# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1"]
# ///
"""Gridded review views of any room's scan, in room coordinates: plan (cut at 1.2 m) + one elevation per side.

Run from inside rooms/<room>/:
  uv run ../../tools/room_views.py

Uses room.json if present, else renders/map/room_draft.json (from map_room.py), for the room origin and extents.
Writes renders/views/{plan,elev_north,elev_south,elev_east,elev_west}.png with a 0.5 m grid labelled in
room coordinates, so positions of doors, windows, soffits and fixtures can be read straight off.
"""

import json
import math
import sys
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

from mathutils import Euler
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roomframe


def _load():
    """room.json unless it is still the untouched template; then the map_room.py draft."""
    rj = Path("room.json")
    if rj.exists():
        r = json.loads(rj.read_text())
        if not r.get("name", "").startswith("<") and r.get("scan", {}).get("alignedOrigin") not in (None, [0, 0]):
            return r
    return json.loads(Path("renders/map/room_draft.json").read_text())


room = _load()
OX, OY = room["scan"]["alignedOrigin"]
xs = [p[0] for p in room["outline"]]
ys = [p[1] for p in room["outline"]]
X0, Y0, RX, RY = min(xs), min(ys), max(xs), max(ys)  # a draft outline may start below 0
TOP = room["ceiling"]["top"] + 0.1
PAD, PX = 0.4, 150
OUT = Path("renders/views")
OUT.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(roomframe.require_file("scan/scan_aligned.glb", "aligned scan")))
for o in bpy.context.scene.objects:  # put the room origin at (0, 0)
    if o.parent is None:
        o.location.x -= OX
        o.location.y -= OY
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.render.resolution_percentage = 100
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "TEXTURE"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (1, 0, 1)
cam_d = bpy.data.cameras.new("cam")
cam_d.type = "ORTHO"
cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam

FONT = roomframe.font(16)


def shot(name, loc, rot, w, h, clip_start, clip_end):
    cam.location, cam.rotation_euler = loc, Euler(rot)
    cam_d.ortho_scale = max(w, h)
    cam_d.sensor_fit = "HORIZONTAL" if w >= h else "VERTICAL"
    cam_d.clip_start, cam_d.clip_end = clip_start, clip_end
    sc.render.resolution_x, sc.render.resolution_y = int(w * PX), int(h * PX)
    sc.render.filepath = str(OUT / f"{name}.png")
    bpy.ops.render.render(write_still=True)
    return Image.open(OUT / f"{name}.png").convert("RGB")


def grid(img, u0, v_top, lab_u, lab_v, flip_u=False):
    """Overlay a 0.5 m grid. Image column = (u - u0) px (or mirrored), row = (v_top - v) px."""
    d = ImageDraw.Draw(img)
    W, H = img.size
    umax = W / PX
    for k in range(-2, int(umax * 2) + 3):
        u = math.floor(u0 * 2) / 2 + k / 2
        x = ((u0 + umax - u) if flip_u else (u - u0)) * PX
        if not 0 <= x <= W:
            continue
        major = abs(u - round(u)) < 1e-6
        d.line([(x, 0), (x, H)], fill=(0, 0, 0) if major else (255, 255, 255), width=2 if major else 1)
        if major:
            d.text((x + 3, H - 22), f"{lab_u}{u:g}", fill=(255, 255, 0), font=FONT, stroke_width=2, stroke_fill=(0, 0, 0))
    for k in range(int(H / PX * 2) + 2):
        v = math.floor(v_top * 2) / 2 - k / 2
        y = (v_top - v) * PX
        if not 0 <= y <= H:
            continue
        major = abs(v - round(v)) < 1e-6
        d.line([(0, y), (W, y)], fill=(0, 0, 0) if major else (255, 255, 255), width=2 if major else 1)
        if major:
            d.text((4, y + 3), f"{lab_v}{v:g}", fill=(255, 255, 0), font=FONT, stroke_width=2, stroke_fill=(0, 0, 0))
    return img


W, D = RX - X0 + 2 * PAD, RY - Y0 + 2 * PAD
CX, CY = (X0 + RX) / 2, (Y0 + RY) / 2
plan = shot("plan", (CX, CY, 1.2), (0, 0, 0), W, D, 0.0, 10)
grid(plan, X0 - PAD, RY + PAD, "x", "y")
dp = ImageDraw.Draw(plan)  # detected/measured outline on top of the scan
op = [((x - X0 + PAD) * PX, (RY + PAD - y) * PX) for x, y in room["outline"]]
dp.line(op + [op[0]], fill=(255, 40, 40), width=3)
plan.save(OUT / "plan.png")

zc = TOP / 2
# elevations: camera at the room centre looking at each wall, so you see the half of the room on that side
for name, rot, w, u0, flip, lab in (
    ("elev_north", (math.pi / 2, 0, 0), W, X0 - PAD, False, "x"),
    ("elev_south", (math.pi / 2, 0, math.pi), W, X0 - PAD, True, "x"),
    ("elev_east", (math.pi / 2, 0, -math.pi / 2), D, Y0 - PAD, True, "y"),  # facing east, image right = south
    ("elev_west", (math.pi / 2, 0, math.pi / 2), D, Y0 - PAD, False, "y"),  # facing west, image right = north
):
    hgt = TOP + 0.2
    img = shot(name, (CX, CY, zc), rot, w, hgt, 0.0, 10)
    grid(img, u0, zc + hgt / 2, lab, "z", flip).save(OUT / f"{name}.png")  # image top row = z at zc + hgt/2
print("wrote", sorted(p.name for p in OUT.glob("*.png")))
