# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2"]
# ///
"""Make a stand-in phone scan from a room's model: for demos, tests and rooms whose real scan can't be shared.

Builds the shell from room.json and a layout's furniture (the same models the renders use), then makes it behave
like a LiDAR phone scan: one textured mesh, small per-point noise and slow drift across the room, holes where glass
is (windows, glazed doors) and in a patch of ceiling, and an arbitrary pose (turned about the vertical, floor below
the origin, as a phone app leaves it). The pipeline then treats it like any scan: align_and_render.py, map_room.py,
geometry_check.py, ceiling_compare.py, scan_compare.py and the editor's scan overlay all run on it.

Usage, from inside rooms/<room>/:
  uv run ../../tools/fake_scan.py <layout | path/to/layout.json> [--out scan/scan_raw.glb] [--seed 7]
      [--yaw 12.5] [--offset 1.3,-0.7,-1.15] [--noise 0.006] [--drift 0.015] [--hole x0,y0,x1,y1] [--edge 0.4] [--max-faces 3000]

The layout can hold things the room's own layouts leave out (a basket, a toy box): the geometry check then lists
them as scan blobs no item explains, as it would for real clutter. --hole (repeatable) removes the ceiling over a
rectangle in room coordinates (glossy or dark ceilings scan patchy); default: one 0.6 x 0.5 m patch.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

import bmesh
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

import blender_models
import blender_scene
import roomframe

ROOM = roomframe.ROOM


def srgb_to_linear(h):
    c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


def is_glass(m):
    if m is None:
        return False
    if m.name.startswith("glass"):
        return True
    b = m.node_tree.nodes.get("Principled BSDF") if m.use_nodes and m.node_tree else None
    return bool(b and b.inputs["Transmission Weight"].default_value >= 0.5)


def keep_visible(bm, room, step):
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    xs = [x for x, _ in room["outline"]]
    ys = [y for _, y in room["outline"]]
    views = []
    for x in np.arange(min(xs) + step / 2, max(xs), step):
        for y in np.arange(min(ys) + step / 2, max(ys), step):
            if not roomframe.point_in_poly((x, y), room["outline"]):
                continue
            for z in (0.6, 1.2, 1.7):
                p = Vector((x, y, z))
                inside = False  # a viewpoint inside a closed piece (a sofa's base) sees its inner faces: skip it
                for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                    hit, nrm, _, dist = tree.ray_cast(p, Vector(d), 1.5)
                    if hit is not None and nrm.dot(Vector(d)) > 0:
                        inside = True
                        break
                if not inside:
                    views.append(p)
    hidden = []
    for f in bm.faces:
        c = f.calc_center_median()
        seen = False
        for p in views:
            d = c - p
            L = d.length
            if L < 1e-3:
                continue
            _, _, idx, dist = tree.ray_cast(p, d.normalized(), L + 0.01)
            if idx == f.index or (dist is not None and abs(dist - L) < 0.01):
                seen = True
                break
        if not seen:
            hidden.append(f)
    bmesh.ops.delete(bm, geom=hidden, context="FACES")
    print(f"visibility: {len(views)} viewpoints, {len(hidden)} hidden faces dropped")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("layout", help="layout name in layouts/, or a path to a layout JSON")
    ap.add_argument("--out", default="scan/scan_raw.glb")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--yaw", type=float, default=12.5, help="turn about the vertical, degrees")
    ap.add_argument("--offset", default="1.3,-0.7,-1.15", help="x,y,z of the room's SW floor corner in the scan (m)")
    ap.add_argument("--noise", type=float, default=0.006, help="per-point noise, m (1 sigma)")
    ap.add_argument("--drift", type=float, default=0.015, help="slow drift across the room, m (amplitude)")
    ap.add_argument("--hole", action="append", help="x0,y0,x1,y1: no ceiling over this rectangle (repeatable)")
    ap.add_argument("--edge", type=float, default=0.4, help="split faces until no edge is longer than this (m)")
    ap.add_argument("--view-step", type=float, default=0.6, help="spacing of the walk-through viewpoints (m)")
    ap.add_argument("--max-faces", type=int, default=3000, help="simplify any one object with more faces than this")
    a = ap.parse_args()

    room = json.loads((ROOM / "room.json").read_text())
    lp = Path(a.layout) if a.layout.endswith(".json") else ROOM / f"layouts/{a.layout}.json"
    layout = json.loads(roomframe.require_file(lp, "layout").read_text())
    rng = np.random.default_rng(a.seed)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    coll = bpy.context.scene.collection
    blender_scene.build_room(room, coll)
    blender_models.LAMPS_ON = False
    blender_models.CEILING = 0.0
    blender_models.place_items(layout, blender_models.load_catalog(ROOM), coll, room)
    # the shell's flat materials take the room's own colours, so the scan looks like the room (editor overlay,
    # scan_compare); furniture keeps its catalog colours
    mats = room.get("materials", {})
    for name, key in (("wall", "wall"), ("ceiling", "ceiling"), ("floor", "floor"), ("door", "trim")):
        m = bpy.data.materials.get(name)
        if m and mats.get(key, {}).get("hex"):
            rgb = srgb_to_linear(mats[key]["hex"])
            m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*rgb, 1)

    # glTF carries a flat colour, not Blender's procedural textures (wood grain): give such materials their colour
    for m in bpy.data.materials:
        b = m.node_tree.nodes.get("Principled BSDF") if m.use_nodes and m.node_tree else None
        if b and b.inputs["Base Color"].is_linked:
            for link in list(b.inputs["Base Color"].links):
                m.node_tree.links.remove(link)
            b.inputs["Base Color"].default_value = m.diffuse_color
    # one mesh, like a scan: evaluate modifiers, bake transforms, join
    meshes = [o for o in bpy.context.scene.objects if o.type in ("MESH", "CURVE")]
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.convert(target="MESH")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in meshes:  # a scan sees fine detail (plant leaves, model files) as a rough blob: keep files small
        if len(o.data.polygons) > a.max_faces:
            dec = o.modifiers.new("scan", "DECIMATE")
            dec.ratio = a.max_faces / len(o.data.polygons)
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.modifier_apply(modifier=dec.name)
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.join()
    scan = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in [o for o in bpy.context.scene.objects if o is not scan]:
        bpy.data.objects.remove(o, do_unlink=True)
    scan.name = "scan"

    bm = bmesh.new()
    bm.from_mesh(scan.data)
    slots = scan.data.materials
    # holes: glass (LiDAR goes through it) and patches of ceiling
    holes = [tuple(map(float, h.split(","))) for h in (a.hole or [])] or [(3.4, 2.6, 4.0, 3.1)]
    top = room["ceiling"]["top"]
    gone = []
    for f in bm.faces:
        m = slots[f.material_index] if f.material_index < len(slots) else None
        c = f.calc_center_median()
        ceiling_hole = f.normal.z < -0.9 and c.z > top - 0.05 and any(x0 <= c.x <= x1 and y0 <= c.y <= y1 for x0, y0, x1, y1 in holes)
        if is_glass(m) or ceiling_hole:
            gone.append(f)
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    # split long edges so noise and drift have points to move
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    for _ in range(8):
        long = [e for e in bm.edges if e.calc_length() > a.edge]
        if not long:
            break
        bmesh.ops.subdivide_edges(bm, edges=long, cuts=1, use_grid_fill=False)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    # only what a phone sees from inside the room: drop faces no walk-through viewpoint can see (the outsides of
    # walls, the floor under a sofa, the tops of tall cabinets, the backs of things against a wall)
    keep_visible(bm, room, a.view_step)
    # noise per point, plus a slow drift that grows across the room (phone scans bend a few cm over a room)
    ph = rng.uniform(0, 2 * math.pi, 3)
    for v in bm.verts:
        x, y = v.co.x, v.co.y
        d = a.drift * np.array([math.sin(0.9 * y + ph[0]), math.sin(0.8 * x + ph[1]), 0.6 * math.sin(0.7 * (x + y) + ph[2])])
        v.co += Vector(rng.normal(0, a.noise, 3) + d)
    bm.to_mesh(scan.data)
    bm.free()

    # the pose a phone app leaves: turned about the vertical, the room's corner somewhere, the floor below the origin
    ox, oy, oz = (float(v) for v in a.offset.split(","))
    scan.matrix_world = Matrix.Translation((ox, oy, oz)) @ Matrix.Rotation(math.radians(a.yaw), 4, "Z")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    out = (ROOM / a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    scan.select_set(True)
    # positions and colours only, like a phone scan's mesh (viewers shade it flat): about a third of the size
    bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
                              export_normals=False, export_texcoords=False)
    n = len(scan.data.polygons)
    print(f"wrote {os.path.relpath(out)} ({out.stat().st_size / 1e6:.1f} MB, {n} faces) from {lp.name}: yaw {a.yaw} deg, "
          f"corner at {ox},{oy}, floor at z {oz}, noise {a.noise} m, drift {a.drift} m, seed {a.seed}")


if __name__ == "__main__":
    main()
