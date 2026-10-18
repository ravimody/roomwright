# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.6", "numpy", "rtree"]
# ///
"""Depth profile along one wall: horizontal rays cast outward from just inside the wall, every 5 cm along it, at
several heights. Prints how far past the wall line each ray hits (metres, + = beyond the wall, - = in front of it).

Reading it: a run of large or "inf" values that stops at a header height is a doorway or opening (its width and
head height come straight off the table); a run a few cm proud of the wall is a closed door, a roller shade or a
picture; "inf" low down only is usually furniture against the wall hiding it. The wall line at each position is
the outline edge facing that way (so stepped walls and bays are measured from their own face), else the outline's
bounding box. The ten probe heights run from 0.3 m to just under the lowest ceiling along the probed stretch
(room.json, slopes included), so a sloped or low ceiling doesn't read as an opening; set them with --heights.

Usage (from inside rooms/<room>/):
  uv run ../../tools/wall_profile.py <north|south|east|west> [from to] [--inset 0.15] [--heights 0.3,0.9,...]
"""

import argparse
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure_common import ceiling_z

from roomframe import extents, room_json, scan_mesh

ap = argparse.ArgumentParser()
ap.add_argument("wall", choices=["north", "south", "east", "west"])
ap.add_argument("range", nargs="*", type=float, help="from / to along the wall (default: the whole wall)")
ap.add_argument("--inset", type=float, default=0.15, help="start the rays this far inside the wall (m)")
ap.add_argument("--step", type=float, default=0.05)
ap.add_argument("--heights", help="comma-separated probe heights in m")
a = ap.parse_args()
if len(a.range) not in (0, 2):
    ap.error("give both ends of the stretch (from to), or neither for the whole wall")

x0, y0, x1, y1 = extents()
c_box, ax, sgn, lo, hi = {
    "north": (y1, "y", 1, x0, x1), "south": (y0, "y", -1, x0, x1),
    "east": (x1, "x", 1, y0, y1), "west": (x0, "x", -1, y0, y1),
}[a.wall]
if len(a.range) == 2:
    lo, hi = sorted(a.range)
# outline edges facing this wall's direction: (along0, along1, line). Outline is CCW, so the outward normal of a->b
# is (dy, -dx).
pts = room_json()["outline"]
faces = []
for (ax_, ay_), (bx_, by_) in zip(pts, pts[1:] + pts[:1]):
    nx_, ny_ = by_ - ay_, -(bx_ - ax_)
    if ax == "y" and abs(ay_ - by_) < 1e-6 and ny_ * sgn > 0:
        faces.append((min(ax_, bx_), max(ax_, bx_), ay_))
    if ax == "x" and abs(ax_ - bx_) < 1e-6 and nx_ * sgn > 0:
        faces.append((min(ay_, by_), max(ay_, by_), ax_))


def wall_line(s):
    """The facing outline edge at position s along the wall (the outermost if several), else the bounding box."""
    hits = [line for f0, f1, line in faces if f0 - 1e-6 <= s <= f1 + 1e-6]
    return (max(hits) if sgn > 0 else min(hits)) if hits else c_box


rmi = trimesh.ray.ray_triangle.RayMeshIntersector(scan_mesh())
ss = np.arange(lo, hi + 1e-6, a.step)
cs = np.array([wall_line(s) for s in ss])
if a.heights:
    Z = [float(v) for v in a.heights.split(",")]
else:  # 0.3 m up to 5 cm under the lowest ceiling over the probe points
    room = room_json()
    zc = min(ceiling_z(room, *((s, c - sgn * a.inset) if ax == "y" else (c - sgn * a.inset, s))) for s, c in zip(ss, cs))
    Z = [round(float(v), 2) for v in np.linspace(0.3, zc - 0.05, 10)]
origins, dirs, cols = [], [], []
for s, c in zip(ss, cs):
    for z in Z:
        origins.append([s, c - sgn * a.inset, z] if ax == "y" else [c - sgn * a.inset, s, z])
        dirs.append([0, sgn, 0] if ax == "y" else [sgn, 0, 0])
        cols.append(c)
loc, idx, _ = rmi.intersects_location(origins, dirs, multiple_hits=False)
depth = np.full(len(origins), np.inf)
if len(idx):
    loc = np.asarray(loc).reshape(-1, 3)
    depth[idx] = sgn * ((loc[:, 1] if ax == "y" else loc[:, 0]) - np.asarray(cols)[idx])
depth = depth.reshape(len(ss), len(Z))
lines = sorted({round(float(c), 3) for c in cs})
print(f"{a.wall} wall at {ax} = {', '.join(f'{c:.2f}' for c in lines)}; depth past the wall line (m) by height z"
      + ("  (stepped: last column is the wall line used)" if len(lines) > 1 else ""))
print(("x" if ax == "y" else "y").rjust(5) + " " + " ".join(f"{z:5.2f}" for z in Z))
for s, row, c in zip(ss, depth, cs):
    print(f"{s:5.2f} " + " ".join("  inf" if np.isinf(v) else f"{v:5.2f}" for v in row) + (f"   {c:.2f}" if len(lines) > 1 else ""))
