# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1"]
# ///
"""Geometry check: where does the model (room.json shell + a layout's furniture) disagree with the 3D scan?

Builds the model and loads the aligned scan into one Blender scene (room frame), then:
  * views: for every room.json camera, casts a ray through every few pixels into the model and into the scan and
    compares the depths. Red = the model has a surface in front of where the scan's is (something modelled that
    isn't there, too big, or misplaced); blue = the scan has a surface in front of the model's (something real that
    the model lacks, is too small or misplaced). Grey = the scan has a hole there (glass, mirror, unscanned), not
    judged. Fast flat (Workbench) renders of scan and model sit next to the overlay.
  * plan: a top-down height map on a 4 cm grid (rays down from 2 m or just under the ceiling): the most direct check
    of furniture footprints and heights.
  * report: every layout item and shell part ranked by how much of it disagrees, plus clusters of scan geometry
    that no item explains (unmodelled furniture or clutter).
Not judged: the shell's "beyond_*" stand-ins for neighbouring rooms, and items whose catalog entry says
"scanVisible": false (glass, crystal, thin wire: LiDAR sees the wall behind them). Glass parts of items (a sauna door,
a glass table top: any Principled material with transmission >= 0.5) are see-through for the rays, so what's behind
them is judged, as the scanner saw it; the shell's windows are not. Fan blades, thin poles and soft
clutter (pillows, throws) also disagree by nature; read their flags with that in mind.

Usage, from inside rooms/<room>/:
  uv run ../../tools/geometry_check.py <layout> \
      [--views a,b] [--tol 0.12] [--res 700x440] [--step 4] [--cell 0.04] [--out dir]

Writes renders/geometry_check/<layout>/{view_<name>.jpg, plan.png, report.txt, report.json}. Not photoreal and
needs no lighting: run it after every geometry or layout change, before any photoreal set.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

from mathutils import Vector
from mathutils.bvhtree import BVHTree

import blender_models
import blender_scene
import roomframe
from roomframe import ceiling_z, point_in_poly

ROOM = Path(os.environ.get("ROOM", ".")).resolve()
RED, BLUE, GREY = (230, 40, 40), (40, 110, 240), (150, 150, 150)
FONT, FONT_BIG = roomframe.font(15), roomframe.font(22)


def owner(ob):
    """Layout item id for a furniture part (place_items tags each item's root empty with "item_id"), else
    'shell:<object>'."""
    root = ob
    while root.parent is not None:
        root = root.parent
    if root.get("item_id"):
        return root["item_id"]
    return root.name if root is not ob or ob.type == "EMPTY" else f"shell:{ob.name.split('.')[0]}"


def is_glass(mat):
    """Furniture glass (a sauna door, a glass table top): LiDAR sees through it, so the check does too."""
    bsdf = mat and mat.use_nodes and next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    return bool(bsdf) and bsdf.inputs["Transmission Weight"].default_value >= 0.5


def bvh_of(objects, see_through_glass=False):
    """One BVH over the evaluated, world-space meshes of `objects`, plus polygon index -> object owner.
    see_through_glass: leave out glass faces of layout items (not the shell's windows), as the scanner does."""
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys, owners = [], [], []
    for ob in objects:
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ob.matrix_world
        base = len(verts)
        verts.extend(mw @ v.co for v in me.vertices)
        glass = set()
        if see_through_glass and not owner(ob).startswith("shell:"):
            glass = {k for k, s in enumerate(ob.material_slots) if is_glass(s.material)}
        for p in me.polygons:
            if p.material_index in glass:
                continue
            polys.append([base + i for i in p.vertices])
            owners.append(ob)
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys, all_triangles=False), owners


def cast(bvh, origins, dirs, max_d=30.0):
    """Distance and polygon index of the first hit for each ray (inf / -1 when nothing is hit)."""
    dist = np.full(len(origins), np.inf)
    idx = np.full(len(origins), -1)
    for k, (o, d) in enumerate(zip(origins, dirs)):
        loc, _, i, dd = bvh.ray_cast(Vector(o), Vector(d), max_d)
        if loc is not None:
            dist[k], idx[k] = dd, i
    return dist, idx


def setup(room, layout_slug):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    coll = bpy.context.scene.collection
    blender_scene.build_room(room, coll)
    blender_models.LAMPS_ON = False
    blender_models.CEILING = 0.0  # ceiling-layer lights off too (geometry only)
    lp = ROOM / f"layouts/{layout_slug}.json"
    if not lp.exists():
        sys.exit(f"no layouts/{layout_slug}.json; layouts: {', '.join(sorted(p.stem for p in (ROOM / 'layouts').glob('*.json')))}")
    layout = json.loads(lp.read_text())
    catalog = blender_models.load_catalog(ROOM)
    blender_models.place_items(layout, catalog, coll, room)
    model_objs = [o for o in bpy.data.objects if o.type == "MESH"]
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(roomframe.require_file(ROOM / "scan/scan_aligned.glb", "aligned scan")))
    scan_objs = [o for o in bpy.data.objects if o not in before]
    OX, OY = room["scan"]["alignedOrigin"]
    shift = bpy.data.objects.new("scan_to_room", None)  # aligned scan -> room frame
    coll.objects.link(shift)
    shift.location = (-OX, -OY, 0)
    for o in scan_objs:
        if o.parent is None:
            o.parent = shift
    bpy.context.view_layer.update()
    scan_meshes = [o for o in scan_objs if o.type == "MESH"]
    return layout, catalog, model_objs, scan_meshes


def camera_rays(cam, w, h):
    """One ray per pixel centre of a w x h grid, the same camera as the renders (roll, sensor fit: roomframe)."""
    dirs = [tuple(d) for d in roomframe.camera_rays(cam, w, h)]
    return [tuple(cam["eye"])] * len(dirs), dirs


def flat_render(objs_show, objs_hide, cam, res, path, textured):
    sc = bpy.context.scene
    for o in objs_hide:
        o.hide_render = True
    for o in objs_show:
        o.hide_render = False
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "FLAT" if textured else "STUDIO"
    sc.display.shading.color_type = "TEXTURE" if textured else "MATERIAL"
    sc.display.shading.show_cavity = not textured
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.world = sc.world or bpy.data.worlds.new("w")
    sc.world.color = (1, 0, 1)
    if sc.camera is None:
        cd = bpy.data.cameras.new("cam")
        cd.clip_start = 0.05
        co = bpy.data.objects.new("cam", cd)
        sc.collection.objects.link(co)
        sc.camera = co
    roomframe.apply_camera(sc.camera, cam)
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return Image.open(path).convert("RGB")


def classify(d_model, d_scan, tol):
    """+1 model in front (extra), -1 scan in front (missing), 0 agree, 2 no scan hit (unknown)."""
    out = np.zeros(len(d_model), dtype=int)
    valid = np.isfinite(d_scan)
    t = tol + 0.03 * np.where(valid, d_scan, 0)  # scans drift a little more far away
    diff = np.where(valid & np.isfinite(d_model), d_model - d_scan, 0)
    out[valid & (diff < -t)] = 1
    out[valid & (diff > t)] = -1
    out[valid & ~np.isfinite(d_model)] = -1
    out[~valid] = 2
    return out


def check_views(room, views, model_bvh, model_owner, scan_bvh, scan_meshes, model_objs, res, step, tol, out_dir, stats, unscannable):
    W, H = res
    gw, gh = W // step, H // step
    summary = {}
    for name in views:
        cam = room["cameras"][name]
        origins, dirs = camera_rays(cam, gw, gh)
        dm, im = cast(model_bvh, origins, dirs)
        ds, _ = cast(scan_bvh, origins, dirs)
        cls = classify(dm, ds, tol)
        # not judged: the model's stand-ins for neighbouring rooms seen through openings (shell "beyond_*"), and items
        # the catalog marks scanVisible: false (glass, crystal, thin wire: the scan sees the wall behind them)
        skip = np.array([i >= 0 and (owner(model_owner[i]).startswith("shell:beyond") or owner(model_owner[i]) in unscannable) for i in im])
        cls[skip] = 2
        for c, i in zip(cls, im):
            if i < 0 or c == 2:
                continue
            s = stats.setdefault(owner(model_owner[i]), {"view_px": 0, "view_extra": 0, "view_missing": 0, "plan_cells": 0, "plan_high": 0, "plan_low": 0})
            s["view_px"] += 1
            s["view_extra"] += c == 1
            s["view_missing"] += c == -1
        judged = cls != 2
        agree = float(np.mean(cls[judged] == 0)) if judged.any() else 0.0
        summary[name] = {"agree": round(agree, 3), "extra": round(float(np.mean(cls[judged] == 1)), 3), "missing": round(float(np.mean(cls[judged] == -1)), 3)}
        scan_img = flat_render(scan_meshes, model_objs, cam, res, out_dir / f"_scan_{name}.png", True)
        model_img = flat_render(model_objs, scan_meshes, cam, res, out_dir / f"_model_{name}.png", False)
        mask = np.zeros((gh, gw, 3), dtype=np.uint8)
        alpha = np.zeros((gh, gw), dtype=np.uint8)
        grid = cls.reshape(gh, gw)
        for val, col, a in ((1, RED, 170), (-1, BLUE, 170), (2, GREY, 90)):
            mask[grid == val] = col
            alpha[grid == val] = a
        ov = Image.fromarray(mask).resize((W, H), Image.NEAREST)
        al = Image.fromarray(alpha).resize((W, H), Image.NEAREST)
        diff_img = Image.composite(ov, scan_img.convert("L").convert("RGB"), al)
        o = Image.new("RGB", (W * 3 + 40, H + 46), "white")
        for k, (im_, title) in enumerate(((scan_img, "SCAN"), (model_img, "MODEL"), (diff_img, f"DIFF  agree {agree:.0%}  red = model extra  blue = model missing  grey = no scan"))):
            o.paste(im_, (k * (W + 20), 46))
            ImageDraw.Draw(o).text((k * (W + 20) + 4, 12), title, fill="black", font=FONT_BIG if k < 2 else FONT)
        o.save(out_dir / f"view_{name}.jpg", quality=88)
        for p in (out_dir / f"_scan_{name}.png", out_dir / f"_model_{name}.png"):
            p.unlink()
        print(f"view {name}: agree {agree:.0%}")
    return summary


def check_plan(room, layout, catalog, model_bvh, model_owner, scan_bvh, cell, tol, out_dir, stats):
    xs = [p[0] for p in room["outline"]]
    ys = [p[1] for p in room["outline"]]
    gx = np.arange(min(xs) + cell / 2, max(xs), cell)
    gy = np.arange(min(ys) + cell / 2, max(ys), cell)
    hm = np.full((len(gy), len(gx)), np.nan)
    hs = np.full_like(hm, np.nan)
    own = np.full(hm.shape, "", dtype=object)
    for j, y in enumerate(gy):
        for i, x in enumerate(gx):
            if not point_in_poly((x, y), room["outline"]):
                continue
            z0 = min(2.0, ceiling_z(room, x, y) - 0.06)
            for bvh, arr in ((model_bvh, hm), (scan_bvh, hs)):
                loc, _, idx, _ = bvh.ray_cast(Vector((x, y, z0)), Vector((0, 0, -1)), z0 + 0.3)
                if loc is not None:
                    arr[j, i] = loc.z
                    if bvh is model_bvh:
                        own[j, i] = owner(model_owner[idx])
    # cells under an item's footprint belong to it even where the model has nothing there (e.g. under a table top)
    foot = np.full(hm.shape, "", dtype=object)
    for it in layout["items"]:
        s = {**catalog.get(it["type"], {}), **it}
        if s.get("ceiling") is not None or s.get("floorLayer"):
            continue
        c, sn = math.cos(math.radians(s.get("rot", 0))), math.sin(math.radians(s.get("rot", 0)))
        bw, bd = s.get("baseW", s["w"]), s.get("baseD", s["d"])
        X, Y = np.meshgrid(gx, gy)
        lx, ly = (X - s["x"]) * c + (Y - s["y"]) * sn, -(X - s["x"]) * sn + (Y - s["y"]) * c
        foot[(abs(lx) <= bw / 2) & (abs(ly) <= bd / 2) & (foot == "")] = it["id"]
    # wall-hung items (sconces, boards) and the walls themselves are judged in the views: in plan they are a cell or
    # two wide and only measure scan drift at the wall
    thin = {it["id"] for it in layout["items"] if {**catalog.get(it["type"], {}), **it}["d"] <= 0.15 or {**catalog.get(it["type"], {}), **it}.get("scanVisible") is False}
    diff = hm - hs
    valid = np.isfinite(diff)
    high = valid & (diff > tol)
    low = valid & (diff < -tol)
    for j in range(len(gy)):
        for i in range(len(gx)):
            if not valid[j, i]:
                continue
            who = own[j, i] if own[j, i] and not own[j, i].startswith("shell:floor") else foot[j, i]
            if not who or who in thin or who.startswith("shell:"):
                continue
            s = stats.setdefault(who, {"view_px": 0, "view_extra": 0, "view_missing": 0, "plan_cells": 0, "plan_high": 0, "plan_low": 0})
            s["plan_cells"] += 1
            s["plan_high"] += bool(high[j, i])
            s["plan_low"] += bool(low[j, i])
    # scan stuff with no item: connected blobs of "scan higher" cells outside every footprint
    lone = low & (foot == "") & np.isfinite(hs) & (hs > 0.15)
    blobs = []
    seen = np.zeros_like(lone)
    for j0, i0 in zip(*np.nonzero(lone)):
        if seen[j0, i0]:
            continue
        stack, cells = [(j0, i0)], []
        seen[j0, i0] = True
        while stack:
            j, i = stack.pop()
            cells.append((j, i))
            for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                jj, ii = j + dj, i + di
                if 0 <= jj < lone.shape[0] and 0 <= ii < lone.shape[1] and lone[jj, ii] and not seen[jj, ii]:
                    seen[jj, ii] = True
                    stack.append((jj, ii))
        if len(cells) * cell * cell >= 0.04:  # ignore anything under ~20 x 20 cm
            rows_, cols_ = zip(*cells)
            blobs.append({"x": [round(gx[min(cols_)] - cell / 2, 2), round(gx[max(cols_)] + cell / 2, 2)], "y": [round(gy[min(rows_)] - cell / 2, 2), round(gy[max(rows_)] + cell / 2, 2)],
                          "area_m2": round(len(cells) * cell * cell, 2), "max_h": round(float(np.nanmax(hs[list(rows_), list(cols_)])), 2)})
    blobs.sort(key=lambda b: -b["area_m2"])
    # image: scan height in grey, mismatches in colour, item footprints outlined and labelled
    px = 10
    h_img = np.clip(np.nan_to_num(hs, nan=0) / 1.2, 0, 1)
    rgb = np.dstack([235 - h_img * 150] * 3).astype(np.uint8)
    rgb[~np.isfinite(hs)] = (255, 220, 255)
    rgb[high] = RED
    rgb[low] = BLUE
    img = Image.fromarray(rgb[::-1]).resize((len(gx) * px, len(gy) * px), Image.NEAREST)
    pad = 30
    canvas = Image.new("RGB", (img.width + 2 * pad, img.height + 2 * pad + 30), "white")
    canvas.paste(img, (pad, pad + 30))
    d = ImageDraw.Draw(canvas)
    x0, y1 = min(xs), max(ys)
    P = lambda x, y: (pad + (x - x0) / cell * px, pad + 30 + (y1 - y) / cell * px)
    d.line([P(*p) for p in room["outline"] + room["outline"][:1]], fill="black", width=2)
    for it in layout["items"]:
        s = {**catalog.get(it["type"], {}), **it}
        if s.get("floorLayer") or s.get("ceiling") is not None:
            continue
        c, sn = math.cos(math.radians(s.get("rot", 0))), math.sin(math.radians(s.get("rot", 0)))
        pts = [(s["x"] + ax * c - ay * sn, s["y"] + ax * sn + ay * c) for ax, ay in ((-s["w"] / 2, -s["d"] / 2), (s["w"] / 2, -s["d"] / 2), (s["w"] / 2, s["d"] / 2), (-s["w"] / 2, s["d"] / 2))]
        d.line([P(*p) for p in pts + pts[:1]], fill=(20, 20, 20), width=1)
        d.text(P(s["x"], s["y"]), it["id"], fill="black", font=FONT, anchor="mm")
    d.text((pad, 8), f"PLAN height check (cell {cell * 100:.0f} cm, tol {tol * 100:.0f} cm): red = model higher than the scan, blue = scan higher than the model. Grey = scan height (darker = taller).", fill="black", font=FONT)
    canvas.save(out_dir / "plan.png")
    print(f"plan: {int(high.sum())} cells model-high, {int(low.sum())} cells scan-high of {int(valid.sum())}")
    return blobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("--views", help="comma-separated room.json cameras (default: all)")
    ap.add_argument("--tol", type=float, default=0.12, help="depth/height tolerance in metres")
    ap.add_argument("--res", default="700x440")
    ap.add_argument("--step", type=int, default=4, help="cast one ray every N pixels in the views")
    ap.add_argument("--cell", type=float, default=0.04, help="plan grid cell (m)")
    ap.add_argument("--no-plan", action="store_true")
    ap.add_argument("--out", help="output folder (default renders/geometry_check/<layout> in the room)")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    room = roomframe.normalize_room(json.loads((ROOM / "room.json").read_text()))
    views = a.views.split(",") if a.views else list(room.get("cameras", {}))
    roomframe.check_views(room, views)
    out_dir = Path(a.out).resolve() if a.out else ROOM / f"renders/geometry_check/{a.layout}"
    out_dir.mkdir(parents=True, exist_ok=True)
    layout, catalog, model_objs, scan_meshes = setup(room, a.layout)
    model_bvh, model_owner = bvh_of(model_objs, see_through_glass=True)
    scan_bvh, _ = bvh_of(scan_meshes)
    stats = {}
    unscannable = {it["id"] for it in layout["items"] if {**catalog.get(it["type"], {}), **it}.get("scanVisible") is False}
    summary = check_views(room, views, model_bvh, model_owner, scan_bvh, scan_meshes, model_objs, tuple(int(v) for v in a.res.split("x")), a.step, a.tol, out_dir, stats, unscannable)
    blobs = [] if a.no_plan else check_plan(room, layout, catalog, model_bvh, model_owner, scan_bvh, a.cell, a.tol, out_dir, stats)
    names = {it["id"]: catalog.get(it["type"], {}).get("name", it["type"]) for it in layout["items"]}
    rows = []
    for who, s in stats.items():
        v = (s["view_extra"] + s["view_missing"]) / s["view_px"] if s["view_px"] >= 30 else None
        p = (s["plan_high"] + s["plan_low"]) / s["plan_cells"] if s["plan_cells"] >= 10 else None
        worst = max(x for x in (v, p, 0) if x is not None)
        rows.append({"id": who, "name": names.get(who, who), "view_mismatch": v, "plan_mismatch": p, "plan_model_high": s["plan_high"], "plan_model_low": s["plan_low"], "worst": worst})
    rows.sort(key=lambda r: -r["worst"])
    fmt = lambda x: "  -  " if x is None else f"{x:5.0%}"
    lines = [f"Geometry check: {a.layout} (tol {a.tol * 100:.0f} cm)", "", "Views (share of scanned pixels where model and scan agree):"]
    lines += [f"  {k:24s} agree {v['agree']:.0%}   model extra {v['extra']:.0%}   model missing {v['missing']:.0%}" for k, v in summary.items()]
    lines += ["", "Items and shell parts, worst first (views = pixels off; plan = 4 cm cells off; high/low = model above/below the scan):"]
    for r in rows:
        flag = "CHECK" if r["worst"] >= 0.25 else "     "
        lines.append(f"  {flag} {r['id']:22s} views {fmt(r['view_mismatch'])}  plan {fmt(r['plan_mismatch'])}  (high {r['plan_model_high']}, low {r['plan_model_low']})  {r['name']}")
    if blobs:
        lines += ["", "Scan geometry no layout item explains (unmodelled furniture, or clutter):"]
        lines += [f"  x {b['x'][0]:.2f}-{b['x'][1]:.2f}  y {b['y'][0]:.2f}-{b['y'][1]:.2f}  {b['area_m2']:.2f} m2  up to {b['max_h']:.2f} m" for b in blobs[:15]]
    text = "\n".join(lines) + "\n"
    (out_dir / "report.txt").write_text(text)
    (out_dir / "report.json").write_text(json.dumps({"views": summary, "items": rows, "unexplained": blobs}, indent=2) + "\n")
    print(text)
    print("wrote", out_dir)


if __name__ == "__main__":
    main()
