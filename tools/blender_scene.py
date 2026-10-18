# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1"]
# ///
"""Build the room shell from room.json in Blender (bpy) and render it next to the scan.

Usage:
  uv run ../../tools/blender_scene.py compare

The `build_room` function is the start of the photoreal pipeline: same geometry the editor uses.
Room frame: x east, y north, z up (meters). room.json scan.alignedOrigin says where the room origin sits in the aligned scan.
"""

import itertools
import json
import math
import os
import sys
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy  # must come before bmesh (bpy registers it)

import bmesh
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roomframe

REPO = Path(__file__).resolve().parent.parent  # repo root: shared catalog, materials, models
ROOM = Path(os.environ.get("ROOM", ".")).resolve()  # room folder (run from inside rooms/<room>/ or set ROOM=)


def mat(name, color, rough=0.8):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    return m


def mesh_obj(name, bm, material, coll):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(material)
    coll.objects.link(ob)
    return ob


def prism(poly, z0, z1, slope=None):
    """Vertical prism over a plan polygon; optional linear slope on the underside."""
    bm = bmesh.new()

    def zb(x, y):
        if not slope:
            return z0
        t = x if slope["axis"] == "x" else y
        t = min(max(t, slope["from"]), slope["to"])
        return slope["zFrom"] + (slope["zTo"] - slope["zFrom"]) * (t - slope["from"]) / (slope["to"] - slope["from"])

    bot = [bm.verts.new((x, y, zb(x, y))) for x, y in poly]
    top = [bm.verts.new((x, y, z1)) for x, y in poly]
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([bot[i], bot[j], top[j], top[i]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def box(x0, y0, z0, x1, y1, z1):
    return prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1)


# red (lowest ceiling in the room) -> yellow -> green -> blue (highest); stops are fractions of the room's range
PALETTE_F = [(0.0, (0.78, 0.16, 0.16)), (0.32, (0.94, 0.70, 0.20)), (0.58, (0.55, 0.78, 0.42)), (1.0, (0.25, 0.47, 0.82))]
HRANGE = [1.80, 2.33]  # set per room in build_room()


def height_color(z):
    lo, hi = HRANGE
    PALETTE = [(lo + f * (hi - lo), c) for f, c in PALETTE_F]
    for (z0, c0), (z1, c1) in itertools.pairwise(PALETTE):
        if z <= z1:
            f = max(0.0, (z - z0) / (z1 - z0))
            return tuple(c0[k] + (c1[k] - c0[k]) * f for k in range(3))
    return PALETTE[-1][1]


def build_room(room, coll, color_ceiling=False):
    roomframe.normalize_room(room)
    zs = [d["z"] for d in room["ceiling"]["downstands"]] + [z for d in room["ceiling"]["downstands"] if d.get("slope") for z in (d["slope"]["zFrom"], d["slope"]["zTo"])]
    HRANGE[:] = [min(zs + [room["ceiling"]["top"]]) - 0.03, room["ceiling"]["top"]]
    top = room["ceiling"]["top"]
    T = room["wallThickness"]
    wall_m = mat("wall", (0.72, 0.76, 0.73), 0.9)
    ceil_m = mat("ceiling", (0.92, 0.91, 0.88), 0.9)
    floor_m = mat("floor", (0.62, 0.45, 0.30), 0.6)
    trim_m = mat("door", (0.95, 0.95, 0.93), 0.5)
    glass_m = mat("glass", (0.7, 0.85, 0.95), 0.05)

    outline = room["outline"]
    bm = bmesh.new()
    bm.faces.new([bm.verts.new((x, y, 0)) for x, y in outline])
    mesh_obj("floor", bm, floor_m, coll)

    # walls: split each outline edge around doors/windows
    n = len(outline)
    for i in range(n):
        a, b = Vector((*outline[i], 0)), Vector((*outline[(i + 1) % n], 0))
        u = (b - a).normalized()
        L = (b - a).length
        nrm = Vector((-u.y, u.x, 0))  # inward (outline is CCW)
        prev = Vector((*outline[i - 1], 0))
        nxt = Vector((*outline[(i + 2) % n], 0))
        # extend the wall prism past its ends only at convex (outside) corners, where the neighbour's prism leaves a gap;
        # at reflex corners (e.g. a chimney breast or a step in a wall) extending would poke into the room; there the
        # prism stops 3 mm short so its end face hides inside the neighbour instead of lying coplanar on its face (black)
        ext_a = T if ((a - prev).x * u.y - (a - prev).y * u.x) > 0 else -0.003
        ext_b = T if (u.x * (nxt - b).y - u.y * (nxt - b).x) > 0 else -0.003
        ops = []

        def on_edge(p):
            v = Vector((*p, 0)) - a
            return v.dot(u) if abs(v.dot(nrm)) < 0.03 and -0.03 < v.dot(u) < L + 0.03 else None

        for d in room["doors"]:
            ta, tb = on_edge(d["a"]), on_edge(d["b"])
            if ta is not None and tb is not None:
                ops.append((min(ta, tb), max(ta, tb), 0, d["height"], "door", d))
        for w in room["windows"]:
            ta, tb = on_edge(w["a"]), on_edge(w["b"])
            if ta is not None and tb is not None:
                ops.append((min(ta, tb), max(ta, tb), w["z0"], w["z1"], "window", w))
        ops.sort(key=lambda o: o[0])

        def piece(t0, t1, z0, z1, m=wall_m, inset=0.0, depth=T):
            if t1 - t0 < 0.005 or z1 - z0 < 0.005:
                return
            p0 = a + u * t0 - nrm * inset
            p1 = a + u * t1 - nrm * inset
            q0, q1 = p0 - nrm * depth, p1 - nrm * depth
            mesh_obj("wall", prism([(p0.x, p0.y), (p1.x, p1.y), (q1.x, q1.y), (q0.x, q0.y)], z0, z1), m, coll)

        casing = room.get("casings")  # optional white casings/frames (opt-in so older rooms render unchanged)
        cw = 0.075  # casing width

        def case(t0, t1, z0, z1, sill=False):
            piece(t0 - cw, t0, 0 if not sill else z0 - 0.03, z1 + cw, trim_m, -0.015, 0.015)
            piece(t1, t1 + cw, 0 if not sill else z0 - 0.03, z1 + cw, trim_m, -0.015, 0.015)
            piece(t0, t1, z1, z1 + cw, trim_m, -0.015, 0.015)
            if sill:
                piece(t0 - cw, t1 + cw, z0 - 0.03, z0, trim_m, -0.03, 0.03)

        def grilles(t0, t1, z0, z1, cols, rows, mid=T / 2):
            for k in range(1, cols):
                tt = t0 + (t1 - t0) * k / cols
                piece(tt - 0.012, tt + 0.012, z0, z1, trim_m, mid - 0.015, 0.03)
            for k in range(1, rows):
                zz = z0 + (z1 - z0) * k / rows
                piece(t0, t1, zz - 0.012, zz + 0.012, trim_m, mid - 0.015, 0.03)
            for tt in (t0, t1 - 0.03):  # sash frame sides
                piece(tt, tt + 0.03, z0, z1, trim_m, mid - 0.02, 0.04)
            piece(t0, t1, z0, z0 + 0.04, trim_m, mid - 0.02, 0.04)
            piece(t0, t1, z1 - 0.04, z1, trim_m, mid - 0.02, 0.04)

        t = -ext_a
        for t0, t1, z0, z1, kind, obj in ops:
            piece(t, t0, 0, top)
            piece(t0, t1, 0, z0)
            piece(t0, t1, z1, top)
            if kind == "window":
                piece(t0, t1, z0, z1, glass_m, T / 2, 0.01)
                if obj.get("grid"):
                    grilles(t0, t1, z0, z1, *obj["grid"])
                if casing:
                    case(t0, t1, z0, z1, sill=True)
            else:
                style = obj.get("style", "door")
                if style == "door":
                    piece(t0 + 0.03, t1 - 0.03, 0, z1 - 0.02, trim_m, T - 0.04, 0.04)
                elif style == "glass":  # glazed (French) doors: glass with sash frames and grilles
                    piece(t0, t1, 0, z1, glass_m, T / 2, 0.01)
                    mid_t = (t0 + t1) / 2
                    grilles(t0, mid_t, 0, z1, *obj.get("grid", (2, 5)))
                    grilles(mid_t, t1, 0, z1, *obj.get("grid", (2, 5)))
                elif style == "opening" and obj.get("beyond", True):
                    # cased opening: a hint of the next room (floor + back wall) so it isn't a void
                    p0 = a + u * t0 - nrm * (T + 0.002)
                    p1 = a + u * t1 - nrm * (T + 0.002)
                    far = room.get("beyondDepth", 1.6)
                    q0, q1 = p0 - nrm * far - u * 0.6, p1 - nrm * far + u * 0.6
                    hall = mat("beyond_wall", (0.62, 0.58, 0.52), 0.9)
                    mesh_obj("beyond_floor", prism([(p0.x - u.x * 0.6, p0.y - u.y * 0.6), (p1.x + u.x * 0.6, p1.y + u.y * 0.6), (q1.x, q1.y), (q0.x, q0.y)], -0.01, 0.0), floor_m, coll)
                    r0, r1 = q0 - nrm * 0.1, q1 - nrm * 0.1
                    mesh_obj("beyond_wall", prism([(q0.x, q0.y), (q1.x, q1.y), (r1.x, r1.y), (r0.x, r0.y)], 0, top), hall, coll)
                    for e0, e1 in ((p0 - u * 0.6, q0), (p1 + u * 0.6, q1)):  # side walls of the next room
                        f0, f1 = e0 - u * 0.1 * (1 if e0 == p0 - u * 0.6 else -1), e1 - u * 0.1 * (1 if e1 == q0 else -1)
                        mesh_obj("beyond_wall", prism([(e0.x, e0.y), (e1.x, e1.y), (f1.x, f1.y), (f0.x, f0.y)], 0, top), hall, coll)
                    mesh_obj("beyond_ceiling", prism([(p0.x - u.x * 0.6, p0.y - u.y * 0.6), (p1.x + u.x * 0.6, p1.y + u.y * 0.6), (q1.x, q1.y), (q0.x, q0.y)], top, top + 0.02), ceil_m, coll)
                elif style == "sliding":  # multi-panel sliding glass door (e.g. OXXO): glass, frame, mullions, handles
                    piece(t0, t1, 0, z1, glass_m, T / 2, 0.01)
                    fr = 0.055
                    for tt0, tt1 in ((t0, t0 + fr), (t1 - fr, t1)):  # jambs
                        piece(tt0, tt1, 0, z1, trim_m, T / 2 - 0.03, 0.06)
                    piece(t0, t1, z1 - fr * 2, z1, trim_m, T / 2 - 0.03, 0.06)  # head
                    piece(t0, t1, 0, 0.05, trim_m, T / 2 - 0.03, 0.06)  # sill
                    ax_i = 1 if abs(u.y) > abs(u.x) else 0
                    for mz in obj.get("mullions", []):
                        pt = list(obj["a"])
                        pt[ax_i] = mz
                        tm = on_edge(pt)
                        if tm is None:
                            continue
                        piece(tm - fr, tm + fr, 0, z1, trim_m, T / 2 - 0.035, 0.07)
                    for mz in obj.get("handlesAt", []):  # pull handles on the operable panels' meeting stiles
                        pt = list(obj["a"])
                        pt[ax_i] = mz
                        tm = on_edge(pt)
                        if tm is None:
                            continue
                        hm = mat("door_handle", (0.05, 0.05, 0.05), 0.4)
                        for off in (-0.08, 0.08):
                            piece(tm + off - 0.012, tm + off + 0.012, 0.85, 1.15, hm, -0.03, 0.03)
                # style == "opening": cased opening, nothing in it
                if casing:
                    case(t0, t1, 0, z1)
            t = t1
        piece(t, L + ext_b, 0, top)

    # ceiling: slab at top + downstands hanging from it
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    top_m = mat("ceil_top", height_color(top), 0.9) if color_ceiling else ceil_m
    mesh_obj("ceiling", box(min(xs) - T, min(ys) - T, top, max(xs) + T, max(ys) + T, top + 0.05), top_m, coll)
    labels = []
    for ds in room["ceiling"]["downstands"]:
        poly = ds.get("poly") or [(ds["rect"][0], ds["rect"][1]), (ds["rect"][2], ds["rect"][1]), (ds["rect"][2], ds["rect"][3]), (ds["rect"][0], ds["rect"][3])]
        sl = ds.get("slope")
        zc = (sl["zFrom"] + sl["zTo"]) / 2 if sl else ds["z"]
        m = mat(f"ceil_{ds['name']}", height_color(zc), 0.9) if color_ceiling else ceil_m
        bm = prism(poly, ds["z"], top, sl)
        if not color_ceiling:  # soffit sides are painted the wall color; undersides stay ceiling white
            for f in bm.faces:
                f.material_index = 1 if abs(f.normal.z) < 0.5 else 0
        ob = mesh_obj(ds["name"], bm, m, coll)
        if not color_ceiling:
            ob.data.materials.append(wall_m)
        cx, cy = sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)
        text = f"{ds['name']}  {sl['zFrom']:.2f}->{sl['zTo']:.2f} m (slanted)" if sl else f"{ds['name']}  {ds['z']:.2f} m"
        labels.append((text, (cx, cy, zc - 0.01)))
    tl = room["ceiling"].get("topLabel")  # optional label(s) for areas at full ceiling height
    for x, y in (tl or {}).get("at", []):
        labels.append((f"{tl['name']}  {top:.2f} m", (x, y, top - 0.01)))

    for f in room["fixtures"]:
        if f.get("kind") in FIXTURE_BUILDERS:
            build_on_wall(f, coll, trim_m)
            continue
        if f["wall"] in ("north", "south"):
            s = -1 if f["wall"] == "north" else 1
            y0, y1 = sorted([f["y"], f["y"] + s * f["depth"]])
            bmf = box(f["x0"], y0, f["z0"], f["x1"], y1, f["z1"])
        else:
            s = -1 if f["wall"] == "east" else 1
            x0, x1 = sorted([f["x"], f["x"] + s * f["depth"]])
            bmf = box(x0, f["y0"], f["z0"], x1, f["y1"], f["z1"])
        hx = f.get("color", "#1a1a1a").lstrip("#")
        rgb = tuple((int(hx[i:i + 2], 16) / 255) ** 2.2 for i in (0, 2, 4))
        mesh_obj(f["id"], bmf, mat(f["id"], rgb, 0.4), coll)
        if f.get("screen") is not None and f["id"] in SCREENS_ON:
            add_screen(f, coll)
    return labels


SCREENS_ON = set()  # fixture ids whose `screen` is lit (a TV left on); set per scene by render_photoreal ("screens")


def add_screen(f, coll):
    """A lit screen on the front face of a wall fixture (a TV): `screen` {luminance (cd/m², average over the picture),
    hex (average colour)}. Its light is part of the scene, so a TV left on shows up as a coloured cast."""
    import blender_models
    import photometry as ph

    sp = f["screen"]
    if "luminance" not in sp or "hex" not in sp:
        blender_models.ASSUMED.append((f"{f['id']} screen", f["id"], None if "luminance" in sp else "150 cd/m²", None if "hex" in sp else "white"))
    hx = sp.get("hex", "#ffffff").lstrip("#")
    srgb = [int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    y = ph.luminance(lin) or 1.0
    rgb = tuple(c / y for c in lin)
    lum = sp.get("luminance", 150)
    m = bpy.data.materials.new(f"{f['id']}_screen")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*rgb, 1)
    em.inputs["Strength"].default_value = ph.emission_strength(lum)
    nt.links.new(em.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    e, t = 0.015, 0.002  # edge inset; thickness, in front of the face
    s = -1 if f["wall"] in ("north", "east") else 1  # direction into the room
    if f["wall"] in ("north", "south"):
        yf = f["y"] + s * f["depth"]
        bm = box(f["x0"] + e, min(yf, yf + s * t), f["z0"] + e, f["x1"] - e, max(yf, yf + s * t), f["z1"] - e)
    else:
        xf = f["x"] + s * f["depth"]
        bm = box(min(xf, xf + s * t), f["y0"] + e, f["z0"] + e, max(xf, xf + s * t), f["y1"] - e, f["z1"] - e)
    ob = mesh_obj(f"{f['id']}_screen", bm, m, coll)
    along = (f["x1"] - f["x0"]) if f["wall"] in ("north", "south") else (f["y1"] - f["y0"])
    area = (along - 2 * e) * (f["z1"] - f["z0"] - 2 * e)
    ob.lightgroup = blender_models.light_group(f"screen_{f['id']}", {"kind": "screen", "fixture": f["id"], "luminance": lum, "lumens": None,
                                                                    "kelvin": None, "dim": 1.0, "rgb": rgb, "flux": lum * math.pi * area,
                                                                    "label": f"{f['id']} screen", "assumed": "luminance" not in sp})


ACCENTS_ON = False  # accent lights (niche pucks, picture lights); set per scene by render_photoreal
FIRE_ON = False  # fireplace flame


def _accent_light(name, loc, spec, n, legacy_watts, rot=(math.pi, 0, 0), spot_deg=100, fixture=""):
    """Small hidden spot (puck or picture light), one of n sharing the fixture's `lights` / `pictureLight`
    {lumens (all n together), kelvin}. Without data: the old default watts converted like builder bulbs (ASSUMED).
    Points down by default."""
    import blender_models
    import photometry as ph

    legacy = n * spec.get("watts", legacy_watts) * ph.luminance((1.0, 0.78, 0.55)) * ph.LEGACY_LM_PER_W * ph.cone_solid_angle(spot_deg) / (4 * math.pi)
    lumens, kelvin = spec.get("lumens", legacy), spec.get("kelvin") or blender_models.ROOM_KELVIN or ph.DEFAULT_KELVIN
    has_k = "kelvin" in spec or bool(blender_models.ROOM_KELVIN)  # the room's usual bulb colour counts as given
    if ("lumens" not in spec or not has_k) and not any(a[1] == fixture for a in blender_models.ASSUMED):
        blender_models.ASSUMED.append((f"{fixture} {name.replace('_', ' ')}s", fixture, None if "lumens" in spec else f"{lumens:.0f} lm",
                                       None if has_k else f"{kelvin:.0f} K"))
    rgb = ph.kelvin_rgb(kelvin)
    ld = bpy.data.lights.new(name, "SPOT")
    ld.energy, ld.color, ld.spot_size, ld.spot_blend, ld.shadow_soft_size = ph.spot_watts(lumens / n, spot_deg), rgb, math.radians(spot_deg), 0.7, 0.03
    lo = bpy.data.objects.new(name, ld)
    lo.location, lo.rotation_euler = loc, rot
    lo.visible_camera = lo.visible_glossy = lo.visible_transmission = False
    lo.lightgroup = blender_models.light_group("accents", {"kind": "accents", "lumens": None, "kelvin": None, "dim": 1.0, "rgb": rgb, "label": "accent lights"})
    bpy.context.scene.collection.objects.link(lo)
    return lo


# ---- architectural fixtures on a north wall (wall face at y = f["y"], projecting toward -y by f["depth"]) ----


def _xz_prism(pts, y0, y1):
    """Prism from a polygon in the x-z plane, extruded from y0 to y1."""
    bm = bmesh.new()
    a = [bm.verts.new((x, y0, z)) for x, z in pts]
    b = [bm.verts.new((x, y1, z)) for x, z in pts]
    bm.faces.new(a)
    bm.faces.new(list(reversed(b)))
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        bm.faces.new([a[i], b[i], b[j], a[j]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def fx_fireplace(f, coll, white):
    """Painted surround with a black firebox, mantel shelf, stone hearth. `insert`: "none" (default: an empty firebox, e.g. a
    decorative or painted-out fireplace), "wood" (open firebox with wood logs) or "gas" (black frame, louvre and glass
    in front of ceramic logs). The fire's light: `fire` {lumens, kelvin}; defaults (photometry.DEFAULT_FIRE,
    listed as ASSUMED): a gas insert gives little light, an open wood fire much more."""
    Y, D, x0, x1, z1 = f["y"], f["depth"], f["x0"], f["x1"], f["z1"]
    insert = f.get("insert", "none")
    yf = Y - D
    cx = (x0 + x1) / 2
    fw, fz0, fz1 = f.get("fireboxW", 0.92), 0.12, f.get("fireboxTop", 0.82)
    stone = mat("hearth_stone", (0.42, 0.4, 0.37), 0.4)
    mesh_obj("surround", box(x0, yf, 0, cx - fw / 2, Y - 0.002, z1 - 0.06), white, coll)
    mesh_obj("surround", box(cx + fw / 2, yf, 0, x1, Y - 0.002, z1 - 0.06), white, coll)
    mesh_obj("surround", box(cx - fw / 2, yf, fz1, cx + fw / 2, Y - 0.002, z1 - 0.06), white, coll)
    # firebox: charcoal back and cheeks; a gas insert adds a black metal frame and glass
    mesh_obj("firebox_floor", box(cx - fw / 2, yf + 0.004, 0, cx + fw / 2, Y - 0.004, fz0), stone, coll)
    charcoal = mat("firebox_charcoal", (0.025, 0.022, 0.02), 0.95)
    frame = mat("insert_frame", (0.015, 0.015, 0.015), 0.35)
    mesh_obj("firebox", box(cx - fw / 2 + 0.002, Y - 0.012, fz0, cx + fw / 2 - 0.002, Y - 0.004, fz1), charcoal, coll)
    for sx in (-1, 1):  # firebox inner cheeks
        mesh_obj("firebox", box(cx + sx * fw / 2 - (0.01 if sx > 0 else 0), yf + 0.02, fz0, cx + sx * fw / 2 + (0.01 if sx < 0 else 0), Y - 0.012, fz1), charcoal, coll)
    fr = 0.045
    if insert == "gas":
        mesh_obj("insert_frame", box(cx - fw / 2, yf - 0.006, fz0, cx - fw / 2 + fr, yf + 0.01, fz1), frame, coll)
        mesh_obj("insert_frame", box(cx + fw / 2 - fr, yf - 0.006, fz0, cx + fw / 2, yf + 0.01, fz1), frame, coll)
        mesh_obj("insert_frame", box(cx - fw / 2, yf - 0.006, fz1 - fr, cx + fw / 2, yf + 0.01, fz1), frame, coll)
        mesh_obj("insert_frame", box(cx - fw / 2, yf - 0.006, fz0, cx + fw / 2, yf + 0.01, fz0 + 0.06), frame, coll)  # louvre
    if insert == "none":
        mesh_obj("mantel", box(x0 - 0.08, yf - 0.1, z1 - 0.06, x1 + 0.08, Y - 0.001, z1), white, coll)
        for zz in (fz1 + 0.06, fz1 + 0.24):  # frieze moulding lines
            mesh_obj("frieze", box(cx - fw / 2 - 0.05, yf - 0.012, zz, cx + fw / 2 + 0.05, yf, zz + 0.025), white, coll)
        mesh_obj("hearth", box(x0 - 0.05, yf - f.get("hearthDepth", 0.45), 0, x1 + 0.05, yf + 0.002, 0.025), stone, coll)
        return
    logm = mat("ceramic_log", (0.16, 0.1, 0.06), 0.9) if insert == "gas" else mat("wood_log", (0.2, 0.12, 0.06), 0.95)
    for k, (dx, ang, rr) in enumerate(((-0.12, 0.25, 0.045), (0.14, -0.2, 0.042), (0.0, 0.05, 0.04))):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=rr, radius2=rr * 0.9, depth=fw * 0.55)
        ob = mesh_obj("log", bm, logm, coll)
        ob.location = (cx + dx, Y - 0.06 - 0.02 * k, fz0 + 0.07 + rr + (0.06 if k == 2 else 0))
        ob.rotation_euler = (0, math.pi / 2, ang)
    if FIRE_ON and insert != "none":  # flames: glowing flame shapes along the logs (seen, not lighting) + the fire's light
        import blender_models
        import photometry as ph

        spec = {**ph.DEFAULT_FIRE[insert], **f.get("fire", {})}
        missing = [k for k in ("lumens", "kelvin") if k not in f.get("fire", {})]
        if missing:
            blender_models.ASSUMED.append((f"{f['id']} fire ({insert})", f["id"], f"{spec['lumens']:.0f} lm" if "lumens" in missing else None,
                                           f"{spec['kelvin']:.0f} K" if "kelvin" in missing else None))
        rgb = ph.kelvin_rgb(spec["kelvin"])
        group = blender_models.light_group(f"fire_{f['id']}", {"kind": "fire", "fixture": f["id"], "lumens": spec["lumens"], "kelvin": spec["kelvin"],
                                                               "dim": 1.0, "rgb": rgb, "label": f"{f['id']} fire", "assumed": "lumens" not in f.get("fire", {})})
        flame = bpy.data.materials.get("flame") or bpy.data.materials.new("flame")
        flame.use_nodes = True
        fb = flame.node_tree.nodes["Principled BSDF"]
        fb.inputs["Base Color"].default_value = (*rgb, 1)
        fb.inputs["Emission Color"].default_value = (*rgb, 1)
        fb.inputs["Emission Strength"].default_value = ph.emission_strength(4000)  # a yellow flame is a few thousand cd/m²
        for k in range(9):
            fx = cx - fw * 0.32 + k * fw * 0.08
            hh = 0.12 + 0.07 * ((k * 37) % 5) / 4
            bm = bmesh.new()
            bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.045, radius2=0.004, depth=hh * 0.8)
            ob = mesh_obj("flame", bm, flame, coll)
            ob.location = (fx, Y - 0.08, fz0 + 0.13 + hh / 2)
            ob.visible_diffuse = ob.visible_shadow = False  # the point light below carries the fire's lumens
        fl = bpy.data.lights.new("fire_glow", "POINT")
        fl.energy, fl.color, fl.shadow_soft_size = ph.watts(spec["lumens"]), rgb, 0.25
        flo = bpy.data.objects.new("fire_glow", fl)
        flo.lightgroup = group
        flo.location = (cx, yf - 0.05, fz0 + 0.3)
        flo.visible_camera = flo.visible_glossy = False
        coll.objects.link(flo)
    if insert == "gas":
        glass = mat("insert_glass", (0.2, 0.2, 0.2), 0.05)
        mesh_obj("insert_glass", box(cx - fw / 2 + fr, yf + 0.004, fz0 + 0.06, cx + fw / 2 - fr, yf + 0.006, fz1 - fr), glass, coll)
        if glass.node_tree:
            bsdf = glass.node_tree.nodes["Principled BSDF"]
            bsdf.inputs["Transmission Weight"].default_value = 0.92
            bsdf.inputs["Roughness"].default_value = 0.03
    mesh_obj("mantel", box(x0 - 0.08, yf - 0.1, z1 - 0.06, x1 + 0.08, Y - 0.001, z1), white, coll)
    for zz in (fz1 + 0.06, fz1 + 0.24):  # frieze moulding lines
        mesh_obj("frieze", box(cx - fw / 2 - 0.05, yf - 0.012, zz, cx + fw / 2 + 0.05, yf, zz + 0.025), white, coll)
    mesh_obj("hearth", box(x0 - 0.05, yf - f.get("hearthDepth", 0.45), 0, x1 + 0.05, yf + 0.002, 0.025), stone, coll)


def fx_panel(f, coll, white):
    """Painted panelling over a wall face, with raised rectangular mouldings."""
    Y, x0, x1, z0, z1 = f["y"], f["x0"], f["x1"], f["z0"], f["z1"]
    mesh_obj("panel", box(x0 + 0.002, Y - 0.012, z0, x1 - 0.002, Y - 0.003, z1), white, coll)
    cols = f.get("cols", 2)
    gap = 0.12
    pw = (x1 - x0 - gap * (cols + 1)) / cols
    for i in range(cols):
        px = x0 + gap + i * (pw + gap)
        for (a, b_, c, d_) in ((px, z0 + gap, px + pw, z0 + gap + 0.025), (px, z1 - gap - 0.025, px + pw, z1 - gap),
                               (px, z0 + gap, px + 0.025, z1 - gap), (px + pw - 0.025, z0 + gap, px + pw, z1 - gap)):
            mesh_obj("moulding", box(a, Y - 0.024, b_, c, Y - 0.012, d_), white, coll)


def fx_niche(f, coll, white):
    """Built-in cabinet with an arched open niche and shelves."""
    Y, D, z1 = f["y"], f["depth"], f["z1"]
    x0, x1 = f["x0"] + 0.003, f["x1"] - 0.003  # stay off adjoining wall faces (coplanar faces render black)
    yf = Y - D
    st = 0.07  # stile width
    cx, r = (x0 + x1) / 2, (x1 - x0) / 2 - st
    zs = f.get("springZ", 1.8)  # arch springline
    mesh_obj("niche_stile", box(x0, yf, 0, x0 + st, Y - 0.002, z1), white, coll)
    mesh_obj("niche_stile", box(x1 - st, yf, 0, x1, Y - 0.002, z1), white, coll)
    mesh_obj("niche_base", box(x0 + st, yf, 0, x1 - st, Y - 0.002, 0.08), white, coll)
    mesh_obj("niche_back", box(x0 + st, Y - 0.014, 0.08, x1 - st, Y - 0.004, zs + r), white, coll)
    # arched face plate: rectangle above the springline minus the semicircle
    pts = [(x0 + st, zs), (x0 + st, z1), (x1 - st, z1), (x1 - st, zs)]
    for k in range(17):
        a = math.pi * k / 16
        pts.append((cx + r * math.cos(a), zs + r * math.sin(a)))
    mesh_obj("niche_arch", _xz_prism(pts, yf, yf + 0.03), white, coll)
    mesh_obj("niche_cap", box(x0 + st, yf + 0.03, zs + r - 0.01, x1 - st, Y - 0.014, zs + r), white, coll)
    shelves = f.get("shelves", [0.42, 0.78, 1.14, 1.5])
    if ACCENTS_ON and f.get("lights"):  # puck light under each shelf and in the arch, lighting the shelf below
        tops = shelves[1:] + [zs + r - 0.02]
        for zz_ in tops:
            _accent_light("niche_puck", (cx, Y - 0.17, zz_ - 0.01), f["lights"], len(tops), 4, fixture=f["id"])
    for zz in shelves:
        mesh_obj("niche_shelf", box(x0 + st, yf + 0.02, zz, x1 - st, Y - 0.014, zz + 0.025), white, coll)
        if f.get("styled", True):  # a few books / objects per shelf
            for i, (w_, h_, col) in enumerate(((0.05, 0.24, (0.45, 0.2, 0.12)), (0.04, 0.22, (0.18, 0.25, 0.35)), (0.06, 0.26, (0.7, 0.66, 0.58)))):
                bx = x0 + st + 0.05 + i * 0.065 + (0.25 if int(zz * 10) % 2 else 0)
                mesh_obj("niche_book", box(bx, Y - 0.2, zz + 0.025, bx + w_, Y - 0.02, zz + 0.025 + h_), mat(f"book{i}", col, 0.6), coll)


def fx_shelves(f, coll, white):
    """Built-in open shelving on any wall: side panels, top, shelves, a few books. Fields: wall, along-wall range
    (x0/x1 for north/south, y0/y1 for east/west), wall-face coordinate (y or x), depth, z0/z1."""
    vertical = f["wall"] in ("east", "west")
    s0, s1 = (f["y0"], f["y1"]) if vertical else (f["x0"], f["x1"])
    face = f["x"] if vertical else f["y"]
    inward = {"north": -1, "south": 1, "east": -1, "west": 1}[f["wall"]]
    D, z0, z1 = f["depth"], f.get("z0", 0.0), f["z1"]

    def bx(a0, a1, n0, n1, h0, h1, m):  # along-wall a, normal offset n (0 = wall face, D = front)
        p0, p1 = face + inward * n0, face + inward * n1
        lo, hi = min(p0, p1), max(p0, p1)
        if vertical:
            mesh_obj("shelves", box(lo, a0, h0, hi, a1, h1), m, coll)
        else:
            mesh_obj("shelves", box(a0, lo, h0, a1, hi, h1), m, coll)

    st = 0.03
    bx(s0, s0 + st, 0.003, D, z0, z1, white)
    bx(s1 - st, s1, 0.003, D, z0, z1, white)
    bx(s0, s1, 0.003, D, z1 - st, z1, white)
    bx(s0 + st, s1 - st, 0.003, 0.012, z0, z1 - st, white)  # back
    cols = [(0.45, 0.2, 0.12), (0.18, 0.25, 0.35), (0.7, 0.66, 0.58), (0.3, 0.4, 0.3)]
    for k, zz in enumerate(f.get("shelves", [0.1, 0.5, 0.9, 1.3, 1.7])):
        bx(s0 + st, s1 - st, 0.012, D, zz, zz + 0.022, white)
        if D >= 0.12 and zz + 0.3 < z1:
            for i in range(int((s1 - s0 - 0.1) / 0.06)):
                if (i + k) % 4 == 3:
                    continue
                a = s0 + st + 0.02 + i * 0.06
                bx(a, a + 0.045, 0.02, D - 0.02, zz + 0.022, zz + 0.022 + 0.2 + 0.04 * ((i + k) % 3), mat(f"book{(i + k) % 4}", cols[(i + k) % 4], 0.6))


def fx_art(f, coll, white):
    """Framed art on a north-facing wall face, with an optional picture light (lit in accent scenes)."""
    Y, x0, x1, z0, z1 = f["y"], f["x0"], f["x1"], f["z0"], f["z1"]
    fr = mat("art_frame", (0.18, 0.12, 0.06), 0.4)
    mesh_obj("art_frame", box(x0, Y - 0.04, z0, x1, Y - 0.005, z1), fr, coll)
    canvas = bpy.data.materials.get(f"art_{f['id']}") or bpy.data.materials.new(f"art_{f['id']}")
    canvas.use_nodes = True
    nt = canvas.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.8
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = 6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.12, 0.2, 0.12, 1)  # landscape-ish greens and sky
    ramp.color_ramp.elements[1].color = (0.55, 0.62, 0.68, 1)
    e = ramp.color_ramp.elements.new(0.5)
    e.color = (0.45, 0.35, 0.18, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    m = 0.05
    mesh_obj("art_canvas", box(x0 + m, Y - 0.045, z0 + m, x1 - m, Y - 0.04, z1 - m), canvas, coll)
    if f.get("pictureLight"):
        brass = mat("picture_light_brass", (0.6, 0.45, 0.22), 0.3)
        cxm = (x0 + x1) / 2
        L = (x1 - x0) * 0.6
        mesh_obj("picture_light", box(cxm - L / 2, Y - 0.15, z1 + 0.06, cxm + L / 2, Y - 0.1, z1 + 0.09), brass, coll)
        mesh_obj("picture_light_arm", box(cxm - 0.01, Y - 0.12, z1 + 0.02, cxm + 0.01, Y - 0.01, z1 + 0.04), brass, coll)
        if ACCENTS_ON:
            for k in (-0.3, 0.0, 0.3):  # aim down and back onto the art
                _accent_light("picture_light", (cxm + k * L, Y - 0.13, z1 + 0.05), f["pictureLight"], 3, 5, rot=(math.radians(160), 0, 0), spot_deg=70, fixture=f["id"])


def build_on_wall(f, coll, white):
    """Fixture builders are written for the north wall (x0..x1 along it, y = wall line, front facing -y). For the
    other walls, build in that frame and rotate into place. East/west fixtures give y0..y1 along the wall and x."""
    wall = f["wall"]
    if wall == "north" or f["kind"] in ANY_WALL_FIXTURES:
        FIXTURE_BUILDERS[f["kind"]](f, coll, white)
        return
    g = dict(f)
    if wall == "south":
        g.update(x0=-f["x1"], x1=-f["x0"], y=-f["y"])
        ang = math.pi
    elif wall == "east":
        g.update(x0=-f["y1"], x1=-f["y0"], y=f["x"])
        ang = -math.pi / 2
    else:  # west
        g.update(x0=f["y0"], x1=f["y1"], y=-f["x"])
        ang = math.pi / 2
    before = set(bpy.data.objects)  # all objects: accent lights are linked to the scene collection, not coll
    FIXTURE_BUILDERS[f["kind"]](g, coll, white)
    rot = Matrix.Rotation(ang, 4, "Z")
    for ob in set(bpy.data.objects) - before:
        if ob.parent is None:  # matrix_basis, not matrix_world: a just-set location isn't in matrix_world yet
            ob.matrix_basis = rot @ ob.matrix_basis


FIXTURE_BUILDERS = {"fireplace": fx_fireplace, "panel": fx_panel, "niche": fx_niche, "shelves": fx_shelves, "art": fx_art}
ANY_WALL_FIXTURES = {"shelves"}


def add_landmarks(layout, catalog, coll):
    """Big, tall pieces (saunas, wardrobes, bookcases: at least 1.5 m tall and 0.5 m2) as plain wood boxes, so the
    shell views have something to line up against."""
    for it in layout["items"]:
        spec = {**catalog.get(it["type"], {}), **it}
        if spec.get("ceiling") is not None or spec.get("h", 0) < 1.5 or spec.get("w", 0) * spec.get("d", 0) < 0.5:
            continue
        r = math.radians(spec.get("rot", 0))
        w, d = spec["w"] / 2, spec["d"] / 2
        pts = [(spec["x"] + math.cos(r) * lx - math.sin(r) * ly, spec["y"] + math.sin(r) * lx + math.cos(r) * ly) for lx, ly in [(-w, -d), (w, -d), (w, d), (-w, d)]]
        z0 = spec.get("z", 0) or 0
        mesh_obj(f"landmark_{it['id']}", prism(pts, z0, z0 + spec["h"]), mat("landmark", (0.75, 0.52, 0.30), 0.7), coll)


VIEWS = {}  # filled by compare(): room.json "compareViews", else its "cameras", else four corner views
COMPARE_LENS = 16  # wide, so each view shows a lot of shell; a compareViews entry may set its own "lens"


def pick_views(room):
    """{name: {eye, target, lens, roll}} for the scan-vs-model comparison."""
    for key in ("compareViews", "cameras"):
        if room.get(key):
            return {k: {"eye": v["eye"], "target": v["target"], "lens": v.get("lens", COMPARE_LENS) if key == "compareViews" else COMPARE_LENS,
                        "roll": v.get("roll", 0.0)} for k, v in room[key].items()}
    xs, ys = [p[0] for p in room["outline"]], [p[1] for p in room["outline"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    zc = room["ceiling"]["top"] * 0.5
    corners = {"from_sw": (x0, y0), "from_se": (x1, y0), "from_ne": (x1, y1), "from_nw": (x0, y1)}
    out = {}
    for name, (cx, cy) in corners.items():
        ex, ey = cx + (0.6 if cx == x0 else -0.6), cy + (0.6 if cy == y0 else -0.6)
        out[name] = {"eye": (ex, ey, 1.65), "target": (x0 + x1 - cx, y0 + y1 - cy, zc), "lens": COMPARE_LENS}
    return out


def setup_render(engine):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 1100, 800
    sc.world = bpy.data.worlds.get("w") or bpy.data.worlds.new("w")
    if engine == "scan":
        sc.render.engine = "BLENDER_WORKBENCH"
        sc.display.shading.light = "FLAT"
        sc.display.shading.color_type = "TEXTURE"
        sc.world.color = (1, 1, 1)
    else:
        sc.render.engine = "CYCLES"
        sc.cycles.device = "CPU"
        sc.cycles.samples = 48
        sc.cycles.use_denoising = True
        sc.view_settings.view_transform = "AgX"
        sc.world.use_nodes = True
        bg = sc.world.node_tree.nodes["Background"]
        bg.inputs["Color"].default_value = (1, 1, 1, 1)
        bg.inputs["Strength"].default_value = 0.35
        # soft room light from the middle of the ceiling so soffit faces read
        light = bpy.data.lights.new("fill", "AREA")
        light.size, light.energy = 3.0, 120
        lo = bpy.data.objects.new("fill", light)
        lo.location = FILL_AT
        lo.visible_camera = False
        lo.rotation_euler = (math.pi, 0, 0)
        sc.collection.objects.link(lo)
    cam_d = bpy.data.cameras.new("cam")
    cam_d.lens = 16
    cam_d.clip_start = 0.05
    cam = bpy.data.objects.new("cam", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    return sc, cam


def render_views(prefix, offset, labels=()):
    """Render every view; returns {view: [(text, px, py)]} for labels in front of the camera."""
    from bpy_extras.object_utils import world_to_camera_view

    sc, cam = setup_render(prefix)
    placed = {}
    for name, view in VIEWS.items():
        roomframe.apply_camera(cam, view, tuple(offset))
        e = cam.location.copy()
        bpy.context.view_layer.update()
        sc.render.filepath = str(ROOM / f"renders/compare/{prefix}_{name}.png")
        bpy.ops.render.render(write_still=True)
        out = []
        dg = bpy.context.evaluated_depsgraph_get()
        for text, p in labels:
            p = Vector(p)
            v = world_to_camera_view(sc, cam, p)
            if not (v.z > 0.3 and 0.05 < v.x < 0.95 and 0.05 < v.y < 0.95):
                continue
            # skip surfaces hidden behind something
            d = p - e
            hit, loc, *_ = sc.ray_cast(dg, e, d.normalized(), distance=d.length)
            if hit and (loc - e).length < d.length - 0.08:
                continue
            x, y = v.x * sc.render.resolution_x, (1 - v.y) * sc.render.resolution_y
            if any(abs(x - ox) < 260 and abs(y - oy) < 34 for _, ox, oy in out):
                y += 36  # nudge down instead of overlapping
            out.append((text, x, y))
        placed[name] = out
    return placed


FILL_AT = (4.0, 2.2, 1.6)


def compare():
    global FILL_AT
    room = roomframe.normalize_room(json.loads((ROOM / "room.json").read_text()))
    OX, OY = room["scan"]["alignedOrigin"]  # room origin inside the aligned scan
    VIEWS.clear()
    VIEWS.update(pick_views(room))
    xs, ys = [p[0] for p in room["outline"]], [p[1] for p in room["outline"]]
    FILL_AT = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, room["ceiling"]["top"] - 0.6)
    catalog = roomframe.load_catalog(ROOM)  # shared, then the household's, then the room's own entries
    lp = ROOM / "layouts/as-scanned.json"  # optional: its big pieces become landmark boxes
    layout = json.loads(lp.read_text()) if lp.exists() else {"items": []}
    (ROOM / "renders/compare").mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(roomframe.require_file(ROOM / "scan/scan_aligned.glb", "aligned scan")))
    render_views("scan", Vector((OX, OY, 0)))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    coll = bpy.context.scene.collection
    labels = build_room(room, coll, color_ceiling=True)
    add_landmarks(layout, catalog, coll)
    placed = render_views("model", Vector((0, 0, 0)), labels)

    from PIL import Image, ImageDraw

    font, big = roomframe.font(22), roomframe.font(30)
    for name in VIEWS:
        a = Image.open(ROOM / f"renders/compare/scan_{name}.png").convert("RGB")
        b = Image.open(ROOM / f"renders/compare/model_{name}.png").convert("RGB")
        db = ImageDraw.Draw(b)
        for text, x, y in placed[name]:
            w = db.textlength(text, font=font)
            db.rounded_rectangle([x - w / 2 - 8, y - 16, x + w / 2 + 8, y + 16], 6, fill=(30, 30, 30))
            db.text((x - w / 2, y - 12), text, fill="white", font=font)
        out = Image.new("RGB", (a.width + b.width + 20, a.height + 120), "white")
        out.paste(a, (0, 60))
        out.paste(b, (a.width + 20, 60))
        d = ImageDraw.Draw(out)
        d.text((10, 14), "REAL ROOM (scan)", fill="black", font=big)
        d.text((a.width + 30, 14), "MY MODEL - ceiling colored by height", fill="black", font=big)
        lx = a.width + 30
        heights = sorted({round(d["z"], 2) for d in room["ceiling"]["downstands"] if not d.get("slope")} | {round(room["ceiling"]["top"], 2)})
        for k, z in enumerate(heights[:6]):
            col = tuple(int(255 * v) for v in height_color(z))
            d.rectangle([lx + k * 170, a.height + 75, lx + k * 170 + 34, a.height + 105], fill=col)
            d.text((lx + k * 170 + 42, a.height + 77), f"{z:.2f} m", fill="black", font=font)
        out.save(ROOM / f"renders/compare/{name}.png")


if __name__ == "__main__":
    if "compare" in sys.argv:
        compare()
