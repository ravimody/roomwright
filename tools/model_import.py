# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*"]
# ///
"""Turn a downloaded 3D model into a clean GLB for a catalog entry ("model": "glb", "file": "models/<name>.glb").

Imports GLB/glTF, OBJ, FBX, USD/USDZ, STL, PLY or DAE; keeps only the meshes (and their materials), optionally only
the objects whose names contain one of --only; converts units; turns it so its front faces -y (south at rot 0, the
engine's convention); sets it on the floor centred on its footprint; reduces it to a triangle budget; optionally scales
it to the product's real size; and writes one GLB. Prints the size before and after, and against --spec, so you can
check the model against the spec sheet before using it.

Usage (from the household folder, or a room folder for a room-only model):
  uv run tools/model_import.py <file> [--out models/<name>.glb] [--units auto|m|cm|mm|in] [--front -y|+y|-x|+x]
      [--rotate RX,RY,RZ] [--only NAME[,NAME]] [--fit W,D,H [--stretch]] [--spec W,D,H] [--max-tris 150000]
      [--max-texture 1024]

  --front     which way the model's front faces after import (glTF files from most sources: -y, the default)
  --rotate    extra rotation in degrees about x, y, z (e.g. 90,0,0 for a model lying on its back)
  --fit       scale to the product's size in metres (uniform, so it fits inside; --stretch: each axis exactly)
  --spec      compare with the product's size without scaling
Then add {"model": "glb", "file": "models/<name>.glb", "w": .., "d": .., "h": ..} to the catalog; the renderer and
the editor fit it to w x d x h again (catalog `fit`). Check licences first: docs/MODELING.md lists sources.
"""

import argparse
import math
import sys
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

from mathutils import Euler, Matrix, Vector

IMPORTERS = {".glb": "gltf", ".gltf": "gltf", ".obj": "obj", ".fbx": "fbx", ".usd": "usd", ".usdz": "usd", ".usda": "usd",
             ".usdc": "usd", ".stl": "stl", ".ply": "ply", ".dae": "dae"}
UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254}
FRONT = {"-y": 0.0, "+y": 180.0, "+x": -90.0, "-x": 90.0}  # degrees about z that turn that direction to -y


def triple(s):
    v = [float(x) for x in s.split(",")]
    if len(v) != 3:
        raise argparse.ArgumentTypeError("give three numbers: a,b,c")
    return v


def load(path):
    kind = IMPORTERS.get(path.suffix.lower())
    if not kind:
        sys.exit(f"{path.name}: unsupported format (use {', '.join(sorted(IMPORTERS))})")
    op = {"gltf": lambda: bpy.ops.import_scene.gltf(filepath=str(path)),
          "obj": lambda: bpy.ops.wm.obj_import(filepath=str(path)),
          "fbx": lambda: bpy.ops.import_scene.fbx(filepath=str(path)),
          "usd": lambda: bpy.ops.wm.usd_import(filepath=str(path)),
          "stl": lambda: bpy.ops.wm.stl_import(filepath=str(path)),
          "ply": lambda: bpy.ops.wm.ply_import(filepath=str(path)),
          "dae": lambda: bpy.ops.wm.collada_import(filepath=str(path))}[kind]
    try:
        op()
    except (AttributeError, RuntimeError) as e:
        sys.exit(f"{path.name}: this Blender can't import {path.suffix} ({e}); convert it to GLB or OBJ first")


def bounds(ob):
    """(lo, hi) of the mesh's vertices (its transform is applied, so these are world coordinates; bound_box would be
    stale after mesh.transform() until the depsgraph updates)."""
    pts = [v.co for v in ob.data.vertices]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    return lo, hi


def fmt(v):
    return " x ".join(f"{x:.3f}" for x in v)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path, help="output GLB (default models/<file stem>.glb)")
    ap.add_argument("--units", default="auto", choices=["auto", *UNITS])
    ap.add_argument("--front", default="-y", choices=list(FRONT))
    ap.add_argument("--rotate", type=triple, default=[0, 0, 0])
    ap.add_argument("--only", help="keep only objects whose names contain one of these (comma-separated)")
    ap.add_argument("--fit", type=triple, help="W,D,H in metres: scale to this size")
    ap.add_argument("--stretch", action="store_true", help="with --fit: scale each axis to it (default: uniform)")
    ap.add_argument("--spec", type=triple, help="W,D,H in metres: compare only")
    ap.add_argument("--max-tris", type=int, default=150_000)
    ap.add_argument("--max-texture", type=int, default=1024, help="longest side of any texture, in pixels")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    if not a.file.is_file():
        sys.exit(f"{a.file}: not found")
    out = a.out or Path("models") / f"{a.file.stem}.glb"

    bpy.ops.wm.read_factory_settings(use_empty=True)
    load(a.file.resolve())
    keep = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if a.only:
        names = [n.strip() for n in a.only.split(",") if n.strip()]
        keep = [o for o in keep if any(n in o.name for n in names)]
    if not keep:
        sys.exit(f"{a.file.name}: no meshes" + (f" matching {a.only!r}" if a.only else ""))
    # bake every parent transform into the meshes, drop everything else (cameras, lights, empties), join into one
    bpy.context.view_layer.update()
    for o in keep:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    for o in list(bpy.context.scene.objects):
        if o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = keep[0]
    if len(keep) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    lo, hi = bounds(ob)
    size = hi - lo
    print(f"imported {a.file.name}: {len(ob.data.polygons)} faces, size {fmt(size)} (file units)")

    unit = UNITS.get(a.units)
    if unit is None:  # auto: furniture is 0.05-6 m; larger numbers are cm or mm
        big = max(size)
        unit = 1.0 if big < 8 else 0.01 if big < 800 else 0.001
        if unit != 1.0:
            print(f"units: looks like {'cm' if unit == 0.01 else 'mm'} ({big:.0f} on the longest side); scaled by {unit} (--units to override)")
    rot = Euler([math.radians(x) for x in a.rotate]).to_matrix().to_4x4()
    turn = Matrix.Rotation(math.radians(FRONT[a.front]), 4, "Z")
    ob.data.transform(turn @ rot @ Matrix.Scale(unit, 4))
    ob.data.update()
    lo, hi = bounds(ob)
    size = hi - lo
    if a.fit:
        k = [a.fit[i] / max(size[i], 1e-9) for i in range(3)]
        if not a.stretch:
            k = [min(k)] * 3
        ob.data.transform(Matrix.Diagonal((*k, 1.0)))
        ob.data.update()
        lo, hi = bounds(ob)
        size = hi - lo
    ob.data.transform(Matrix.Translation((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)))  # footprint centre, floor
    ob.data.update()
    tris = sum(len(p.vertices) - 2 for p in ob.data.polygons)
    if tris > a.max_tris:
        mod = ob.modifiers.new("decimate", "DECIMATE")
        mod.ratio = a.max_tris / tris
        bpy.ops.object.modifier_apply(modifier=mod.name)
        print(f"decimated {tris} -> {sum(len(p.vertices) - 2 for p in ob.data.polygons)} triangles")
    for img in bpy.data.images:  # smaller textures: a few MB per model at most
        if img.size[0] > a.max_texture or img.size[1] > a.max_texture:
            k = a.max_texture / max(img.size)
            img.scale(max(1, round(img.size[0] * k)), max(1, round(img.size[1] * k)))
    ob.name = out.stem
    print(f"size (w x d x h, m): {fmt(size)}")
    spec = a.spec or a.fit
    if spec:
        off = [size[i] / spec[i] - 1 for i in range(3)]
        verdict = "matches" if max(abs(x) for x in off) <= 0.03 else "differs from"
        print(f"{verdict} the spec {fmt(spec)}: " + ", ".join(f"{n} {x * 100:+.0f}%" for n, x in zip("wdh", off)))
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(out.resolve()), export_format="GLB", use_selection=True, export_apply=True, export_image_format="AUTO")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB): add {{\"model\": \"glb\", \"file\": \"{out.as_posix()}\", "
          f"\"w\": {size.x:.3f}, \"d\": {size.y:.3f}, \"h\": {size.z:.3f}}} to the catalog")


if __name__ == "__main__":
    main()
