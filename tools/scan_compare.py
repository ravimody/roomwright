# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1"]
# ///
"""Same-camera check: render the textured scan from each room.json camera and put it next to a photoreal render.

Run from inside rooms/<room>/:
  uv run ../../tools/scan_compare.py <photoreal-folder> [views]
  e.g. ... scan_compare.py today-day view_a,view_b   (a render folder name, not a path)

Writes renders/scan_compare/scan_<view>.png and renders/scan_compare/side_<view>.jpg (scan left, model right).
Use it after every material/lighting/geometry change: colours, doors, built-ins and furniture positions should match.
Cameras (eye, target, lens, roll) are applied exactly as render_photoreal.py does (roomframe.apply_camera).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

from PIL import Image, ImageDraw

import roomframe

ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
ap.add_argument("folder", help="renders/photoreal/<folder> to compare against")
ap.add_argument("views", nargs="?", help="comma-separated room.json cameras (default: all)")
a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
folder = a.folder
room = json.loads(Path("room.json").read_text())
views = a.views.split(",") if a.views else list(room.get("cameras", {}))
roomframe.check_views(room, views)
OX, OY = room["scan"]["alignedOrigin"]
OUT = Path("renders/scan_compare")
OUT.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(roomframe.require_file("scan/scan_aligned.glb", "aligned scan")))
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "TEXTURE"
sc.render.resolution_percentage = 100
sc.world = bpy.data.worlds.new("w")
sc.world.color = (1, 0, 1)
cam_d = bpy.data.cameras.new("cam")
cam_d.clip_start = 0.05
cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
font = roomframe.font(28)
for v in views:
    model = Path(f"renders/photoreal/{folder}/{v}.png")
    w, h = Image.open(model).size if model.exists() else (1400, 875)  # no render yet: scan view only
    sc.render.resolution_x, sc.render.resolution_y = w, h
    roomframe.apply_camera(cam, room["cameras"][v], (OX, OY, 0))
    sc.render.filepath = str(OUT / f"scan_{v}.png")
    bpy.ops.render.render(write_still=True)
    if not model.exists():
        print("wrote", OUT / f"scan_{v}.png", "(no model render to compare)")
        continue
    a_, b = Image.open(OUT / f"scan_{v}.png").convert("RGB"), Image.open(model).convert("RGB")
    o = Image.new("RGB", (w * 2 + 20, h + 50), "white")
    o.paste(a_, (0, 50))
    o.paste(b, (w + 20, 50))
    d = ImageDraw.Draw(o)
    d.text((10, 12), "REAL ROOM (scan)", fill="black", font=font)
    d.text((w + 30, 12), f"MODEL ({folder})", fill="black", font=font)
    o.save(OUT / f"side_{v}.jpg", quality=86)
    print("wrote", OUT / f"side_{v}.jpg")
