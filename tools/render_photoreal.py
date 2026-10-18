# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1", "pillow-heif"]
# ///
"""Photoreal Cycles renders of a layout.

Usage, from inside rooms/<room>/:
  uv run ../../tools/render_photoreal.py <layout> [--lighting day|night|evening|standard|<scene>] (default standard) [--views v1,v2]
      [--samples 48] [--res 1400x875] [--tag folder] [--exposure stops] [--white-balance K] [--meter-layout L]

Writes renders/photoreal/<tag or layout>/<view>.png (render_batch.py and render_modal.py name folders
<tag>, or <tag or layout>-<lighting> when several lightings are rendered). Geometry comes from room.json
(tools/blender_scene.py) and the layout; furniture from the catalogs via tools/blender_models.py. Lighting is a
base preset or a room.json "scenes" entry (see resolve_scene). Quick tests: --samples 16 --res 700x440.

Lights are physical (tools/photometry.py): fixtures in lumens and kelvin with their dimmer curve, daylight from a
sky model, and a camera that exposes and white-balances like a phone (or like the photo a camera was matched to).
Lights without data use stated defaults, printed as ASSUMED lines; fit them to photos with light_match.py.
Other tools render exactly the same scene with build() + aim() + expose() (e.g. color_match.py, light_match.py).
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

from mathutils import Vector

import blender_models
import blender_scene
import photometry as ph
import roomframe

REPO = Path(__file__).resolve().parent.parent  # repo root: shared catalog, materials, models
ROOM = Path(os.environ.get("ROOM", ".")).resolve()  # room folder (run from inside rooms/<room>/ or set ROOM=)


# Named render cameras live in the room's room.json ("cameras": {name: {eye, target, lens, roll?}}); "roll" (degrees
# about the view axis) comes e.g. from a camera recovered from a real photo by tools/photo_match.py.
_ROOM_JSON = json.loads((ROOM / "room.json").read_text()) if (ROOM / "room.json").exists() else {}
VIEWS = {k: roomframe.camera(v) for k, v in _ROOM_JSON.get("cameras", {}).items()}  # name -> (eye, target, lens, roll)


def node_mat(name):
    m = bpy.data.materials.get(name)
    return m, m.node_tree.nodes["Principled BSDF"], m.node_tree


# Shell materials come from room.json "materials"; these neutral defaults (white paint, mid-tone wood) fill the gaps.
MATERIAL_DEFAULTS = {
    "wall": {"color": [0.8, 0.79, 0.76], "roughness": 0.6},
    "ceiling": {"color": [0.8, 0.79, 0.76], "roughness": 0.9},
    "trim": {"color": [0.86, 0.86, 0.84], "roughness": 0.35},  # doors, casings
    "baseboard": {"color": [0.85, 0.85, 0.83], "roughness": 0.35},
    "floor": {"texture": "laminate_floor_02", "scale": 0.62, "hue": 0.5, "saturation": 1.0, "value": 1.0, "coat": 0.15},
}


def srgb_to_linear(hexstr):
    h = hexstr.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


def room_materials(room):
    """Merge room.json "materials" over the defaults. Any entry may give "hex" (sRGB, e.g. sampled from a photo or a
    paint chip) instead of a linear "color"; for the floor, "hex" is the target average colour of its texture, or the
    floor's colour when "texture" is "none" (tile, stone, carpet)."""
    m = {k: dict(v) for k, v in MATERIAL_DEFAULTS.items()}
    for k, v in room.get("materials", {}).items():
        m.setdefault(k, {}).update(v)
    for k, v in m.items():
        if "hex" in v and k != "floor":
            v["color"] = srgb_to_linear(v["hex"])
    return m


def upgrade_shell_materials(room):
    M = room_materials(room)
    # floor: a Poly Haven texture (CC0), mapped in meters via object coordinates and tinted to the room's floor, or a plain colour
    fl = M["floor"]
    _, b, nt = node_mat("floor")
    if fl.get("texture") in (None, "", "none"):  # a plain floor (tile, stone, concrete, carpet, tatami): a colour, no grain
        own = (room.get("materials") or {}).get("floor") or {}  # not the wood defaults' clear coat
        rgb = srgb_to_linear(own["hex"]) if "hex" in own else own.get("color") or srgb_to_linear("#9a8f80")
        b.inputs["Base Color"].default_value = (*rgb, 1)
        b.inputs["Roughness"].default_value = own.get("roughness", 0.5)
        b.inputs["Coat Weight"].default_value = own.get("coat", 0.0)
    else:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (fl["scale"], fl["scale"], 1)
        mp.inputs["Rotation"].default_value = (0, 0, math.radians(fl.get("rotationDeg", 0)))
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        tex = {}
        t = fl["texture"]
        if not (REPO / "shared/pbr" / f"{t}_diff.jpg").exists():
            sys.exit(f"floor texture {t!r} not found: expected shared/pbr/{t}_diff.jpg (room.json materials.floor.texture)")
        for key, fn, cs in [("diff", f"{t}_diff.jpg", "sRGB"), ("rough", f"{t}_rough.jpg", "Non-Color"), ("nor", f"{t}_nor_gl.jpg", "Non-Color")]:
            if not (REPO / "shared/pbr" / fn).exists():
                continue
            roomframe.require_file(REPO / "shared/pbr" / fn, "floor texture")
            n = nt.nodes.new("ShaderNodeTexImage")
            n.image = bpy.data.images.load(str(REPO / "shared/pbr" / fn))
            n.image.colorspace_settings.name = cs
            nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
            tex[key] = n
        if "hex" in fl:
            # tint the texture so its average matches the target colour (keeps the grain, fixes hue and brightness)
            import numpy as np

            img = tex["diff"].image
            px = np.empty(len(img.pixels), dtype=np.float32)  # linear RGBA floats (Blender converts sRGB images on load)
            img.pixels.foreach_get(px)
            px = px.reshape(-1, 4)
            step = max(1, len(px) // 20000)
            mean = px[::step, :3].astype(np.float64).mean(axis=0).tolist()
            gray = nt.nodes.new("ShaderNodeRGBToBW")
            nt.links.new(tex["diff"].outputs["Color"], gray.inputs["Color"])
            tgt = srgb_to_linear(fl["hex"])
            lum = 0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]
            mul = nt.nodes.new("ShaderNodeMix")
            mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
            mul.inputs["Factor"].default_value = 1.0
            nt.links.new(gray.outputs["Val"], mul.inputs[6])
            mul.inputs[7].default_value = (*[t / max(lum, 1e-4) for t in tgt], 1)
            nt.links.new(mul.outputs[2], b.inputs["Base Color"])
        else:
            hsv = nt.nodes.new("ShaderNodeHueSaturation")
            hsv.inputs["Hue"].default_value = fl["hue"]
            hsv.inputs["Saturation"].default_value = fl["saturation"]
            hsv.inputs["Value"].default_value = fl["value"]
            nt.links.new(tex["diff"].outputs["Color"], hsv.inputs["Color"])
            nt.links.new(hsv.outputs["Color"], b.inputs["Base Color"])
        if "rough" in tex:
            nt.links.new(tex["rough"].outputs["Color"], b.inputs["Roughness"])
        else:
            b.inputs["Roughness"].default_value = fl.get("roughness", 0.45)
        if "nor" in tex:
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.inputs["Strength"].default_value = 0.6
            nt.links.new(tex["nor"].outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
        b.inputs["Coat Weight"].default_value = fl["coat"]

    # painted walls with a faint roller texture, or wallpaper (+ painted wainscot below it)
    _, b, nt = node_mat("wall")
    b.inputs["Base Color"].default_value = (*M["wall"]["color"], 1)
    b.inputs["Roughness"].default_value = M["wall"]["roughness"]
    wp = M["wall"].get("texture")
    if wp:  # e.g. from tools/wallpaper_from_scan.py; box-projected in world space so every wall gets it at true scale
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
        wh = M["wall"].get("wainscot", {}).get("height", 0.0)
        top = room["ceiling"]["top"]
        width = M["wall"].get("width", 1.0)
        img = nt.nodes.new("ShaderNodeTexImage")
        img.image = bpy.data.images.load(str((ROOM / wp).resolve()))
        iw, ih = img.image.size
        tile_h = width * ih / iw if iw else top - wh  # true scale: the tile is `width` wide and keeps its aspect
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1 / width, 1 / width, 1 / tile_h)
        mp.inputs["Location"].default_value = (0, 0, -wh / tile_h)
        nt.links.new(geo.outputs["Position"], mp.inputs["Vector"])
        img.projection, img.projection_blend = "BOX", 0.0
        nt.links.new(mp.outputs["Vector"], img.inputs["Vector"])
        col = img.outputs["Color"]
        if wh:
            gt = nt.nodes.new("ShaderNodeMath")
            gt.operation, gt.inputs[1].default_value = "GREATER_THAN", wh
            nt.links.new(sep.outputs["Z"], gt.inputs[0])
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            nt.links.new(gt.outputs[0], mix.inputs["Factor"])
            mix.inputs[6].default_value = (*srgb_to_linear(M["wall"]["wainscot"].get("hex", "#F1EFEA")), 1)
            nt.links.new(col, mix.inputs[7])
            col = mix.outputs[2]
        nt.links.new(col, b.inputs["Base Color"])
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 180
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.03
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])

    for name in [m.name for m in bpy.data.materials if m.name == "ceiling" or m.name.startswith("ceil_")]:
        _, b, _ = node_mat(name)
        b.inputs["Base Color"].default_value = (*M["ceiling"]["color"], 1)
        b.inputs["Roughness"].default_value = M["ceiling"]["roughness"]
    _, b, _ = node_mat("door")
    b.inputs["Base Color"].default_value = (*M["trim"]["color"], 1)
    b.inputs["Roughness"].default_value = M["trim"]["roughness"]
    m, b, _ = node_mat("glass")  # clear float glass: ~90% through, a hint of green
    b.inputs["Base Color"].default_value = (0.9, 0.92, 0.91, 1)
    b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.05
    blender_models.thin_glass(m)  # daylight comes straight through (shadow rays), not as caustics
    if bpy.data.materials.get("tv"):
        _, b, _ = node_mat("tv")
        b.inputs["Base Color"].default_value = (0.004, 0.004, 0.005, 1)
        b.inputs["Roughness"].default_value = 0.06
        b.inputs["Coat Weight"].default_value = 1.0


def add_wall_band(room, coll, name, z0, z1, depth, material, skip_windows=False):
    """A strip of trim along every wall, broken at doors (and at windows it would cross, if asked)."""
    out = room["outline"]
    for i in range(len(out)):
        a, b = Vector((*out[i], 0)), Vector((*out[(i + 1) % len(out)], 0))
        u, L = (b - a).normalized(), (b - a).length
        nrm = Vector((-u.y, u.x, 0))
        cuts = []
        openings = [(d["a"], d["b"]) for d in room["doors"]]
        if skip_windows:
            openings += [(w["a"], w["b"]) for w in room["windows"] if w["z0"] < z1 and w["z1"] > z0]
        for pa, pb in openings:
            ta, tb = (Vector((*pa, 0)) - a).dot(u), (Vector((*pb, 0)) - a).dot(u)
            if abs((Vector((*pa, 0)) - a).dot(nrm)) < 0.03 and min(ta, tb) > -0.03 and max(ta, tb) < L + 0.03:
                pad = 0.075 if (room.get("casings") and z1 > 0.2) else 0.0  # stop at the casing
                cuts.append((min(ta, tb) - pad, max(ta, tb) + pad))
        spans, t = [], 0.0
        for c0, c1 in sorted(cuts):
            spans.append((t, c0))
            t = c1
        spans.append((t, L))
        for t0, t1 in spans:
            if t1 - t0 < 0.02:
                continue
            p0, p1 = a + u * t0, a + u * t1
            q0, q1 = p0 + nrm * depth, p1 + nrm * depth
            bm = blender_scene.prism([(p0.x, p0.y), (p1.x, p1.y), (q1.x, q1.y), (q0.x, q0.y)], z0, z1)
            blender_scene.mesh_obj(name, bm, material, coll)


def add_baseboards(room, coll):
    """White baseboards (plus chair rail and crown if room.json "materials" asks for them)."""
    M = room_materials(room)
    trim = blender_models.pbr("baseboard", tuple(M["baseboard"]["color"]), M["baseboard"]["roughness"])
    add_wall_band(room, coll, "baseboard", 0, 0.095, 0.014, trim)
    if "chairRail" in M:
        z = M["chairRail"]["z"]
        add_wall_band(room, coll, "chair_rail", z - 0.035, z + 0.035, 0.022, trim, skip_windows=True)
    if "crown" in M:
        top = room["ceiling"]["top"]
        add_wall_band(room, coll, "crown", top - M["crown"].get("height", 0.11), top - 0.002, M["crown"].get("depth", 0.05), trim)


def ceiling_z_at(room, x, y):
    """Ceiling height at (x, y), sloped downstands included (roomframe.ceiling_z)."""
    return roomframe.ceiling_z(room, x, y)


def area(name, size, size_y, energy, color, loc, rot, coll):
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape, ld.size, ld.size_y, ld.energy, ld.color = "RECTANGLE", size, size_y, energy, color
    lo = bpy.data.objects.new(name, ld)
    lo.location, lo.rotation_euler = loc, rot
    coll.objects.link(lo)
    return lo


DAYLIT_DOORS = ("glass", "sliding")  # door styles that let daylight in (like windows)
BASES = ("day", "night", "evening", "standard")  # day: daylight only; night: no daylight, all lights on; evening: night, downlights off; standard: daylight + all lights
NIGHT = ("night", "evening")  # no daylight, windows dark
LENS_R = 0.06  # can lens radius, m


def can_lights(room, coll, setting):
    """Recessed downlights from room.json `lights`: positions in `recessed` ([x, y], or {x, y, lumens, kelvin, beam} for
    one that differs), the fixture in `cans` (or `downlights`) {lumens, kelvin, beam (full cone angle), dimCurve, dimToWarm}; missing
    values are photometry.DEFAULT_CAN (listed as ASSUMED). `setting` is the dimmer setting (0 = off)."""
    lights = room.get("lights", {})
    data = dict(lights.get("cans", {}))
    if "kelvin" not in data and "dimToWarm" not in data and lights.get("kelvin"):
        data["kelvin"] = lights["kelvin"]  # the room's usual bulb colour
    base = {**ph.DEFAULT_CAN, **data}
    recessed = lights.get("recessed", [])
    missing = [k for k in ("lumens", "kelvin") if k not in data and not (k == "kelvin" and "dimToWarm" in data)]
    if recessed and missing and setting > 0:
        blender_models.ASSUMED.append(("downlights", "cans", f"{base['lumens']:.0f} lm" if "lumens" in missing else None,
                                       f"{base['kelvin']:.0f} K" if "kelvin" in missing else None))
    trim = blender_models.pbr("can_trim", (0.9, 0.9, 0.9), 0.3)
    for c in recessed:
        spec = {**base, **c} if isinstance(c, dict) else base
        x, y = (c["x"], c["y"]) if isinstance(c, dict) else c
        z = ceiling_z_at(room, x, y)
        b = blender_models.Builder("can", coll)
        b.cyl(0.085, 0.006, x, y, z - 0.003, trim, bevel=0)
        out = ph.dimmer_output(setting, spec.get("dimCurve", "square"))
        if out <= 0:  # cans off: trims only, no glowing lens
            continue
        k = ph.dim_to_warm(setting, *spec["dimToWarm"]) if spec.get("dimToWarm") else spec["kelvin"]
        rgb, lm = ph.kelvin_rgb(k), spec["lumens"] * out
        group = blender_models.light_group("cans", {"kind": "cans", "lumens": spec["lumens"], "kelvin": round(k), "dim": setting,
                                                    "dimCurve": spec.get("dimCurve", "square"), "rgb": rgb, "flux": lm, "label": "downlights", "assumed": "lumens" not in data and not (isinstance(c, dict) and "lumens" in c)})
        # the lens as seen (Lambertian: luminance = lumens / (pi x area x pi)); the spot below carries the light
        lens = b.cyl(LENS_R, 0.002, x, y, z - 0.0065, blender_models.pbr(f"can_lens_{k:.0f}_{out:.4f}", (1, 1, 1), 0.5,
                     emission=(rgb, ph.emission_strength(lm / (math.pi * LENS_R ** 2 * math.pi)))), bevel=0)
        lens.visible_diffuse = lens.visible_shadow = False
        lens.lightgroup = group
        ld = bpy.data.lights.new("can", "SPOT")
        ld.energy, ld.spot_size, ld.spot_blend = ph.spot_watts(lm, spec["beam"]), math.radians(spec["beam"]), 0.6
        ld.color, ld.shadow_soft_size = rgb, 0.05
        lo = bpy.data.objects.new("can", ld)
        lo.location = (x, y, z - 0.02)
        lo.lightgroup = group
        coll.objects.link(lo)


def openings(room):
    """Windows and glazed doors as (centre x, y, z, width, height, inward normal (nx, ny))."""
    outline = room["outline"]
    out = []
    ops = [(w["a"], w["b"], w["z0"], w["z1"]) for w in room["windows"]]
    ops += [(d["a"], d["b"], 0.0, d["height"]) for d in room["doors"] if d.get("style") in DAYLIT_DOORS]
    for (ax, ay), (bx, by), z0, z1 in ops:
        ux, uy = bx - ax, by - ay
        ww = math.hypot(ux, uy)
        ux, uy = ux / ww, uy / ww
        cx, cy = (ax + bx) / 2, (ay + by) / 2
        nx, ny = -uy, ux  # a normal; flip so it points into the room
        if not roomframe.point_in_poly((cx + nx * 0.05, cy + ny * 0.05), outline):
            nx, ny = -nx, -ny
        out.append((cx, cy, (z0 + z1) / 2, ww, z1 - z0, (nx, ny)))
    return out


def sky_state(room, scene):
    """The daylight for a scene: sky kind, horizontal sky illuminance (lux), direct sun (lux, altitude, azimuth)."""
    dl, site = room.get("daylight", {}), room.get("site", {})
    t = scene.get("time") or dl.get("time")
    alt = az = None
    if site.get("latitude") is not None and t:
        import datetime

        doy = datetime.date(2025, int(t.get("month", 6)), int(t.get("day", 21))).timetuple().tm_yday
        alt, az = ph.solar_position(site["latitude"], doy, float(t.get("hour", 12)))
    sky = scene.get("sky") or dl.get("sky", "overcast")
    if sky == "clear" and alt is None:
        print("warning: a clear sky needs room.json site.latitude and a time (daylight.time or the scene's time); using overcast")
        sky = "overcast"
    direct = 0.0
    if sky == "clear":
        direct, diffuse = ph.clear_sky(alt)
    else:
        diffuse = ph.overcast_sky(alt)
    if "illuminance" in dl:
        diffuse = dl["illuminance"]
    elif alt is None:
        blender_models.ASSUMED.append(("daylight", "daylight", f"overcast sky, {diffuse:.0f} lux", None))
    return {"sky": sky, "diffuse": diffuse, "direct": direct, "alt": alt, "az": az, "scale": dl.get("scale", 1.0)}


def add_daylight(room, coll, scene, on):
    """Daylight as the real light source: a sky dome (CIE overcast distribution, scaled to the sky's horizontal
    illuminance; ground below the horizon) and, for a clear sky, the sun (direct normal illuminance from the IES
    clear-sky model, direction from room.json `site` and the time). Cycles light portals in every window and glazed
    door guide the sampling. `daylight.scale` calibrates what reaches the windows (trees, porches, window wells:
    fit it with light_match.py). Night (on = False): no sky, windows dark."""
    sc = bpy.context.scene
    sc.world = bpy.data.worlds.new("world")
    sc.world.use_nodes = True
    nt = sc.world.node_tree
    bg = nt.nodes["Background"]
    if not on:
        bg.inputs["Strength"].default_value = 0.0
        return None
    st = sky_state(room, scene)
    k_sky = 12000 if st["sky"] == "clear" else 6500
    e_ground = st["diffuse"] + st["direct"] * math.sin(math.radians(st["alt"] or 0))
    lz = ph.overcast_zenith(st["diffuse"]) * st["scale"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])

    def math_node(op, a, b=None):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    up = math_node("MAXIMUM", sep.outputs["Z"], 0.0)
    strength = math_node("MULTIPLY", math_node("ADD", math_node("MULTIPLY", up, 2.0), 1.0), ph.emission_strength(lz / 3))
    nt.links.new(strength, bg.inputs["Strength"])
    bg.inputs["Color"].default_value = (*ph.kelvin_rgb(k_sky), 1)
    ground = nt.nodes.new("ShaderNodeBackground")
    ground.inputs["Color"].default_value = (1, 1, 1, 1)
    ground.inputs["Strength"].default_value = ph.emission_strength(ph.GROUND_ALBEDO * e_ground / math.pi * st["scale"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(math_node("GREATER_THAN", sep.outputs["Z"], 0.0), mix.inputs["Fac"])
    nt.links.new(ground.outputs[0], mix.inputs[1])
    nt.links.new(bg.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], nt.nodes["World Output"].inputs["Surface"])
    sc.world.lightgroup = "daylight"
    sun_vec = None
    if st["direct"] > 0:
        dx, dy = ph.plan_direction(st["az"], room.get("site", {}).get("northDeg", 0))
        ca = math.cos(math.radians(st["alt"]))
        sun_vec = Vector((ca * dx, ca * dy, math.sin(math.radians(st["alt"]))))
        ld = bpy.data.lights.new("sun", "SUN")
        ld.energy, ld.angle = ph.sun_strength(st["direct"]) * st["scale"], math.radians(0.53)
        ld.color = ph.kelvin_rgb(ph.sun_kelvin(st["alt"]))
        lo = bpy.data.objects.new("sun", ld)
        lo.rotation_euler = sun_vec.to_track_quat("Z", "Y").to_euler()  # a sun shines along its -Z
        lo.lightgroup = "daylight"
        coll.objects.link(lo)
    # portals just outside each glazed opening (area lights shine along local -Z; (0, -90 deg, phi) points them into
    # the room, local X vertical, local Y along the wall); and the light that comes in, for the white balance
    T = room.get("wallThickness", 0.15)
    flux = 0.0
    for cx, cy, wz, ww, wh, (nx, ny) in openings(room):
        ld = bpy.data.lights.new("portal", "AREA")
        ld.shape, ld.size, ld.size_y = "RECTANGLE", wh, ww
        ld.cycles.is_portal = True
        lo = bpy.data.objects.new("portal", ld)
        lo.location = (cx - nx * (T + 0.02), cy - ny * (T + 0.02), wz)
        lo.rotation_euler = (0, math.radians(-90), math.atan2(ny, nx))
        coll.objects.link(lo)
        sun_in = 0.0
        if sun_vec is not None:  # sun on the glass: the sun direction against the outward normal
            sun_in = max(0.0, -(sun_vec.x * nx + sun_vec.y * ny)) * st["direct"]
        flux += ww * wh * (0.4 * st["diffuse"] + 0.5 * ph.GROUND_ALBEDO * e_ground + sun_in) * st["scale"]  # vertical sky + ground share
    rgb = tuple(c for c in ph.kelvin_rgb(k_sky if st["direct"] == 0 else ph.sun_kelvin(st["alt"])))
    blender_models.light_group("daylight", {"kind": "daylight", "lumens": None, "kelvin": k_sky, "dim": 1.0, "rgb": rgb, "flux": flux,
                                            "label": f"daylight ({st['sky']}, {st['diffuse']:.0f} lux" + (f", sun {st['direct']:.0f} lux" if st["direct"] else "") + ")"})
    return st


def resolve_scene(room, lighting):
    """A --lighting name is either a base preset or a room.json "scenes" entry:
    {"base": "night", "downlights": 0.4, "ceiling": 1.0, "lamps": true, "accents": true, "fire": true, "lampsOff": [ids],
     "lampDim": {id: 0-1}, "lampKelvin": {id: K}, "screens": [fixture ids], "exposure": "auto" | "photo" | stops,
     "exposureBias": stops, "whiteBalance": "auto" | K, "sky": "overcast" | "clear", "time": {month, day, hour}}.
    Base presets: "day" (daylight only, lights off), "night" (no daylight, every light on), "evening" (no daylight,
    downlights off, lamps and accents on: one common setup), "standard" (daylight, downlights and lamps on). `cans`
    (also written `downlights`; recessed downlights), `ceiling` (items with "layer": "ceiling", defaulting to the
    downlights) and `lampDim` are dimmer settings (0-1, as on the dimmer; the
    fixture's dimCurve turns them into light output); `lampKelvin` sets a tunable bulb's colour."""
    known = set(BASES)
    scenes = room.get("scenes", {})
    if lighting not in scenes and lighting not in known:
        sys.exit(f"unknown --lighting {lighting!r}: room.json scenes: {', '.join(scenes) or '(none)'}; presets: {', '.join(sorted(known))}")
    sc = dict(scenes.get(lighting, {}))
    base = sc.get("base", lighting)
    if base not in known:
        sys.exit(f"scene {lighting!r} has base {base!r}; use one of {', '.join(sorted(known))}")
    sc.setdefault("cans", 1.0 if base in ("standard", "night") else 0.0)
    sc.setdefault("ceiling", sc["cans"])  # ceiling-layer items follow the downlights unless the scene sets them
    sc.setdefault("lamps", base != "day")
    sc.setdefault("accents", base in NIGHT)
    sc.setdefault("fire", False)
    sc.setdefault("screens", [])
    sc["base"] = base
    sc["name"] = lighting
    return sc


def enable_gpu():
    """Turn on a GPU for Cycles (OptiX or CUDA on NVIDIA, Metal on Apple silicon, HIP on AMD, oneAPI on Intel);
    returns "GPU", or "CPU" if none is found."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA", "METAL", "HIP", "ONEAPI"):
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue
        prefs.get_devices()
        if any(d.type == backend for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == backend
            print(f"Cycles device: GPU ({backend})")
            return "GPU"
    print("Cycles device: CPU (no GPU found)")
    return "CPU"


SCENE = {}  # the scene of the last build()
ROOM_WB = [ph.D65_K, ""]  # white balance the lights call for, and why (set by build)
METERED = {}  # view -> (exposure, log-average luminance) from auto metering; kept across builds (--meter-layout)
OVERRIDE = {"exposure": None, "whiteBalance": None}  # --exposure / --white-balance


def report_assumed():
    """One line per light that used a default instead of data, so the agent asks the person or calibrates."""
    seen = {}
    for label, _id, lm, k in blender_models.ASSUMED:
        key = (label, lm, k)
        seen[key] = seen.get(key, 0) + 1
    for (label, lm, k), n in seen.items():
        vals = ", ".join(v for v in (lm, k) if v)
        print(f"ASSUMED: {label}{f' x{n}' if n > 1 else ''}: {vals} (not in the data: ask the person, or fit it with light_match.py)")


def scene_white_balance():
    """White balance a camera would pick for the lights that are on: their flux-weighted colour, part of the way
    from D65 (photometry.adapted_white_balance)."""
    rgb, total = [0.0, 0.0, 0.0], 0.0
    for g in blender_models.LIGHT_GROUPS.values():
        f = g.get("flux") or 0.0
        if f > 0 and g.get("rgb"):
            rgb = [a + f * c for a, c in zip(rgb, g["rgb"])]
            total += f
    if not total:
        return ph.D65_K, "no lights"
    k = ph.rgb_kelvin(rgb)
    return ph.adapted_white_balance(k), f"lights {k:.0f} K"


def build(layout_slug, samples, res, lighting="standard"):
    """Build the room, the layout's items and the scene's lights, and set up Cycles and colour management; returns the
    camera (aim it with aim(), then expose() sets the exposure and white balance for that view). Other tools reuse
    this to render exactly what render() renders (e.g. color_match.py, light_match.py)."""
    room = roomframe.normalize_room(json.loads((ROOM / "room.json").read_text()))
    scene = resolve_scene(room, lighting)
    SCENE.clear()
    SCENE.update(scene)
    lp = ROOM / f"layouts/{layout_slug}.json"
    if not lp.exists():
        sys.exit(f"no layout {lp.relative_to(ROOM) if lp.is_relative_to(ROOM) else lp}; layouts: {', '.join(sorted(p.stem for p in (ROOM / 'layouts').glob('*.json')))}")
    blender_scene.ACCENTS_ON = scene["accents"]
    blender_scene.FIRE_ON = scene["fire"]
    blender_scene.SCREENS_ON = set(scene["screens"])
    blender_models.ASSUMED.clear()
    blender_models.LIGHT_GROUPS.clear()
    catalog = blender_models.load_catalog(ROOM)
    layout = json.loads(lp.read_text())
    for it in layout["items"]:  # scene can turn individual lamps off, dim them or set a tunable bulb's colour
        if it["id"] in scene.get("lampsOff", []):
            it["off"] = True
        if it["id"] in scene.get("lampDim", {}):
            it["dim"] = scene["lampDim"][it["id"]]
        if it["id"] in scene.get("lampKelvin", {}):
            it["kelvinSet"] = scene["lampKelvin"][it["id"]]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    coll = bpy.context.scene.collection
    blender_scene.build_room(room, coll)
    upgrade_shell_materials(room)
    add_baseboards(room, coll)
    blender_models.LAMPS_ON = scene["lamps"]  # plug-in lamps (off in daylight scenes)
    blender_models.CEILING = scene["ceiling"]
    blender_models.ROOM_KELVIN = (room.get("lights") or {}).get("kelvin")
    blender_models.place_items(layout, catalog, coll, room)
    for g in blender_models.LIGHT_GROUPS.values():  # lamps: light output for the white balance
        if g["kind"] in ("item", "interior") and g.get("lumens"):
            g["flux"] = g["lumens"] * ph.dimmer_output(g.get("dim", 1.0), g.get("dimCurve", "square")) * g.get("count", 1)
        elif g["kind"] == "fire":
            g["flux"] = g["lumens"]
    can_lights(room, coll, scene["cans"])
    add_daylight(room, coll, scene, scene["base"] not in NIGHT)
    ROOM_WB[:] = scene_white_balance()
    report_assumed()

    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = enable_gpu() if os.environ.get("CYCLES_DEVICE", "CPU").upper() == "GPU" else "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 12
    sc.cycles.diffuse_bounces = 6
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast" if scene["base"] in NIGHT else "AgX - Base Contrast"
    sc.view_settings.use_white_balance = True
    sc.view_settings.white_balance_tint = 0.0  # our lights sit on the Planckian locus; Blender's default tint (10) turns warm light pink
    cam_d = bpy.data.cameras.new("cam")
    cam_d.clip_start = 0.05
    cam = bpy.data.objects.new("cam", cam_d)
    coll.objects.link(cam)
    sc.camera = cam
    return cam


def meter(view):
    """Auto exposure like a phone: render the view small and fast, take the log-average luminance and expose for it
    (photometry.auto_exposure keeps dim scenes darker than bright ones). Returns (exposure, cd/m²)."""
    import tempfile

    import numpy as np

    sc = bpy.context.scene
    r, im = sc.render, sc.render.image_settings
    saved = (r.resolution_x, r.resolution_y, r.resolution_percentage, sc.cycles.samples, r.filepath, im.file_format, im.color_depth, im.color_mode)
    r.resolution_x, r.resolution_y, r.resolution_percentage = 160, max(1, round(160 * saved[1] / saved[0])), 100
    sc.cycles.samples = 16
    im.file_format, im.color_depth, im.color_mode = "OPEN_EXR", "32", "RGB"
    path = str(Path(tempfile.mkdtemp(prefix="meter_")) / f"{view}.exr")
    r.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    px = px.reshape(-1, 4)[:, :3].astype(np.float64)
    lum = (px @ np.array([0.2126, 0.7152, 0.0722])) * ph.LM_PER_W
    log_avg = float(np.exp(np.mean(np.log(lum + 1e-3))))
    (r.resolution_x, r.resolution_y, r.resolution_percentage, sc.cycles.samples, r.filepath, im.file_format, im.color_depth, im.color_mode) = saved
    return ph.auto_exposure(log_avg), log_avg


def expose(cam, view, quiet=False):
    """Exposure and white balance for a view (aim the camera first), from the scene:
    exposure: a number (stops; lock it to compare levels of one light), "photo" (the camera's photo: EXIF shutter,
    aperture and ISO, like the phone that took it; else auto), or "auto" (default: metered like a phone), plus
    `exposureBias` (stops, like a phone's exposure compensation). whiteBalance: kelvin, or "auto" (default: the
    lights' colour, partly neutralised). --exposure / --white-balance override both. Returns (exposure, kelvin, how)."""
    sc = bpy.context.scene
    spec = OVERRIDE["exposure"] if OVERRIDE["exposure"] is not None else SCENE.get("exposure", "auto")
    how = None
    e = None
    if isinstance(spec, (int, float)):
        e, how = float(spec), "fixed"
    elif spec == "photo":
        photo = _ROOM_JSON.get("cameras", {}).get(view, {}).get("photo")
        ev = roomframe.photo_ev100(ROOM / photo) if photo and (ROOM / photo).exists() else None
        if ev is not None:
            e, how = ph.exposure_for_ev(ev), f"photo EV100 {ev:.1f}"
        elif not quiet:
            print(f"{view}: no photo with exposure EXIF; metering instead")
    elif spec != "auto":
        sys.exit(f"exposure {spec!r}: use a number (stops), \"auto\" or \"photo\"")
    if e is None:
        if view not in METERED:
            METERED[view] = meter(view)
        e, lum = METERED[view]
        how = f"auto, {lum:.2g} cd/m2"
    e += SCENE.get("exposureBias", 0.0)
    wb_spec = OVERRIDE["whiteBalance"] if OVERRIDE["whiteBalance"] is not None else SCENE.get("whiteBalance", "auto")
    if isinstance(wb_spec, (int, float)):
        wb, wb_how = float(wb_spec), "fixed"
    elif wb_spec == "auto":
        wb, wb_how = ROOM_WB[0], f"auto, {ROOM_WB[1]}"
    else:
        sys.exit(f"whiteBalance {wb_spec!r}: use a number (K) or \"auto\"")
    sc.view_settings.exposure, sc.view_settings.white_balance_temperature = e, wb
    if not quiet:
        print(f"{view}: exposure {e:.2f} ({how}{', bias ' + str(SCENE['exposureBias']) if SCENE.get('exposureBias') else ''}), white balance {wb:.0f} K ({wb_how})")
    return e, wb, how


def aim(cam, name):
    """Point the camera at a room.json camera (eye, target, lens and roll; roomframe.apply_camera)."""
    roomframe.check_views(_ROOM_JSON, [name])
    roomframe.apply_camera(cam, _ROOM_JSON["cameras"][name])


def render(layout_slug, samples, views, res, lighting="standard", tag=None, meter_layout=None):
    """Render views of a layout. meter_layout: meter auto exposure on another layout (e.g. today's), so a proposal and
    today get the same exposure and the difference between them shows."""
    roomframe.check_views(_ROOM_JSON, views)
    METERED.clear()
    if meter_layout and meter_layout != layout_slug:
        cam = build(meter_layout, samples, res, lighting)
        for name in views:
            aim(cam, name)
            expose(cam, name, quiet=True)
    cam = build(layout_slug, samples, res, lighting)
    sc = bpy.context.scene
    out_dir = ROOM / f"renders/photoreal/{tag or layout_slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in views:
        aim(cam, name)
        expose(cam, name)
        sc.render.filepath = str(out_dir / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print("RENDERED", sc.render.filepath)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Photoreal Cycles renders of a layout from room.json cameras.")
    ap.add_argument("layout")
    ap.add_argument("--samples", type=int, default=48, help="Cycles samples (quick tests: 16)")
    ap.add_argument("--views", default=",".join(VIEWS), help="comma-separated room.json cameras (default: all)")
    ap.add_argument("--res", default="1400x875", help="WxH (quick tests: 700x440)")
    ap.add_argument("--lighting", default="standard", help="day / night / evening / standard, or a scene name from room.json")
    ap.add_argument("--tag", help="output folder name (defaults to the layout slug)")
    ap.add_argument("--exposure", type=float, help="fixed exposure in stops for every view (overrides the scene; the auto value is printed per view)")
    ap.add_argument("--white-balance", type=float, help="fixed white balance in K (overrides the scene)")
    ap.add_argument("--meter-layout", help="meter auto exposure on this layout instead (e.g. today's, for today-vs-proposal pairs)")
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    OVERRIDE.update({"exposure": args.exposure, "whiteBalance": args.white_balance})
    render(args.layout, args.samples, [v for v in args.views.split(",") if v], tuple(int(v) for v in args.res.split("x")), args.lighting, args.tag,
           args.meter_layout)
