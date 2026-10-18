# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh", "numpy", "pillow", "scipy", "networkx", "shapely", "rtree"]
# ///
"""Find furniture in a room scan and write a draft layout: one footprint per piece, with size, rotation and height.

Run from inside rooms/<room>/ after map_room.py and once room.json has the outline and scan.alignedOrigin:
  uv run ../../tools/detect_furniture.py [--min-area 0.04] [--wall-band 0.06]

Writes:
  renders/map/furniture_draft.json   {"items": [{id, x, y, w, d, h, rot, area}]} in room coordinates
  renders/map/furniture.png          plan of the scan with the detected footprints and their sizes

How it works: everything between 0.12 m and 1.9 m above the floor (furniture, not floor or ceiling) is rasterised
into an occupancy grid inside the room outline, minus a thin band along the walls (wallpaper, baseboards,
radiators). Connected blobs are pieces; each gets its minimum rotated rectangle and its tallest point. Tables
read as their top plus chairs, so expect to merge or split a few by eye. This replaces tracing every piece by
hand from the plan render: map each blob to a catalog type and adjust.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import MultiPoint, Point, Polygon

ap = argparse.ArgumentParser()
ap.add_argument("--min-area", type=float, default=0.04, help="ignore blobs smaller than this (m2)")
ap.add_argument("--wall-band", type=float, default=0.06, help="ignore this much along each wall (m)")
ap.add_argument("--cell", type=float, default=0.03)
args = ap.parse_args()
CELL = args.cell
OUT = Path("renders/map")
OUT.mkdir(parents=True, exist_ok=True)

room = json.loads(Path("room.json").read_text())
ox, oy = room["scan"]["alignedOrigin"]
outline = Polygon(room["outline"])
inner = outline.buffer(-args.wall_band)

g = trimesh.load("scan/scan_aligned.glb").to_geometry()
V = g.vertices
g.vertices = np.c_[V[:, 0] - ox, -V[:, 2] - oy, V[:, 1]]  # glTF Y-up -> Z-up, then room coordinates

# sample points on faces in the furniture band (area-weighted, so big flat tops and thin legs both register)
pts, fi = trimesh.sample.sample_surface(g, 400000)
band = (pts[:, 2] > 0.12) & (pts[:, 2] < 1.9)
pts = pts[band]
minx, miny, maxx, maxy = outline.bounds
nx, ny = int((maxx - minx) / CELL) + 1, int((maxy - miny) / CELL) + 1
i = ((pts[:, 0] - minx) / CELL).astype(int)
j = ((pts[:, 1] - miny) / CELL).astype(int)
ok = (i >= 0) & (i < nx) & (j >= 0) & (j < ny)
occ = np.zeros((nx, ny), int)
np.add.at(occ, (i[ok], j[ok]), 1)
top = np.zeros((nx, ny))
np.maximum.at(top, (i[ok], j[ok]), pts[ok, 2])

xs = minx + (np.arange(nx) + 0.5) * CELL
ys = miny + (np.arange(ny) + 0.5) * CELL
gx, gy = np.meshgrid(xs, ys, indexing="ij")
inside = np.vectorize(lambda x, y: inner.contains(Point(x, y)))(gx, gy)
mask = (occ >= 2) & inside
mask = ndimage.binary_closing(mask, iterations=2)
mask = ndimage.binary_opening(mask, iterations=1)
lab, n = ndimage.label(mask)

items = []
for k in range(1, n + 1):
    blob = lab == k
    area = blob.sum() * CELL * CELL
    if area < args.min_area:
        continue
    bi, bj = np.nonzero(blob)
    rect = MultiPoint(list(zip(xs[bi], ys[bj]))).minimum_rotated_rectangle
    c = list(rect.exterior.coords)[:4]
    e1 = np.subtract(c[1], c[0])
    e2 = np.subtract(c[2], c[1])
    l1, l2 = np.hypot(*e1) + CELL, np.hypot(*e2) + CELL
    long_e = e1 if l1 >= l2 else e2
    ang = (np.degrees(np.arctan2(long_e[1], long_e[0])) % 180)
    ang = round(ang / 5) * 5 % 180
    if min(ang, 180 - ang) <= 8 or abs(ang - 90) <= 8:  # near-axis blobs are axis-aligned pieces (scan noise)
        ang = 90 if abs(ang - 90) <= 8 else 0
    items.append({
        "id": f"blob-{len(items) + 1}",
        "x": round(rect.centroid.x, 3), "y": round(rect.centroid.y, 3),
        "w": round(max(l1, l2), 2), "d": round(min(l1, l2), 2),
        "h": round(float(np.percentile(top[blob], 95)), 2),
        "rot": 0 if ang in (0, 180) else (90 if ang == 90 else ang),
        "area": round(area, 2),
    })
items.sort(key=lambda it: -it["area"])
for k, it in enumerate(items, 1):
    it["id"] = f"blob-{k}"
(OUT / "furniture_draft.json").write_text(json.dumps({"items": items}, indent=2) + "\n")

# review image
S = 120  # px per m
img = Image.new("RGB", (int((maxx - minx) * S) + 40, int((maxy - miny) * S) + 40), "white")
d = ImageDraw.Draw(img)
P = lambda x, y: (20 + (x - minx) * S, 20 + (maxy - y) * S)
for a, b in zip(room["outline"], room["outline"][1:] + room["outline"][:1]):
    d.line([P(*a), P(*b)], fill=(0, 0, 0), width=3)
for ii, jj in zip(*np.nonzero(mask)):
    x, y = xs[ii], ys[jj]
    d.rectangle([P(x - CELL / 2, y + CELL / 2), P(x + CELL / 2, y - CELL / 2)], fill=(200, 200, 230))
for it in items:
    t = np.radians(it["rot"])
    ux, uy = np.cos(t) * it["w"] / 2, np.sin(t) * it["w"] / 2
    vx, vy = -np.sin(t) * it["d"] / 2, np.cos(t) * it["d"] / 2
    corners = [(it["x"] + sx * ux + sy * vx, it["y"] + sx * uy + sy * vy) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    d.polygon([P(*q) for q in corners], outline=(200, 30, 30), width=2)
    d.text(P(it["x"], it["y"]), f'{it["id"]}\n{it["w"]:.2f}x{it["d"]:.2f} h{it["h"]:.2f}', fill=(120, 0, 0))
img.save(OUT / "furniture.png")
print(f"{len(items)} pieces ->", OUT / "furniture_draft.json")
for it in items:
    print(f'  {it["id"]}: ({it["x"]}, {it["y"]}) {it["w"]} x {it["d"]} m, h {it["h"]}, rot {it["rot"]}')
