# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.6", "numpy", "pillow>=10.1", "scipy"]
# ///
"""Zoomed cross-sections of one room region: horizontal cuts at several heights plus two vertical cuts.

Run from inside rooms/<room>/:
  uv run ../../tools/region_sections.py x0 y0 x1 y1 out.png [xcut] [ycut] [--heights 0.3,1.0,...]

Default cut heights run from 0.3 m to just under the region's ceiling (from room.json, slopes included); the vertical
cuts (at xcut, looking east, and ycut, looking north; default the region's centre lines) reach 0.2 m above the
highest ceiling in the region, so soffits, crown and slopes show.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure_common import ceiling_z

from roomframe import font, scan_mesh

ap = argparse.ArgumentParser()
for k in ("x0", "y0", "x1", "y1"):
    ap.add_argument(k, type=float)
ap.add_argument("out")
ap.add_argument("xcut", type=float, nargs="?")
ap.add_argument("ycut", type=float, nargs="?")
ap.add_argument("--heights", help="comma-separated plan cut heights in m")
a = ap.parse_args()
x0, x1 = sorted((a.x0, a.x1))
y0, y1 = sorted((a.y0, a.y1))
if x1 - x0 < 0.1 or y1 - y0 < 0.1:
    sys.exit("the region must be at least 0.1 m in x and y")
xcut = a.xcut if a.xcut is not None else (x0 + x1) / 2
ycut = a.ycut if a.ycut is not None else (y0 + y1) / 2

room = json.loads(Path("room.json").read_text())
cz = [ceiling_z(room, x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * j / 8) for i in range(9) for j in range(9)]
c_lo, c_hi = min(cz), max(cz)
Z = [float(v) for v in a.heights.split(",")] if a.heights else [0.3, 1.0, 1.5, round(c_lo - 0.5, 2), round(c_lo - 0.3, 2), round(c_lo - 0.12, 2)]
Z = sorted({z for z in Z if z > 0})
H = c_hi + 0.2
g = scan_mesh()
PX = 400
f = font(13)
cols = [(0, 150, 0), (0, 0, 255), (200, 0, 200), (220, 0, 0), (255, 140, 0), (120, 80, 0), (0, 140, 140), (90, 90, 90)]


def panel(w, h, title):
    im = Image.new("RGB", (int(w * PX) + 60, int(h * PX) + 44), "white")
    ImageDraw.Draw(im).text((4, 2), title, fill="black", font=f)
    return im


def draw_grid(d, ox, oy, w, h, lx, ly):
    for i in range(int(w * 10) + 1):
        x = 50 + i * PX / 10
        d.line([(x, 20), (x, 20 + h * PX)], fill=(225, 225, 225) if i % 5 else (150, 150, 150))
        if i % 5 == 0:
            d.text((x + 2, 20 + h * PX + 4), f"{lx}{ox + i / 10:.1f}", fill="black", font=f)
    for j in range(int(h * 10) + 1):
        y = 20 + h * PX - j * PX / 10
        d.line([(50, y), (50 + w * PX, y)], fill=(225, 225, 225) if j % 5 else (150, 150, 150))
        if j % 5 == 0:
            d.text((2, y - 6), f"{ly}{oy + j / 10:.1f}", fill="black", font=f)


w, h = x1 - x0, y1 - y0
plan = panel(w, h, "plan cuts: " + "  ".join(f"z{z:g}" for z in Z) + " (green, blue, purple, red, orange, brown...)")
d = ImageDraw.Draw(plan)
draw_grid(d, x0, y0, w, h, "x", "y")
P = lambda x, y: (50 + (x - x0) * PX, 20 + (y1 - y) * PX)
for z, col in zip(Z, cols):
    s = g.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if s is None:
        continue
    for e in s.entities:
        pts = s.vertices[e.points]
        if ((pts[:, 0] > x0 - 0.5) & (pts[:, 0] < x1 + 0.5) & (pts[:, 1] > y0 - 0.5) & (pts[:, 1] < y1 + 0.5)).any():
            d.line([P(p[0], p[1]) for p in pts], fill=col, width=2)


def vcut(axis_val, normal, lo, hi, lab):
    im = panel(hi - lo, H, f"vertical cut {'x' if normal[0] else 'y'}={axis_val:.2f} (looking {'east' if normal[0] else 'north'})")
    dd = ImageDraw.Draw(im)
    draw_grid(dd, lo, 0, hi - lo, H, lab, "z")
    s = g.section(plane_origin=[axis_val if normal[0] else 0, axis_val if normal[1] else 0, 0], plane_normal=normal)
    k = 1 if normal[0] else 0
    if s is not None:
        for e in s.entities:
            pts = s.vertices[e.points]
            dd.line([(50 + (p[k] - lo) * PX, 20 + (H - p[2]) * PX) for p in pts], fill=(0, 0, 0), width=2)
    return im


va = vcut(xcut, [1, 0, 0], y0, y1, "y")
vb = vcut(ycut, [0, 1, 0], x0, x1, "x")
W = max(plan.width, va.width + vb.width)
canvas = Image.new("RGB", (W, plan.height + max(va.height, vb.height)), "white")
canvas.paste(plan, (0, 0))
canvas.paste(va, (0, plan.height))
canvas.paste(vb, (va.width, plan.height))
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
canvas.save(a.out)
print("wrote", a.out)
