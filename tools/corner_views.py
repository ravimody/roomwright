# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2"]
# ///
"""Perspective close-ups of the aligned scan (textured, flat light), to look at a corner, a soffit or an opening.

Usage, from inside rooms/<room>/:
  uv run ../../tools/corner_views.py "<shot>;<shot>..." [--lens 18] [--res 1400x1000]

A shot is either the name of a room.json camera (its own lens and roll are used) or an ad-hoc view
"name:ex,ey,ez:tx,ty,tz" (eye and target in room coordinates: x east, y north, z up; --lens applies).
Writes renders/corner_<name>.png.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roomframe

ap = argparse.ArgumentParser(description="Perspective close-ups of the aligned scan.")
ap.add_argument("shots", help='";"-separated: room.json camera names or "name:ex,ey,ez:tx,ty,tz"')
ap.add_argument("--lens", type=float, default=18, help="lens (mm) for ad-hoc shots")
ap.add_argument("--res", default="1400x1000")
a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])

room = json.loads(Path("room.json").read_text())
shots = {}
parts = a.shots.split(";") if ":" in a.shots else a.shots.replace(",", ";").split(";")  # plain names may use commas
for arg in (p.strip() for p in parts if p.strip()):
    if ":" in arg:
        nm, e_, t_ = arg.split(":")
        shots[nm] = {"eye": [float(v) for v in e_.split(",")], "target": [float(v) for v in t_.split(",")], "lens": a.lens}
    elif arg in room.get("cameras", {}):
        shots[arg] = room["cameras"][arg]
    else:
        sys.exit(f"unknown shot {arg!r}: not a room.json camera ({', '.join(room.get('cameras', {})) or 'none'}) or name:ex,ey,ez:tx,ty,tz")

OX, OY = room["scan"]["alignedOrigin"]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(roomframe.require_file("scan/scan_aligned.glb", "aligned scan")))
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "TEXTURE"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (1, 0, 1)
sc.render.resolution_x, sc.render.resolution_y = (int(v) for v in a.res.split("x"))
sc.render.resolution_percentage = 100
cam_d = bpy.data.cameras.new("cam")
cam_d.clip_start = 0.05
cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
Path("renders").mkdir(exist_ok=True)
for name, shot in shots.items():
    roomframe.apply_camera(cam, shot, (OX, OY, 0))
    sc.render.filepath = f"renders/corner_{name}.png"
    bpy.ops.render.render(write_still=True)
    print("wrote", sc.render.filepath)
