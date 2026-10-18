# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.6", "numpy", "pillow>=10.1", "scipy", "rtree"]
# ///
"""Ceiling check: how well room.json's ceiling (top, downstands, slopes) matches the scan, on a 5 cm grid.

Run from inside rooms/<room>/:
  uv run ../../tools/ceiling_compare.py [--layout as-scanned] [--step 0.05] [--out renders/ceiling_check]

For every grid cell inside the outline it casts a ray straight up from 0.5 m below the modelled ceiling and records the
first scan hit, so sloped ceilings, soffits and stair undersides are all measured (normal-filtered sampling drops
slopes). Cells under layout items that reach within 0.5 m of the ceiling (wardrobes, a sauna, ceiling fans, chandeliers)
are left out, as are scan holes and the ring of cells along the walls (wall faces, crown moulding). Prints the share of cells within 3 cm and 5 cm, then every mismatch region over
0.04 m2 (where, how big, scan higher or lower), which is what to fix or explain. Target: > 90% within 3 cm.

Writes <out>.png (scan | model | difference, same colour scale, north up, 1 m grid) and <out>.json (grid origin and
step, stats, regions, and the measured heights as rows south to north).
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_common import ceiling_levels, ceiling_z, footprint, grid, height_color, layout_items, point_in_poly

from roomframe import font, scan_mesh

ap = argparse.ArgumentParser()
ap.add_argument("--layout", help="layout whose tall and ceiling-hung items are left out (default: as-scanned if present)")
ap.add_argument("--step", type=float, default=0.05)
ap.add_argument("--probe", type=float, default=0.5, help="rays start this far below the modelled ceiling (m)")
ap.add_argument("--out", default="renders/ceiling_check")
a = ap.parse_args()

room = json.loads(Path("room.json").read_text())
xs, ys, (gx0, gy0) = grid(room, a.step)
nx, ny = len(xs), len(ys)
inside = np.array([[point_in_poly((x, y), room["outline"]) for x in xs] for y in ys])  # rows = y (south to north)
model = np.array([[ceiling_z(room, x, y) if inside[j, i] else np.nan for i, x in enumerate(xs)] for j, y in enumerate(ys)])

# cells under items that reach into the probe range (top within `probe` of the ceiling, or hung from it)
excluded = np.zeros_like(inside)
layout = a.layout or ("as-scanned" if Path("layouts/as-scanned.json").exists() else None)
if layout:
    items, _ = layout_items(layout)
    for s in items:
        if s.get("floorLayer"):
            continue
        hung = s.get("ceiling") is not None or (s.get("hang") == "ceiling" and not s.get("z"))  # hangs from the ceiling over it
        top = s.get("ceiling") if s.get("ceiling") is not None else 1e9 if hung else (s.get("z") or 0) + s["h"]
        poly = footprint(s)
        px, py = [p[0] for p in poly], [p[1] for p in poly]
        i0, i1 = np.searchsorted(xs, min(px) - 0.05), np.searchsorted(xs, max(px) + 0.05)
        j0, j1 = np.searchsorted(ys, min(py) - 0.05), np.searchsorted(ys, max(py) + 0.05)
        for j in range(j0, min(j1, ny)):
            for i in range(i0, min(i1, nx)):
                if inside[j, i] and top > model[j, i] - a.probe and point_in_poly((xs[i], ys[j]), poly):
                    excluded[j, i] = True
    excluded = ndimage.binary_dilation(excluded, iterations=1) & inside

# ray-cast the scan
g = scan_mesh()
jj, ii = np.nonzero(inside)
org = np.c_[np.array(xs)[ii], np.array(ys)[jj], model[jj, ii] - a.probe]
loc, ridx, _ = g.ray.intersects_location(org, np.tile([0, 0, 1.0], (len(org), 1)), multiple_hits=False)
scan = np.full((ny, nx), np.nan)
if len(ridx):
    scan[jj[ridx], ii[ridx]] = np.asarray(loc).reshape(-1, 3)[:, 2]
scan[scan > model + 0.6] = np.nan  # through a hole into the floor above or a neighbouring room: not judged

diff = scan - model
# the ring of cells along the outline straddles the wall line (wall faces, crown moulding, curtains): not judged
edge = inside & ~ndimage.binary_erosion(inside, iterations=max(1, round(0.05 / a.step)))
excluded |= edge
judged = np.isfinite(diff) & ~excluded
n = int(judged.sum())
w3 = float((np.abs(diff[judged]) < 0.03).mean() * 100) if n else 0.0
w5 = float((np.abs(diff[judged]) < 0.05).mean() * 100) if n else 0.0
mean = float(np.abs(diff[judged]).mean() * 100) if n else 0.0
holes = int((inside & ~np.isfinite(scan) & ~excluded).sum())
print(f"ceiling: {n} cells judged ({a.step * 100:.0f} cm), within 3 cm {w3:.1f}%, within 5 cm {w5:.1f}%, mean |diff| {mean:.1f} cm"
      f"  [not judged: {int((excluded & ~edge).sum())} cells under tall/hung items{f' ({layout})' if layout else ''}, "
      f"{int(edge.sum())} along the walls, {holes} scan holes]")

# mismatch regions (> 5 cm), largest first
bad = judged & (np.abs(np.nan_to_num(diff)) >= 0.05)
lab, nl = ndimage.label(bad)
regions = []
for q in range(1, nl + 1):
    cells = np.argwhere(lab == q)
    area = len(cells) * a.step * a.step
    if area < 0.04:
        continue
    d = diff[lab == q]
    (j0, i0), (j1, i1) = cells.min(0), cells.max(0)
    regions.append({"x": [round(gx0 + i0 * a.step, 2), round(gx0 + (i1 + 1) * a.step, 2)], "y": [round(gy0 + j0 * a.step, 2), round(gy0 + (j1 + 1) * a.step, 2)],
                    "area": round(area, 2), "meanDiff": round(float(np.mean(d)), 3), "scan": "higher" if np.mean(d) > 0 else "lower"})
regions.sort(key=lambda r: -r["area"])
for r in regions[:15]:
    print(f"  CHECK x {r['x'][0]:.2f}-{r['x'][1]:.2f}  y {r['y'][0]:.2f}-{r['y'][1]:.2f}  {r['area']:.2f} m2  scan {r['scan']} by {abs(r['meanDiff']) * 100:.0f} cm")
if len(regions) > 15:
    print(f"  ... {len(regions) - 15} smaller regions in the JSON")

# image: three panels, north up
lo, hi = ceiling_levels(room)
lo, hi = lo - 0.05, hi + 0.05
S = max(3, min(10, round(1100 / max(nx, ny))))
W, H = nx * S, ny * S
f, fb = font(14), font(17)
img = Image.new("RGB", (W * 3 + 160, H + 130), "white")
dr = ImageDraw.Draw(img)


def diff_col(dz):
    if np.isnan(dz):
        return (245, 245, 245)
    return (225, 235, 225) if abs(dz) < 0.03 else (250, 200, 120) if abs(dz) < 0.08 else (210, 50, 50)


panels = [("SCAN (ray-cast up)", scan, lambda z: height_color(z, lo, hi)), ("MODEL (room.json)", model, lambda z: height_color(z, lo, hi)),
          ("DIFFERENCE  green <3 cm  orange 3-8  red >8  grey = not judged", diff, diff_col)]
for p, (title, arr, fn) in enumerate(panels):
    ox, oy = 40 + p * (W + 40), 40
    dr.text((ox, 12), title, fill="black", font=fb)
    for j in range(ny):
        for i in range(nx):
            if not inside[j, i]:
                continue
            c = (200, 200, 200) if (p == 2 and excluded[j, i]) else fn(arr[j, i])
            y = ny - 1 - j
            dr.rectangle([ox + i * S, oy + y * S, ox + (i + 1) * S - 1, oy + (y + 1) * S - 1], fill=c)
    for k in range(int(np.floor(gx0)), int(np.ceil(gx0 + nx * a.step)) + 1):
        X = ox + (k - gx0) / a.step * S
        if ox <= X <= ox + W:
            dr.line([X, oy, X, oy + H], fill=(120, 120, 120))
            dr.text((X + 2, oy + H + 4), f"x{k}", fill="black", font=f)
    for k in range(int(np.floor(gy0)), int(np.ceil(gy0 + ny * a.step)) + 1):
        Y = oy + H - (k - gy0) / a.step * S
        if oy <= Y <= oy + H:
            dr.line([ox, Y, ox + W, Y], fill=(120, 120, 120))
            dr.text((ox - 24, Y - 8), f"y{k}", fill="black", font=f)
ly = H + 80
for k, z in enumerate(np.linspace(lo, hi, 8)):
    dr.rectangle([40 + k * 100, ly, 70 + k * 100, ly + 16], fill=height_color(z, lo, hi))
    dr.text((74 + k * 100, ly), f"{z:.2f} m", fill="black", font=f)
dr.text((40, ly + 24), f"within 3 cm: {w3:.1f}% of {n} cells   within 5 cm: {w5:.1f}%   mean |diff| {mean:.1f} cm", fill="black", font=fb)
out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out.with_suffix(".png"))
res = {"origin": [round(gx0, 4), round(gy0, 4)], "step": a.step, "nx": nx, "ny": ny, "layout": layout,
       "judged": n, "within3cm": round(w3, 1), "within5cm": round(w5, 1), "meanDiffCm": round(mean, 1), "regions": regions,
       "scan": [[None if not np.isfinite(v) else round(float(v), 3) for v in row] for row in scan]}
out.with_suffix(".json").write_text(json.dumps(res) + "\n")
print(f"wrote {out.with_suffix('.png')} and {out.with_suffix('.json')}")
