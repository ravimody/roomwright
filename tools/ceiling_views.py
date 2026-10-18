# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1"]
# ///
"""Reflected ceiling plan of the aligned scan: the textured ceiling seen from below (everything above --cut), drawn
north-up and east-right like a plan, cropped to the room with a 0.5 m grid labelled in room coordinates. Use it to
find recessed cans (bright spots), beams, soffits and vents.

Usage, from inside rooms/<room>/:
  uv run ../../tools/ceiling_views.py [--cut 1.45] [--px 150] [--pad 0.3]

Writes renders/ceiling_up.png.
"""

import argparse
import math
import os
import sys
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roomframe

ap = argparse.ArgumentParser(description="Reflected ceiling plan of the aligned scan.")
ap.add_argument("--cut", type=float, default=1.45, help="show the scan above this height (m)")
ap.add_argument("--px", type=int, default=150, help="pixels per metre")
ap.add_argument("--pad", type=float, default=0.3, help="margin around the outline (m)")
a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])

OX, OY = roomframe.origin()  # room origin in aligned-scan coords
x0, y0, x1, y1 = roomframe.extents()
x0, y0, x1, y1 = x0 - a.pad, y0 - a.pad, x1 + a.pad, y1 + a.pad
W, D = x1 - x0, y1 - y0

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(roomframe.require_file("scan/scan_aligned.glb", "aligned scan")))
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "TEXTURE"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (1, 0, 1)
sc.render.resolution_percentage = 100
cam_d = bpy.data.cameras.new("cam")
cam_d.type = "ORTHO"
cam_d.sensor_fit = "HORIZONTAL"  # ortho_scale = the image width, whatever the aspect
cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
# camera at the cut height looking straight up: image right = east, image up = south; flipped top-bottom below
cam.location = (OX + (x0 + x1) / 2, OY + (y0 + y1) / 2, a.cut)
cam.rotation_euler = (math.pi, 0, 0)
cam_d.ortho_scale, cam_d.clip_start, cam_d.clip_end = W, 0.0, 5
sc.render.resolution_x, sc.render.resolution_y = round(W * a.px), round(D * a.px)
Path("renders").mkdir(exist_ok=True)
out = Path("renders/ceiling_up.png")
sc.render.filepath = str(out.resolve())
bpy.ops.render.render(write_still=True)

im = ImageOps.flip(Image.open(out).convert("RGB"))  # north up, east right
d = ImageDraw.Draw(im)
font = roomframe.font(14)
P = lambda x, y: ((x - x0) * a.px, (y1 - y) * a.px)
for k in range(math.ceil(x0 * 2), math.floor(x1 * 2) + 1):
    x = k / 2
    d.line([P(x, y0), P(x, y1)], fill=(0, 0, 0) if k % 2 == 0 else (90, 90, 90), width=2 if k % 2 == 0 else 1)
    if k % 2 == 0:
        d.text((P(x, y1)[0] + 3, 3), f"x {x:g}", fill="black", font=font)
for k in range(math.ceil(y0 * 2), math.floor(y1 * 2) + 1):
    y = k / 2
    d.line([P(x0, y), P(x1, y)], fill=(0, 0, 0) if k % 2 == 0 else (90, 90, 90), width=2 if k % 2 == 0 else 1)
    if k % 2 == 0:
        d.text((3, P(x0, y)[1] + 3), f"y {y:g}", fill="black", font=font)
outline = [P(*p) for p in roomframe.room_json()["outline"]]
d.line(outline + outline[:1], fill=(230, 40, 40), width=2)
im.save(out)
print("wrote", out)
