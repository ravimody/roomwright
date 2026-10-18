# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow"]
# ///
"""Capture a wall's wallpaper from the textured scan as a tileable image for renders.

Run from inside rooms/<room>/:
  uv run ../../tools/wallpaper_from_scan.py <wall: north|south|east|west> <from> <to> <z0> <z1> [out=textures/wallpaper.jpg]

<from>/<to> are positions along the wall in room coordinates (x for north/south walls, y for east/west), z0/z1 the
height band to keep (above the wainscot, below the crown). Pick a stretch with nothing in front of it. The scan is
rendered orthographically, square-on, with flat (emission-like) shading, so the image is the wall's own texture at
a known scale. The left and right edges are cross-faded so the image tiles with a soft seam.

Then in room.json: "materials": {"wall": {"texture": "textures/wallpaper.jpg", "width": <to-from>,
"wainscot": {"height": 0.9, "hex": "#F1EFEA"}}} and render_photoreal maps it onto every wall.
"""

import argparse
import json
import sys
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

import numpy as np
from mathutils import Vector
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roomframe

ap = argparse.ArgumentParser(description="Capture a wall's wallpaper from the textured scan as a tileable image.")
ap.add_argument("wall", choices=["north", "south", "east", "west"])
ap.add_argument("start", type=float, help="from, along the wall (x for north/south walls, y for east/west)")
ap.add_argument("end", type=float, help="to, along the wall")
ap.add_argument("z0", type=float, help="bottom of the band (above the wainscot)")
ap.add_argument("z1", type=float, help="top of the band (below the crown)")
ap.add_argument("out", nargs="?", default="textures/wallpaper.jpg")
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
wall, a, b, z0, z1 = args.wall, min(args.start, args.end), max(args.start, args.end), args.z0, args.z1
out = Path(args.out)
room = json.loads(Path("room.json").read_text())
OX, OY = room["scan"]["alignedOrigin"]
PX_PER_M = 400

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(roomframe.require_file("scan/scan_aligned.glb", "aligned scan")))
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "TEXTURE"
sc.view_settings.view_transform = "Standard"
w, h = b - a, z1 - z0
sc.render.resolution_x, sc.render.resolution_y = int(w * PX_PER_M), int(h * PX_PER_M)
cam_d = bpy.data.cameras.new("cam")
cam_d.type = "ORTHO"
cam_d.ortho_scale = max(w, h)
cam_d.clip_end = 3.0
cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
mid, zc = (a + b) / 2, (z0 + z1) / 2
# stand 1.2 m in front of the wall, looking at it square-on (scan is glTF Y-up: room y = -scan z, room z = scan y)
face = roomframe.wall_line(room, wall, mid)  # this stretch's own wall face (bays, steps and breasts included)
eye = {"north": (mid, face - 1.2), "south": (mid, face + 1.2), "east": (face - 1.2, mid), "west": (face + 1.2, mid)}[wall]
look = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}[wall]
cam_d.clip_start = 0.9  # skip anything more than 30 cm in front of the wall (furniture, plants)
# glTF import converts to Blender Z-up already: room (x, y, z) -> blender (x + OX, y + OY, z)
e = Vector((eye[0] + OX, eye[1] + OY, zc))
t = e + Vector((look[0], look[1], 0))
cam.location = e
cam.rotation_euler = (t - e).to_track_quat("-Z", "Y").to_euler()
tmp = out.with_suffix(".raw.png")
out.parent.mkdir(parents=True, exist_ok=True)
sc.render.filepath = str(tmp.resolve())
bpy.ops.render.render(write_still=True)

img = np.asarray(Image.open(tmp).convert("RGB")).astype(float)
H, W = img.shape[:2]
fade = max(4, W // 12)  # cross-fade the right edge into the left so it tiles
ramp = np.linspace(0, 1, fade)[None, :, None]
img[:, :fade] = img[:, :fade] * ramp + img[:, -fade:] * (1 - ramp)
img = img[:, : W - fade]
Image.fromarray(img.clip(0, 255).astype("uint8")).save(out, quality=92)
tmp.unlink()
print(f"wrote {out}  ({(W - fade) / PX_PER_M:.2f} m wide x {h:.2f} m tall); set materials.wall.width to {(W - fade) / PX_PER_M:.2f}")
