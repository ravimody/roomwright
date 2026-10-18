# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.6", "numpy", "pillow>=10.1", "scipy"]
# ///
"""Horizontal cross-sections of the whole scan (room frame, 0.25 m grid) to read wall lines and item footprints.

Run from inside rooms/<room>/:
  uv run ../../tools/sections.py [--heights 0.15,0.6,1.2,<ceiling-0.3>] [--out renders/sections.png]

The canvas covers the room outline plus 0.5 m (to show what the scan saw through openings). Default heights: floor
clutter, seat, counter height, and just under the lowest ceiling level (above most furniture, below crown moulding).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure_common import ceiling_levels, extents

from roomframe import font, scan_mesh

room = json.loads(Path("room.json").read_text())
ap = argparse.ArgumentParser()
ap.add_argument("--heights", help="comma-separated cut heights in m")
ap.add_argument("--out", default="renders/sections.png")
a = ap.parse_args()
lo_c, _ = ceiling_levels(room)
Z = [float(v) for v in a.heights.split(",")] if a.heights else [0.15, 0.6, 1.2, round(lo_c - 0.3, 2)]
COLS = [(0, 160, 0), (0, 0, 255), (220, 0, 0), (255, 140, 0), (150, 0, 150), (120, 80, 0)]

g = scan_mesh()
ex0, ey0, ex1, ey1 = extents(room)
PX, X0, Y0 = 150, ex0 - 0.5, ey0 - 0.5
W, H = ex1 - ex0 + 1.0, ey1 - ey0 + 1.0
im = Image.new("RGB", (int(W * PX), int(H * PX) + 30), "white")
d = ImageDraw.Draw(im)
f = font(14)
P = lambda x, y: ((x - X0) * PX, (Y0 + H - y) * PX)
for i in range(int(W * 4) + 1):
    x = X0 + i / 4
    major = abs(x - round(x)) < 1e-6
    d.line([P(x, Y0), P(x, Y0 + H)], fill=(120, 120, 120) if major else (200, 200, 200))
    if major:
        d.text((P(x, 0)[0] + 2, 4), f"x{round(x):g}", fill="black", font=f)
for j in range(int(H * 4) + 1):
    y = Y0 + j / 4
    major = abs(y - round(y)) < 1e-6
    d.line([P(X0, y), P(X0 + W, y)], fill=(120, 120, 120) if major else (200, 200, 200))
    if major:
        d.text((4, P(0, y)[1] + 2), f"y{round(y):g}", fill="black", font=f)
d.polygon([P(*p) for p in room["outline"]], outline=(170, 170, 170))
for z, col in zip(Z, COLS):
    s = g.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if s is None:
        continue
    for e in s.entities:
        d.line([P(p[0], p[1]) for p in s.vertices[e.points]], fill=col, width=2)
d.text((10, im.height - 24), "  ".join(f"z {z:g}" for z in Z) + "   (colours in that order: green, blue, red, orange, purple, brown)", fill="black", font=f)
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
im.save(a.out)
print("wrote", a.out)
