"""The modelling kit for photoreal renders (bpy): the engine's own item models and the helpers builders use.
Mirrors editor/src/kit.js.

The engine ships no furniture library. It draws an item from its catalog entry with one of the core models:
  box       a plain box at w x d x h in the item's `color` (also the fallback for anything unknown)
  parts     a list of primitives in the catalog entry (box, cylinder, cone, sphere, lathe, extrude): see docs/MODELING.md
  glb       a model file (`file`, e.g. models/chair.glb from tools/model_import.py), fitted to w x d x h
  mat       a flat mat or rug (`texture` image, `pattern: "persian"` or a colour); roundRug a round one
Anything else comes from a household's builders: `<household>/builders/*.py` and `<room>/builders/*.py`, plain modules
that export BUILDERS = {name: fn(spec, builder, materials)} and import these helpers (pbr, wood, fabric, Builder, lathe,
point_light, linen_shade, paper, ...). The household folder is the one holding rooms/ (roomframe.household_root).

Local frame per item: origin at footprint center on the floor, width along +X, depth along Y,
front facing -Y (plan rot 0 = front faces south), up +Z. JS models use (x, y_up, z_front);
a JS point (x, y, z) maps here to (x, -z, y), and JS rotation.x maps to the same rotation about X.
"""

import importlib.util
import itertools
import math
import os
import sys
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

import bmesh
from mathutils import Euler

import photometry as ph
import roomframe

REPO = Path(__file__).resolve().parent.parent  # engine root: shared catalog and materials
ROOM = Path(os.environ.get("ROOM", ".")).resolve()  # room folder (run from inside rooms/<room>/ or set ROOM=)
_mats = {}
LAMPS_ON = True  # render_photoreal turns plug-in lamps off for daylight scenes
CEILING = 1.0  # the scene's dimmer setting for items on the ceiling layer ("layer": "ceiling": pendants, flush lights, panels)
ROOM_KELVIN = None  # room.json lights.kelvin: the room's usual bulb colour, for lights that don't give their own
# Builders draw their lights at full output with legacy weights (watts); place_items then sets every light from the
# item's `light` data (lumens, kelvin, dimmer: physical_lights). LAMP_LEVEL stays 1.0 while a builder runs.
LAMP_LEVEL = 1.0
ASSUMED = []  # lights that used a default instead of data, listed by render_photoreal as ASSUMED lines
LIGHT_GROUPS = {}  # Cycles light group -> what it holds (render_photoreal, light_match)


def pbr(name, color, rough=0.5, metal=0.0, **extra):
    """Cached Principled material. extra: transmission, alpha, emission=(rgb, strength), coat."""
    key = (name, color, rough, metal, tuple(sorted(extra.items())))
    if key in _mats:
        try:
            if _mats[key].name:  # still alive? read_factory_settings() frees materials between scenes in one process
                return _mats[key]
        except ReferenceError:
            del _mats[key]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if "transmission" in extra:
        b.inputs["Transmission Weight"].default_value = extra["transmission"]
        b.inputs["IOR"].default_value = 1.5
        if extra["transmission"] >= 0.5:
            thin_glass(m)
    if "coat" in extra:
        b.inputs["Coat Weight"].default_value = extra["coat"]
    if "emission" in extra:
        rgb, strength = extra["emission"]
        b.inputs["Emission Color"].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = (*color, 1)
    _mats[key] = m
    return m


def thin_glass(m):
    """Flat glass (a window, a glass door) passes light straight through without bending it, but Cycles treats a
    refracting surface as opaque to shadow rays, so light behind it (daylight, a sauna's lamp) only arrives as noisy
    caustics. Shadow and diffuse rays see through it (tinted by the glass colour); camera and glossy rays still see
    the glass and its reflections."""
    nt = m.node_tree
    out = nt.nodes["Material Output"]
    bsdf = nt.nodes["Principled BSDF"]
    lp = nt.nodes.new("ShaderNodeLightPath")
    either = nt.nodes.new("ShaderNodeMath")
    either.operation = "MAXIMUM"
    nt.links.new(lp.outputs["Is Shadow Ray"], either.inputs[0])
    nt.links.new(lp.outputs["Is Diffuse Ray"], either.inputs[1])
    clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    clear.inputs["Color"].default_value = bsdf.inputs["Base Color"].default_value
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(either.outputs[0], mix.inputs["Fac"])
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(clear.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


def wood(name, color, scale=18.0, rough=0.6, coat=0.0, dark=None):
    """Procedural wood grain (sauna cedar / shelf boards). Low rough + coat = polished antique finish."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    b.inputs["Coat Weight"].default_value = coat
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1, 1, scale)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "RINGS"
    wave.inputs["Scale"].default_value = 2.5
    wave.inputs["Distortion"].default_value = 6
    wave.inputs["Detail"].default_value = 3
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    dark = tuple(c * (0.72 if dark is None else dark) for c in color)  # dark = grain shade factor
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*color, 1)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], wave.inputs["Vector"])
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    m.diffuse_color = (*color, 1)
    return m


def M():
    """Shared equipment materials."""
    return {
        "steel": pbr("powder_coat", (0.012, 0.012, 0.013), 0.42, 0.35),
        "chrome": pbr("chrome", (0.8, 0.8, 0.82), 0.12, 1.0),
        "rubber": pbr("rubber", (0.012, 0.012, 0.012), 0.92),
        "pad": pbr("vinyl_pad", (0.02, 0.02, 0.02), 0.55, coat=0.2),
        "plastic": pbr("plastic_dark", (0.03, 0.03, 0.035), 0.35),
        "red": pbr("red_accent", (0.5, 0.03, 0.03), 0.4),
        "screen": pbr("screen", (0.005, 0.005, 0.006), 0.05, coat=1.0),
        "mirror": pbr("mirror", (0.95, 0.95, 0.95), 0.015, 1.0),
        "glass": pbr("glass_sauna", (0.86, 0.8, 0.7), 0.01, transmission=1.0),  # light bronze tint, like a sauna's tempered-glass door
    }


class Builder:
    """Collects parts for one item under an empty."""

    def __init__(self, name, coll):
        self.coll = coll
        self.root = bpy.data.objects.new(name, None)
        coll.objects.link(self.root)

    def _obj(self, bm, material, name, bevel):
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(name, me)
        ob.data.materials.append(material)
        self.coll.objects.link(ob)
        ob.parent = self.root
        if bevel:
            mod = ob.modifiers.new("bevel", "BEVEL")
            mod.width = bevel
            mod.segments = 2
            mod.limit_method = "ANGLE"
        for p in me.polygons:
            p.use_smooth = False
        return ob

    def box(self, w, d, h, x, y, z, material, rx=0.0, bevel=0.004, name="part"):
        """Box sized w (x) x d (y) x h (z), centered at (x, y, z), rotated rx about X."""
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1)
        bmesh.ops.scale(bm, vec=(w, d, h), verts=bm.verts)
        ob = self._obj(bm, material, name, min(bevel, w / 3, d / 3, h / 3) if bevel else 0)
        ob.location = (x, y, z)
        ob.rotation_euler = (rx, 0, 0)
        return ob

    def cyl(self, r, length, x, y, z, material, axis="z", seg=32, bevel=0.002, name="cyl"):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=length)
        ob = self._obj(bm, material, name, min(bevel, r / 3) if bevel else 0)
        for p in ob.data.polygons:
            p.use_smooth = True
        ob.location = (x, y, z)
        ob.rotation_euler = {"x": (0, math.pi / 2, 0), "y": (math.pi / 2, 0, 0), "z": (0, 0, 0)}[axis]
        return ob

    # JS-frame helpers: (w, h, d) at JS (x, y_up, z_front) -> Blender
    def jbox(self, w, h, d, x, y, z, material, rx=0.0, **kw):
        return self.box(w, d, h, x, -z, y, material, rx, **kw)

    def jcyl(self, r, length, x, y, z, material, axis="y", **kw):
        return self.cyl(r, length, x, -z, y, material, {"y": "z", "x": "x", "z": "y"}[axis], **kw)


# ---------------------------------------------------------------- item builders


def b_box(s, b, m):
    color = s.get("color") or "#999999"
    b.box(s["w"], s["d"], s["h"], 0, 0, s["h"] / 2, pbr(f"box_{color}", hex_rgb(color), 0.8), bevel=0.01)


def b_mat(s, b, m):
    if s.get("pattern") == "persian" or s.get("rug") or s.get("texture"):
        return b_rug(s, b, m)
    h = max(s["h"], 0.012)
    b.box(s["w"], s["d"], h, 0, 0, h / 2, m["rubber"] if s.get("color", "#1c1c1c") == "#1c1c1c" else pbr("floor_mat", hex_rgb(s["color"]), 0.9), bevel=0.003)


def rnd(k):
    """Deterministic 0..1 noise (same formula as the editor, so both draw the same books)."""
    return (math.sin(k * 12.9898) * 43758.5453) % 1.0


def mathutils_translation(x, y, z):
    from mathutils import Matrix
    return Matrix.Translation((x, y, z))


def point_light(b, name, loc, watts, color=ph.LEGACY_WARM, radius=0.05):
    """A bulb. `watts` and `color` are the builder's legacy weights: place_items (physical_lights) replaces them
    with the item's lumens and colour temperature, split between its bulbs in proportion to these."""
    if not LAMPS_ON:
        return None
    ld = bpy.data.lights.new(name, "POINT")
    ld.energy, ld.color, ld.shadow_soft_size = watts, color, radius
    lo = bpy.data.objects.new(name, ld)
    lo.location = loc
    b.coll.objects.link(lo)
    lo.parent = b.root
    lo.visible_camera = lo.visible_glossy = lo.visible_transmission = False
    return lo


def paper(name="paper", glow=3.0):
    """Lit white paper: soft emission (legacy strength; place_items scales it with the item's lumens and dimmer),
    and it doesn't block the bulb inside it."""
    return pbr(name, (0.92, 0.88, 0.8), 0.9, emission=((1.0, 0.78, 0.55), glow if LAMPS_ON else 0.0))


def linen_shade():
    """Fabric lampshade that behaves like one: blocks most sideways light (so lamps throw pools up and down, not a
    room-filling glow) and lets ~30% through, so it glows warm from the bulb inside. Casts shadows."""
    key = ("linen_shade_real", LAMPS_ON)
    if key in _mats:
        try:
            if _mats[key].name:  # still alive? (read_factory_settings() frees materials between scenes in one process)
                return _mats[key]
        except ReferenceError:
            del _mats[key]
    m = bpy.data.materials.new("linen_shade_real")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    out = nt.nodes["Material Output"]
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    dif.inputs["Color"].default_value = (0.88, 0.84, 0.76, 1)
    tr = nt.nodes.new("ShaderNodeBsdfTranslucent")
    tr.inputs["Color"].default_value = (1.0, 0.86, 0.66, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.3
    nt.links.new(dif.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    m.diffuse_color = (0.88, 0.84, 0.76, 1)
    _mats[key] = m
    return m


def fabric(name, color, rough=0.95, sheen=0.4):
    m = pbr(name, color, rough)
    if "Sheen Weight" in m.node_tree.nodes["Principled BSDF"].inputs:
        m.node_tree.nodes["Principled BSDF"].inputs["Sheen Weight"].default_value = sheen
    return m


def top_slab(b, pts, z0, z1, material, name="top"):
    """Extruded plan-shape slab (local coords)."""
    bm = bmesh.new()
    lo = [bm.verts.new((x, y, z0)) for x, y in pts]
    hi = [bm.verts.new((x, y, z1)) for x, y in pts]
    bm.faces.new(list(reversed(lo)))
    bm.faces.new(hi)
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        bm.faces.new([lo[i], lo[j], hi[j], hi[i]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return b._obj(bm, material, name, 0.006)


def shape_points(shape, w, d, n=48):
    if shape == "oval":
        return [(w / 2 * math.cos(2 * math.pi * k / n), d / 2 * math.sin(2 * math.pi * k / n)) for k in range(n)]
    if shape == "cloud":  # soft irregular organic outline
        return [(w / 2 * math.cos(t) * (1 + 0.07 * math.sin(3 * t + 0.6)), d / 2 * math.sin(t) * (1 + 0.07 * math.cos(2 * t))) for t in (2 * math.pi * k / n for k in range(n))]
    return [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]


def lathe(b, profile, x, y, z0, material, seg=28, name="turned", caps=True):
    """Solid of revolution about a vertical axis at (x, y): profile [(radius, dz), ...] from bottom to top; caps=False
    leaves the ends open (a lampshade)."""
    bm = bmesh.new()
    rings = [[bm.verts.new((x + max(r, 0.001) * math.cos(2 * math.pi * k / seg), y + max(r, 0.001) * math.sin(2 * math.pi * k / seg), z0 + dz))
              for k in range(seg)] for r, dz in profile]
    for a, c in itertools.pairwise(rings):
        for k in range(seg):
            j = (k + 1) % seg
            bm.faces.new([a[k], a[j], c[j], c[k]])
    if caps:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    ob = b._obj(bm, material, name, 0)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def persian(name, w, d):
    """Procedural Persian-style rug: navy border, cream guard stripe, red field with a navy medallion."""
    mt = bpy.data.materials.new(name)
    mt.use_nodes = True
    nt = mt.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.98
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])

    def op(kind, a, bval=None):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = kind
        for i, v in enumerate((a, bval)):
            if v is None:
                continue
            if isinstance(v, float):
                n.inputs[i].default_value = v
            else:
                nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    ux = op("DIVIDE", op("ABSOLUTE", sep.outputs[0]), w / 2)
    uy = op("DIVIDE", op("ABSOLUTE", sep.outputs[1]), d / 2)
    edge = op("MAXIMUM", ux, uy)
    rad = op("MULTIPLY", op("ADD", ux, uy), 0.75)  # diamond-shaped (lozenge) medallion
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 22
    noise.inputs["Detail"].default_value = 6
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    field = nt.nodes.new("ShaderNodeValToRGB")  # mostly deep red, with small navy and ivory motifs
    fe = field.color_ramp.elements
    fe[0].position, fe[0].color = 0.0, (0.26, 0.025, 0.02, 1)
    fe[1].position, fe[1].color = 1.0, (0.36, 0.035, 0.025, 1)
    for pos, col in ((0.44, (0.34, 0.035, 0.025, 1)), (0.47, (0.03, 0.04, 0.1, 1)), (0.5, (0.33, 0.035, 0.025, 1)),
                     (0.6, (0.33, 0.035, 0.025, 1)), (0.62, (0.55, 0.45, 0.3, 1)), (0.64, (0.36, 0.035, 0.025, 1))):
        el = fe.new(pos)
        el.color = col
    field.color_ramp.interpolation = "EASE"
    nt.links.new(noise.outputs["Fac"], field.inputs["Fac"])
    border = nt.nodes.new("ShaderNodeValToRGB")
    border.color_ramp.interpolation = "CONSTANT"
    els = border.color_ramp.elements
    els[0].position, els[0].color = 0.0, (0, 0, 0, 0)  # alpha 0 = show field
    els[1].position, els[1].color = 0.97, (0.6, 0.55, 0.42, 1)  # fringe edge
    for pos, col in ((0.8, (0.03, 0.045, 0.11, 1)), (0.84, (0.55, 0.47, 0.32, 1)), (0.87, (0.03, 0.045, 0.11, 1))):
        n_ = els.new(pos)
        n_.color = col
    nt.links.new(edge, border.inputs["Fac"])
    med = nt.nodes.new("ShaderNodeValToRGB")  # navy centre, ivory ring, red band, navy outline
    med.color_ramp.interpolation = "CONSTANT"
    me = med.color_ramp.elements
    me[0].position, me[0].color = 0.0, (0.03, 0.045, 0.11, 1)
    me[1].position, me[1].color = 0.34, (0, 0, 0, 0)
    for pos, col in ((0.1, (0.55, 0.47, 0.32, 1)), (0.12, (0.3, 0.03, 0.025, 1)), (0.26, (0.03, 0.045, 0.11, 1)), (0.3, (0.55, 0.47, 0.32, 1))):
        el = me.new(pos)
        el.color = col
    nt.links.new(rad, med.inputs["Fac"])
    mix1 = nt.nodes.new("ShaderNodeMix")
    mix1.data_type = "RGBA"
    nt.links.new(med.outputs["Alpha"], mix1.inputs["Factor"])
    nt.links.new(field.outputs["Color"], mix1.inputs[6])
    nt.links.new(med.outputs["Color"], mix1.inputs[7])
    mix2 = nt.nodes.new("ShaderNodeMix")
    mix2.data_type = "RGBA"
    nt.links.new(border.outputs["Alpha"], mix2.inputs["Factor"])
    nt.links.new(mix1.outputs[2], mix2.inputs[6])
    nt.links.new(border.outputs["Color"], mix2.inputs[7])
    nt.links.new(mix2.outputs[2], bsdf.inputs["Base Color"])
    return mt


def image_rug(path, w, d, gain=1.0, sat=1.0):
    """Rug material from a whole-rug image (scan-recovered or procedural): image top = the rug's +y (north at rot 0).
    gain/sat lift a scan texture, which comes out darker and duller than the rug looks in the scan's own views."""
    key = f"rugimg_{Path(path).stem}_{gain}_{sat}"[:63]  # Blender names stop at 63 bytes; no local paths in names
    if key in bpy.data.materials:
        return bpy.data.materials[key]
    mt = bpy.data.materials.new(key)
    mt.use_nodes = True
    nt = mt.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.97
    if "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = 0.3  # wool pile
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")  # object coords (metres, centred) -> 0..1 UV
    mp.inputs["Scale"].default_value = (1 / w, 1 / d, 1)
    mp.inputs["Location"].default_value = (0.5, 0.5, 0)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(path))
    tex.extension = "EXTEND"
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], tex.inputs["Vector"])
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Saturation"].default_value = sat
    hsv.inputs["Value"].default_value = gain
    nt.links.new(tex.outputs["Color"], hsv.inputs["Color"])
    nt.links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])
    return mt


def b_rug(s, b, m):
    """Flat rug. `texture`: a whole-rug image under the room folder (e.g. textures/rug-persian-scanned.jpg);
    else `pattern: "persian"` (procedural) or a plain colour."""
    h = max(s.get("h", 0.01), 0.008)
    if s.get("texture"):
        mt = image_rug(asset(s["texture"]), s["w"], s["d"], s.get("textureGain", 1.0), s.get("textureSat", 1.0))
    elif s.get("pattern") == "persian":
        mt = persian(f"rug_{s['id']}", s["w"], s["d"])
    else:
        mt = fabric(f"rug_{s.get('color')}", hex_rgb(s.get("color", "#a59c8c")), 0.98, 0.2)
    ob = b.box(s["w"], s["d"], h, 0, 0, h / 2, mt, bevel=0.003)
    ob.visible_shadow = True


def b_round_rug(s, b, m):
    b.cyl(s["w"] / 2, max(s.get("h", 0.01), 0.008), 0, 0, 0.005, fabric(f"rug_{s.get('color')}", hex_rgb(s.get("color", "#d9cfbf")), 0.98, 0.3), seg=64, bevel=0.003)


def asset(rel):
    """A file named in room data (a texture, a model): in the room folder, else in the household folder."""
    return roomframe.asset_path(rel, ROOM)


def hex_rgb(h):
    h = (h or "#888888").lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)


# ---------------------------------------------------------------- parts: simple modelling as catalog data


def part_material(s, ref):
    """A part's material: a name from the item's `materials` map, a "#rrggbb" colour, or (no `material`) the item's
    `color`. A `materials` entry is {hex, rough, metal, coat, kind}; kind is paint (default), wood (with grain), fabric,
    metal, glass, shade (a translucent fabric lampshade) or glow (lit paper, glowing while the lamps are on)."""
    mats = s.get("materials") or {}
    if isinstance(ref, str) and ref in mats:
        spec, name = mats[ref], ref
    elif isinstance(ref, str) and ref.startswith("#"):
        spec, name = {"hex": ref}, ref.lstrip("#")
    else:
        spec, name = {}, "body"
    kind, rough = spec.get("kind", "paint"), spec.get("rough")
    col = hex_rgb(spec.get("hex") or s.get("color") or "#888888")
    nm = f"{s.get('type', 'item')}_{name}"[:60]
    if kind == "wood":
        return wood(nm, col, rough=0.55 if rough is None else rough, coat=spec.get("coat", 0.0))
    if kind == "fabric":
        return fabric(nm, col, 0.95 if rough is None else rough)
    if kind == "metal":
        return pbr(nm, col, 0.3 if rough is None else rough, spec.get("metal", 1.0))
    if kind == "glass":
        return pbr(nm, col, 0.02 if rough is None else rough, transmission=1.0)
    if kind == "shade":
        return linen_shade()
    if kind == "glow":
        return paper(nm)
    return pbr(nm, col, 0.6 if rough is None else rough, spec.get("metal", 0.0), coat=spec.get("coat", 0.0))


PART_MIRRORS = {None: [(1, 1)], "x": [(1, 1), (-1, 1)], "y": [(1, 1), (1, -1)], "xy": [(1, 1), (-1, 1), (1, -1), (-1, -1)]}


def _part(b, p, mat, sx, sy, name):
    """One primitive of a `parts` item, mirrored by (sx, sy). Positions are item-local metres: x to the right as you
    face the item's front, y toward its back, z up; `at` is the centre (box, cylinder, cone, sphere) or the base point
    (lathe, extrude)."""
    x, y, z = p.get("at", (0, 0, 0))
    x, y = x * sx, y * sy
    rx, ry, rz = p.get("rot", (0, 0, 0))
    if sx < 0:
        ry, rz = -ry, -rz
    if sy < 0:
        rx, rz = -rx, -rz
    shape = p.get("shape", "box")
    seg = p.get("seg", 32)
    if shape == "box":
        w, d, h = p["size"]
        ob = b.box(w, d, h, x, y, z, mat, bevel=p.get("bevel", 0.004), name=name)
    elif shape in ("cylinder", "cone"):
        r0, r1 = (p["r"], p["r"]) if shape == "cylinder" else (p["r0"], p["r1"])
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=not p.get("open"), segments=seg, radius1=max(r0, 1e-4), radius2=max(r1, 1e-4), depth=p["h"])
        ob = b._obj(bm, mat, name, 0)
        for f in ob.data.polygons:
            f.use_smooth = True
        ob.location = (x, y, z)
        ob.rotation_euler = {"x": (0, math.pi / 2, 0), "y": (math.pi / 2, 0, 0), "z": (0, 0, 0)}[p.get("axis", "z")]
    elif shape == "sphere":
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(seg // 2, 4), radius=p["r"])
        bmesh.ops.scale(bm, vec=tuple(p.get("scale", (1, 1, 1))), verts=bm.verts)
        ob = b._obj(bm, mat, name, 0)
        for f in ob.data.polygons:
            f.use_smooth = True
        ob.location = (x, y, z)
    elif shape == "lathe":
        ob = lathe(b, [(r, dz) for r, dz in p["profile"]], 0, 0, 0, mat, seg=seg, name=name, caps=not p.get("open"))
        ob.location = (x, y, z)
    elif shape == "extrude":
        pts = [(px * sx, py * sy) for px, py in p["points"]]
        if sx * sy < 0:
            pts.reverse()
        ob = top_slab(b, pts, 0, p["h"], mat, name=name)
        ob.location = (x, y, z)
    else:
        print(f"warning: part {name}: unknown shape {shape!r} (box, cylinder, cone, sphere, lathe, extrude)")
        return None
    if rx or ry or rz:
        ob.rotation_euler = (Euler((math.radians(rx), math.radians(ry), math.radians(rz))).to_matrix() @ ob.rotation_euler.to_matrix()).to_euler()
    if p.get("role"):
        ob["role"] = p["role"]  # e.g. "shade": the part a lamp's light sits in
    if p.get("role") == "shade":  # a lamp: a bulb in the shade's middle (its output comes from the item's `light` data)
        mid = sum(dz for _, dz in p["profile"]) / len(p["profile"]) if shape == "lathe" else 0.0
        point_light(b, f"{name}_bulb", (x, y, z + mid), 60, radius=0.03)
    return ob


def b_parts(s, b, m):
    """`parts`: the item drawn from the primitives listed in its catalog entry (or layout item); docs/MODELING.md.
    Parts are drawn at `partsSize` (default: the catalog entry's w x d x h); an item resized in a layout stretches."""
    parts = s.get("parts") or []
    if not parts:
        return b_box(s, b, m)
    pw, pd, ph = s.get("partsSize") or (s["w"], s["d"], s["h"])
    if (pw, pd, ph) != (s["w"], s["d"], s["h"]):
        b.root.scale = (s["w"] / pw, s["d"] / pd, s["h"] / ph)
    mats = {}
    for i, p in enumerate(parts):
        ref = p.get("material")
        if ref not in mats:
            mats[ref] = part_material(s, ref)
        for sx, sy in PART_MIRRORS.get(p.get("mirror"), [(1, 1)]):
            _part(b, p, mats[ref], sx, sy, p.get("name", f"part{i}"))
    return None


def b_glb(s, b, m):
    """`glb`: a model file (`file`, e.g. models/chair.glb, looked up in the room folder, then the household folder) fitted
    to the item's w x d x h. `fit`: "scale" (default: uniform, fits inside the box), "stretch" (each axis to the box) or
    "none"; `rotate` [x, y, z] degrees is applied first, to turn the model's front to -y (south at rot 0) or stand it up.
    tools/model_import.py prepares files so that neither is needed."""
    path = asset(s.get("file", ""))
    if not s.get("file") or not path.is_file() or roomframe.is_lfs_pointer(path):
        print(f"warning: item {s.get('id')}: model file {s.get('file')!r} not found (room folder, then household); drawn as a box")
        return b_box(s, b, m)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    holder = bpy.data.objects.new(f"{s.get('id', 'item')}_model", None)  # scale and offset, in room axes
    turn = bpy.data.objects.new(f"{s.get('id', 'item')}_turn", None)  # `rotate`, applied before the fit
    for o in (holder, turn):
        b.coll.objects.link(o)
    holder.parent, turn.parent = b.root, holder
    turn.rotation_euler = [math.radians(a) for a in s.get("rotate", (0, 0, 0))]
    for o in new:
        for c in o.users_collection:
            c.objects.unlink(o)
        b.coll.objects.link(o)
        if o.parent is None:
            o.parent = turn
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ v.co for o in new if o.type == "MESH" for v in o.data.vertices]
    if not pts:
        print(f"warning: item {s.get('id')}: {s['file']} has no meshes")
        return None
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    size = [max(hi[i] - lo[i], 1e-6) for i in range(3)]
    want = (s["w"], s["d"], s["h"])
    fit = s.get("fit", "scale")
    k = [want[i] / size[i] for i in range(3)]
    if fit == "scale":
        k = [min(k)] * 3
    elif fit == "none":
        k = [1.0] * 3
    holder.scale = k
    holder.location = (-(lo[0] + hi[0]) / 2 * k[0], -(lo[1] + hi[1]) / 2 * k[1], -lo[2] * k[2])
    if fit == "scale" and max(want[i] / (size[i] * k[0]) for i in range(3)) > 1.15:
        got = " x ".join(f"{size[i] * k[0]:.2f}" for i in range(3))
        print(f"note: item {s.get('id')}: {s['file']} fitted to {got} m inside {want[0]} x {want[1]} x {want[2]} (proportions differ)")
    return None


# ---------------------------------------------------------------- builders: core models plus the household's


CORE = {"box": b_box, "mat": b_mat, "roundRug": b_round_rug, "parts": b_parts, "glb": b_glb}
BUILDERS = dict(CORE)  # load_builders() adds the household's and the room's builders
_loaded = {}


def builder_dirs(room_dir=None):
    """Folders searched for builder modules: <household>/builders, then <room>/builders (later wins)."""
    rd = Path(room_dir or ROOM).resolve()
    hh = roomframe.household_root(rd)
    return [d for d in (hh / "builders" if hh else None, rd / "builders") if d and d.is_dir()]


def load_builders(room_dir=None):
    """The core models plus every module in builder_dirs() (files starting with _ are helpers, not loaded): each
    module's BUILDERS {name: fn(spec, builder, materials)}. Helper modules are imported by name, so builder folders go
    on sys.path; give a room's helpers names that differ from the household's."""
    dirs = tuple(builder_dirs(room_dir))
    if dirs not in _loaded:
        reg = dict(CORE)
        for i, d in enumerate(dirs):
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
            for f in sorted(d.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                name = f"_roomwright_builders{i}_{f.stem}"
                spec = importlib.util.spec_from_file_location(name, f)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                reg.update(getattr(mod, "BUILDERS", {}))
        _loaded[dirs] = reg
    BUILDERS.clear()
    BUILDERS.update(_loaded[dirs])
    return BUILDERS


def load_catalog(room_dir=None):
    """Item types for a room: shared/catalog.json, then the household's catalog.json, then the room's (later wins)."""
    return roomframe.load_catalog(room_dir or ROOM)


def legacy_kelvin(rgb):
    """Colour temperature for a builder's legacy light colour: the old default warm is DEFAULT_KELVIN, and other
    colours keep their offset from it in mired (a candle's redder colour lands near 1900 K)."""
    m = ph.mired(ph.DEFAULT_KELVIN) + ph.mired(ph.rgb_kelvin(rgb)) - ph.mired(ph.rgb_kelvin(ph.LEGACY_WARM))
    return min(max(1e6 / max(m, 1.0), 1500.0), 12000.0)


def _group_name(text):
    return "".join(c if c.isalnum() else "_" for c in text)[:60]


def light_group(key, info):
    """Register a Cycles light group (one per lamp type and dimmer setting, the cans, daylight, ...). Same key and
    same settings share a group; a second setting of one type gets its own (named after the item)."""
    name = _group_name(key)
    old = LIGHT_GROUPS.get(name)
    same = old and all(old.get(k) == info.get(k) for k in ("kind", "lumens", "kelvin", "dim"))
    if old and not same and info.get("ids"):
        name = _group_name(f"{key}__{info['ids'][0]}")
        old = LIGHT_GROUPS.get(name)
        same = bool(old)
    if same:
        new_ids = [i for i in info.get("ids", []) if i not in old.get("ids", [])]
        if new_ids or not info.get("ids"):
            old["ids"] = old.get("ids", []) + new_ids
            old["count"] = old.get("count", 1) + 1
            old["flux"] = (old.get("flux") or 0) + (info.get("flux") or 0)
            old["what"] = f"{old['label']} x{old['count']}"
    else:
        LIGHT_GROUPS[name] = {**info, "count": 1, "what": info["label"]}
    return name


def _descendants(ob):
    out, stack = [], list(ob.children)
    while stack:
        o = stack.pop()
        out.append(o)
        stack.extend(o.children)
    return out


def _emissive_slots(ob):
    for slot in ob.material_slots:
        mt = slot.material
        bsdf = mt.node_tree.nodes.get("Principled BSDF") if (mt and mt.use_nodes) else None
        if bsdf and bsdf.inputs["Emission Strength"].default_value > 0 and max(bsdf.inputs["Emission Color"].default_value[:3]) > 0:
            yield slot, bsdf


def physical_lights(s, root):
    """Give an item's lights real units. The builder drew its bulbs (and glowing parts) with legacy weights; the item's
    `light` {lumens (whole item), kelvin, dimToWarm: [kFull, kMin], dimCurve, beam} from the catalog or layout sets
    them, with the scene's dimmer setting (s["dim"], from lampDim) through the dimmer curve and a tunable bulb's
    colour (s["kelvinSet"], from lampKelvin). Missing values come from the builder (its legacy watts, anchored on an
    800 lm bulb) and are listed in ASSUMED."""
    parts = _descendants(root)
    lights = [o for o in parts if o.type == "LIGHT"]
    glows = [(o, slot, bsdf) for o in parts if o.type == "MESH" for slot, bsdf in _emissive_slots(o)]
    if not lights and not glows:
        return
    spec = s.get("light") or {}
    weights = []
    for o in lights:
        ld = o.data
        cone = ph.cone_solid_angle(math.degrees(ld.spot_size)) / (4 * math.pi) if ld.type == "SPOT" else 1.0
        weights.append(ld.energy * ph.luminance(ld.color) * ph.LEGACY_LM_PER_W * cone)
    legacy_lm = sum(weights)
    lumens = spec.get("lumens", legacy_lm or ph.DEFAULT_BULB_LM)
    dom = lights[max(range(len(lights)), key=lambda i: weights[i])].data.color if lights else glows[0][2].inputs["Emission Color"].default_value
    built = legacy_kelvin(tuple(dom)[:3])
    # the room's usual bulb colour replaces only an ordinary bulb's; a flame or a coloured light keeps the builder's colour
    room_bulb = bool(ROOM_KELVIN) and abs(ph.mired(built) - ph.mired(ph.DEFAULT_KELVIN)) < 30
    kelvin = spec.get("kelvin") or (ROOM_KELVIN if room_bulb else built)
    missing = [k for k in ("lumens", "kelvin") if k not in spec and not (k == "kelvin" and ("dimToWarm" in spec or room_bulb))]
    if missing and lights:  # (an item that only glows, e.g. an LED trim, keeps its builder's glow quietly)
        ASSUMED.append((s.get("type", s["id"]), s["id"], f"{lumens:.0f} lm" if "lumens" in missing else None,
                        f"{kelvin:.0f} K" if "kelvin" in missing else None))
    setting = s.get("dim", 1.0)
    curve = spec.get("dimCurve", "square")
    out = ph.dimmer_output(setting, curve)
    if s.get("kelvinSet"):
        kelvin = s["kelvinSet"]
    elif spec.get("dimToWarm"):
        kelvin = ph.dim_to_warm(setting, *spec["dimToWarm"])
    rgb = ph.kelvin_rgb(kelvin)
    group = light_group(f"item_{s.get('type', s['id'])}", {"kind": "item", "type": s.get("type"), "ids": [s["id"]], "lumens": lumens if lights else None,
                                                         "kelvin": round(kelvin), "dim": setting, "dimCurve": curve, "rgb": rgb,
                                                         "label": s.get("type", s["id"]), "assumed": "lumens" in missing})
    for o, w in zip(lights, weights):
        ld = o.data
        lm = lumens * (w / legacy_lm if legacy_lm else 1 / len(lights)) * out
        ld.color = rgb
        if ld.type == "SPOT":
            beam = spec.get("beam", math.degrees(ld.spot_size))
            ld.spot_size = math.radians(beam)
            ld.energy = ph.spot_watts(lm, beam)
        else:
            ld.energy = ph.watts(lm)
        o.lightgroup = group
    ratio = lumens / legacy_lm if legacy_lm else 1.0
    copies = {}
    for o, slot, _bsdf in glows:
        mt = slot.material
        if mt.name not in copies:
            c = mt.copy()
            cb = c.node_tree.nodes["Principled BSDF"]
            strength = cb.inputs["Emission Strength"].default_value * ph.luminance(cb.inputs["Emission Color"].default_value[:3])
            cb.inputs["Emission Strength"].default_value = strength * ph.LEGACY_EMISSION * ratio * out
            cb.inputs["Emission Color"].default_value = (*rgb, 1)
            copies[mt.name] = c
        slot.material = copies[mt.name]
        o.lightgroup = group


def interior_light(s, b):
    """Optional catalog/item `interiorLight` {lumens, kelvin, z, size}: a point light inside the item (a sauna's or a
    lit cabinet's lamp), on with the lamps unless the scene switches the item off (lampsOff). Hidden from the camera,
    glass and reflections so its sphere never shows. Legacy {watts, color} are converted like builder bulbs."""
    li = s.get("interiorLight")
    if not (li and LAMPS_ON and not s.get("off")):
        return
    color = tuple(li.get("color", ph.LEGACY_WARM))
    lumens = li.get("lumens") or (li["watts"] * ph.luminance(color) * ph.LEGACY_LM_PER_W if "watts" in li else ph.DEFAULT_BULB_LM)
    kelvin = li.get("kelvin") or (legacy_kelvin(color) if "color" in li else ROOM_KELVIN or ph.DEFAULT_KELVIN)
    if "lumens" not in li or "kelvin" not in li:
        ASSUMED.append((f"{s.get('type', s['id'])} interior light", s["id"], None if "lumens" in li else f"{lumens:.0f} lm",
                        None if "kelvin" in li else f"{kelvin:.0f} K"))
    rgb = ph.kelvin_rgb(kelvin)
    ld = bpy.data.lights.new(f"{s['id']}_glow", "POINT")
    ld.energy, ld.color, ld.shadow_soft_size = ph.watts(lumens), rgb, li.get("size", 0.3)
    lo = bpy.data.objects.new(f"{s['id']}_glow", ld)
    lo.visible_camera = lo.visible_transmission = lo.visible_glossy = False
    lo.location = (s["x"], s["y"], li.get("z", s.get("h", 1.0) * 0.85))
    lo.lightgroup = light_group(f"interior_{s.get('type', s['id'])}", {"kind": "interior", "type": s.get("type"), "ids": [s["id"]],
                                                                     "lumens": lumens, "kelvin": round(kelvin), "dim": 1.0, "rgb": rgb,
                                                                     "label": f"{s.get('type', s['id'])} interior light", "assumed": "lumens" not in li})
    b.coll.objects.link(lo)


def place_items(layout, catalog, coll, room=None):
    """Build every item in a layout at its plan position. Each item's root empty carries its layout id as the custom
    property "item_id" (Blender object names are capped at 63 bytes and get .001 suffixes on clashes). Items with
    `hang: "ceiling"` and no `ceiling` hang from the room's ceiling at their position (room: room.json, read from ROOM
    if not given)."""
    if room is None and (ROOM / "room.json").exists():
        import json

        room = roomframe.normalize_room(json.loads((ROOM / "room.json").read_text()))
    builders = load_builders(ROOM)
    m = M()
    global LAMPS_ON
    lamps_on = LAMPS_ON
    for it in layout["items"]:
        base = catalog.get(it["type"])
        if base is None:
            print(f"warning: item {it['id']}: type {it['type']!r} is not in the catalog; drawn as a plain box")
            base = catalog.get("generic_box", {"model": "box", "w": 0.5, "d": 0.5, "h": 0.5, "color": "#999999"})
        s = {**base, **it}
        if s["model"] == "parts" and "partsSize" not in s:  # the size the parts were drawn at
            s["partsSize"] = [base.get(k, s[k]) for k in ("w", "d", "h")]
        if s["model"] not in builders:
            print(f"warning: item {it['id']}: no Blender builder {s['model']!r}; drawn as a plain box")
        if s.get("hang") == "ceiling" and s.get("ceiling") is None and room:
            s["ceiling"] = roomframe.ceiling_z(room, s["x"], s["y"])
        b = Builder(it["id"], coll)
        b.root["item_id"] = it["id"]
        ceiling_layer = s.get("layer") == "ceiling"  # pendants, flush lights, panels: switched with the ceiling, not the lamps
        if ceiling_layer and "dim" not in it:
            s["dim"] = CEILING
        on = (s.get("dim", 0) > 0 if "dim" in it else CEILING > 0) if ceiling_layer else lamps_on  # lampDim switches one on
        LAMPS_ON = on and not s.get("off")  # a scene can switch single lights off (lampsOff)
        builders.get(s["model"], b_box)(s, b, m)
        physical_lights(s, b.root)  # lumens, kelvin and the scene's dimmer setting (lampDim) for its bulbs and glow
        z = s.get("z", 0) or 0
        if s["model"] in CORE and s.get("ceiling") is not None and not z:  # core models hang h below the ceiling (builders do it themselves)
            z = s["ceiling"] - s["h"]
        b.root.location = (s["x"], s["y"], z)
        b.root.rotation_euler = (0, 0, math.radians(s.get("rot", 0)))
        interior_light(s, b)
        LAMPS_ON = lamps_on
