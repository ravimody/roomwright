# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh", "numpy", "pillow", "scipy", "networkx", "shapely", "rtree"]
# ///
"""Automatically map a room from its aligned scan: outline, ceiling levels, openings. Clutter-robust.

Run from inside rooms/<room>/ after align_and_render.py (needs scan/scan_aligned.glb, scan/alignment.json):
  uv run ../../tools/map_room.py [--seed X Y] [--cell 0.05] [--out renders/map]

Writes:
  renders/map/room_draft.json   draft room.json (outline, wallHeight, ceiling, openings, scan transform)
  renders/map/review.png        plan of the scan with the detected outline, walls and openings overlaid
  renders/map/ceiling.png       ceiling height map with detected levels

Strategy:
  * Furniture and clutter live below ~1.6 m, so nothing below that height is used for the outline.
  * The ceiling is the cleanest surface: cast rays straight up on a grid (catches slanted ceilings too).
  * Neighbouring rooms seen through openings also have ceiling; they are cut off by the strip of wall
    between door-head height and the ceiling (headers/soffits), found as vertical surfaces in that band.
  * Wall positions are refined from profiles just under the ceiling (ceiling - 0.33 to - 0.13 m, below crown
    moulding): real walls reach that band; bookcases and cabinets don't.
  * Openings are gaps in the mid-height walls; their head is the lowest surface above 1.5 m inside the wall
    thickness (the header).
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy import ndimage

ap = argparse.ArgumentParser()
ap.add_argument("--seed", nargs=2, type=float, help="a point inside the room (aligned-scan x y); default: densest ceiling area")
ap.add_argument("--cell", type=float, default=0.05)
ap.add_argument("--out", default="renders/map", help="output folder")
args = ap.parse_args()
CELL = args.cell
OUT = Path(args.out)
OUT.mkdir(parents=True, exist_ok=True)

# ---------- load (aligned scan, glTF Y-up -> Z-up; still in aligned coords, origin applied at the end) ----------
g = trimesh.load("scan/scan_aligned.glb").to_geometry()
V = g.vertices
g.vertices = np.c_[V[:, 0], -V[:, 2], V[:, 1]]
n, area, cen = g.face_normals, g.area_faces, g.triangles_center
lo, hi = g.bounds
x0, y0 = lo[0] - 0.2, lo[1] - 0.2
nx, ny = int((hi[0] - x0 + 0.2) / CELL) + 1, int((hi[1] - y0 + 0.2) / CELL) + 1
xs = x0 + (np.arange(nx) + 0.5) * CELL
ys = y0 + (np.arange(ny) + 0.5) * CELL
to_ij = lambda x, y: (np.floor((np.asarray(x) - x0) / CELL).astype(int), np.floor((np.asarray(y) - y0) / CELL).astype(int))

# ---------- 1. ceiling height map (rays straight up from 1.6 m) ----------
gx, gy = np.meshgrid(xs, ys, indexing="ij")
org = np.c_[gx.ravel(), gy.ravel(), np.full(gx.size, 1.6)]
loc, ridx, _ = g.ray.intersects_location(org, np.tile([0, 0, 1.0], (len(org), 1)), multiple_hits=False)
H = np.full(gx.size, np.nan)
H[ridx] = loc[:, 2]
H = H.reshape(gx.shape)

# ceiling levels = peaks of the height histogram (ignoring a 5 cm band of noise)
valid = np.isfinite(H) & (H > 1.9) & (H < 4.0)
hist, edges = np.histogram(H[valid], bins=np.arange(1.9, 4.0, 0.02))
sm = np.convolve(hist, [1, 2, 3, 2, 1], "same")
peaks = [i for i in range(1, len(sm) - 1) if sm[i] >= sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > 0.03 * sm.max()]
levels = sorted({round(edges[i] + 0.01, 2) for i in peaks})
main_ceiling = round(edges[int(np.argmax(sm))] + 0.01, 2)
print("ceiling levels (m):", levels, "main:", main_ceiling)

# ---------- 2. header band: vertical surfaces between door-head height and the ceiling ----------
# Above door heads but above typical tall furniture too (bookcases ~2.2 m): walls reach the ceiling, furniture doesn't.
band_lo, band_hi = max(2.05, main_ceiling - 0.25), main_ceiling - 0.04
vert = np.abs(n[:, 2]) < 0.35
m = vert & (cen[:, 2] > band_lo) & (cen[:, 2] < band_hi)
i, j = to_ij(cen[m, 0], cen[m, 1])
ok = (i >= 0) & (i < nx) & (j >= 0) & (j < ny)
header = np.zeros((nx, ny), bool)
header[i[ok], j[ok]] = True
header = ndimage.binary_dilation(header, iterations=1)

# also mid-height walls (1.6 m to the header band): they bound the room except at openings
m2 = vert & (cen[:, 2] > 1.6) & (cen[:, 2] < band_lo)
i2, j2 = to_ij(cen[m2, 0], cen[m2, 1])
ok2 = (i2 >= 0) & (i2 < nx) & (j2 >= 0) & (j2 < ny)
midwall = np.zeros((nx, ny), bool)
midwall[i2[ok2], j2[ok2]] = True

# door band: walls between 1.2 and 1.85 m, below any door head (~2.0 m). A doorway or cased opening is a gap here;
# its header (above ~2.0 m) would hide it in the mid-height band above.
m3 = vert & (cen[:, 2] > 1.2) & (cen[:, 2] < 1.85)
i3, j3 = to_ij(cen[m3, 0], cen[m3, 1])
ok3 = (i3 >= 0) & (i3 < nx) & (j3 >= 0) & (j3 < ny)
doorband = np.zeros((nx, ny), bool)
doorband[i3[ok3], j3[ok3]] = True

# ---------- 3. room mask: flood fill the ceiling area from a seed, blocked by the header band ----------
ceil_ok = np.isfinite(H) & (band_lo < H)
free = ceil_ok & ~header
lab, nlab = ndimage.label(free)
if nlab == 0:
    sys.exit("no ceiling found above the header band: is the scan aligned (floor at z = 0) and does it include the ceiling?")


def nearest_cell(mask, i, j):
    """The cell of mask nearest to (i, j)."""
    _, (ii, jj) = ndimage.distance_transform_edt(~mask, return_indices=True)
    return int(ii[i, j]), int(jj[i, j])


if args.seed:
    si, sj = (int(v) for v in to_ij(*args.seed))
    if not (0 <= si < nx and 0 <= sj < ny):
        sys.exit(f"--seed {args.seed} is outside the scan (x {x0:.2f}..{x0 + nx * CELL:.2f}, y {y0:.2f}..{y0 + ny * CELL:.2f})")
    if not lab[si, sj]:  # on a header, a scan hole or furniture: use the nearest open ceiling
        si, sj = nearest_cell(free, si, sj)
        print(f"--seed moved to the nearest open ceiling at ({xs[si]:.2f}, {ys[sj]:.2f})")
else:  # the largest free component, at its cell nearest the centre (an L-shaped room's centre can fall outside it)
    big = lab == np.argmax(ndimage.sum(free, lab, range(1, nlab + 1))) + 1
    ci, cj = ndimage.center_of_mass(big)
    si, sj = nearest_cell(big, int(ci), int(cj))
room = lab == lab[si, sj]
room = ndimage.binary_closing(room, iterations=3)
room = ndimage.binary_fill_holes(room)
room = ndimage.binary_opening(room, iterations=4)  # drop narrow leaks through openings (< ~40 cm)
lab_r, nr_ = ndimage.label(room)
room = lab_r == lab_r[si, sj] if lab_r[si, sj] else room
# Patchy ceiling scans (dark or glossy ceilings, a chandelier) leave holes the flood fill can't cross, so part of
# the room drops out. If the header band (plus mid-height walls) closes into a ring around the seed, everything
# inside it is room too. Close progressively larger gaps in the ring (scan holes, then full-height cased openings,
# up to ~1.6 m at 5 cm cells) until it does; only the component holding the seed is added.
for it in (2, 4, 6, 8, 12, 16):
    ring = ndimage.binary_closing(header | midwall, iterations=it)
    inside = ndimage.binary_fill_holes(ring) & ~ring
    lab_i, _ = ndimage.label(inside)
    if lab_i[si, sj]:
        enclosed = lab_i == lab_i[si, sj]
        if enclosed.sum() > room.sum() * 1.1:
            print(f"ceiling had gaps: added {(enclosed & ~room).sum() * CELL * CELL:.1f} m2 enclosed by the walls")
            room = ndimage.binary_opening(room | enclosed, iterations=2)
        break
print(f"room area ~{room.sum() * CELL * CELL:.1f} m2")

# ---------- 4. rectilinear outline from the mask ----------
def mask_outline(mask):
    """Trace the boundary of a grid mask as an axis-aligned polygon (CCW, aligned-scan coords)."""
    import shapely.geometry as sg
    import shapely.ops as so

    boxes = [sg.box(x0 + a * CELL, y0 + b * CELL, x0 + (a + 1) * CELL, y0 + (b + 1) * CELL) for a, b in zip(*np.nonzero(mask))]
    poly = so.unary_union(boxes)
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda p: p.area)
    poly = sg.Polygon(poly.exterior).simplify(CELL * 0.5)
    return poly


poly = mask_outline(room)
pts = list(poly.exterior.coords)[:-1]
# make it strictly rectilinear: snap near-axis edges, drop jogs shorter than 15 cm
def rectify(pts, min_jog=0.15):
    out = []
    for p in pts:
        if out and abs(p[0] - out[-1][0]) < 1e-6 and abs(p[1] - out[-1][1]) < 1e-6:
            continue
        out.append(list(p))
    changed = True
    while changed and len(out) > 4:
        changed = False
        for k in range(len(out)):
            a, b = out[k], out[(k + 1) % len(out)]
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) < min_jog:
                # remove the short edge by moving b onto a's line
                c = out[(k + 2) % len(out)]
                if abs(b[0] - c[0]) < 1e-6:
                    out[(k + 2) % len(out)][0] = a[0]
                else:
                    out[(k + 2) % len(out)][1] = a[1]
                out.pop((k + 1) % len(out))
                changed = True
                break
    # merge collinear vertices
    res = []
    for k in range(len(out)):
        p, q, r = out[k - 1], out[k], out[(k + 1) % len(out)]
        if (abs(p[0] - q[0]) < 1e-6 and abs(q[0] - r[0]) < 1e-6) or (abs(p[1] - q[1]) < 1e-6 and abs(q[1] - r[1]) < 1e-6):
            continue
        res.append(q)
    return res


pts = rectify(pts, min_jog=0.25)

# ---------- 5. snap each edge to the strongest vertical wall plane nearby (1.6 m to ceiling band) ----------
# snap band just under the ceiling (below crown molding): real walls reach it, freestanding furniture doesn't
wallm = vert & (cen[:, 2] > main_ceiling - 0.33) & (cen[:, 2] < main_ceiling - 0.13)
wc, wn, wa = cen[wallm], n[wallm], area[wallm]


def snap_edges(pts, search=0.2):
    pts = [list(p) for p in pts]
    N = len(pts)
    for k in range(N):
        a, b = pts[k], pts[(k + 1) % N]
        horiz = abs(a[1] - b[1]) < 1e-6  # edge along x at y = const
        ax = 1 if horiz else 0
        c = a[ax]
        lo_, hi_ = sorted([a[1 - ax], b[1 - ax]])
        sel = (np.abs(wn[:, ax]) > 0.85) & (np.abs(wc[:, ax] - c) < search) & (wc[:, 1 - ax] > lo_ + 0.1) & (wc[:, 1 - ax] < hi_ - 0.1)
        if sel.sum() < 5:
            continue
        hst, e = np.histogram(wc[sel, ax], bins=np.arange(c - search, c + search + 0.01, 0.01), weights=wa[sel])
        best = e[np.argmax(hst)] + 0.005
        a[ax] = b[ax] = round(float(best), 3)
    return pts


def axisify(pts):
    """Turn any diagonal edge into an L so the outline is strictly rectilinear."""
    out = []
    for k in range(len(pts)):
        a, b = pts[k], pts[(k + 1) % len(pts)]
        out.append(list(a))
        if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6:
            out.append([b[0], a[1]])
    return out


def clean(pts, eps=0.01):
    """Drop duplicate and collinear vertices."""
    pts = [list(p) for p in pts]
    changed = True
    while changed and len(pts) > 4:
        changed = False
        for k in range(len(pts)):
            p, q, r = pts[k - 1], pts[k], pts[(k + 1) % len(pts)]
            dup = abs(p[0] - q[0]) < eps and abs(p[1] - q[1]) < eps
            col = (abs(p[0] - q[0]) < eps and abs(q[0] - r[0]) < eps) or (abs(p[1] - q[1]) < eps and abs(q[1] - r[1]) < eps)
            if dup or col:
                pts.pop(k)
                changed = True
                break
    return pts


def support(ax, c, lo_, hi_, tol=0.06):
    """Fraction of the span [lo_, hi_] backed by a wall plane at coordinate c (axis ax) in the under-ceiling band."""
    sel = (np.abs(wn[:, ax]) > 0.85) & (np.abs(wc[:, ax] - c) < tol) & (wc[:, 1 - ax] > lo_) & (wc[:, 1 - ax] < hi_)
    if hi_ - lo_ < 0.1:
        return 0.0
    bins = np.arange(lo_, hi_ + 0.1, 0.1)
    h, _ = np.histogram(wc[sel, 1 - ax], bins=bins)
    return float((h > 0).mean())


def flatten_notches(pts, max_depth=0.5):
    """Remove shallow bumps/notches caused by furniture (e.g. a tall bookcase against a wall): if the wall line on
    either side continues behind the bump right up under the ceiling, straighten the edge onto that line."""
    pts = [list(p) for p in pts]
    changed = True
    while changed and len(pts) > 4:
        changed = False
        N = len(pts)
        for k in range(N):
            a, b = pts[k], pts[(k + 1) % N]
            pa, nb = pts[k - 1], pts[(k + 2) % N]
            horiz = abs(a[1] - b[1]) < 1e-6
            ax = 1 if horiz else 0
            c_prev, c_next = pa[ax], nb[ax]
            d1, d2 = abs(a[ax] - c_prev), abs(b[ax] - c_next)
            if abs(c_prev - c_next) > 0.05 or not (0.03 < d1 < max_depth) or not (0.03 < d2 < max_depth):
                continue
            lo_, hi_ = sorted([a[1 - ax], b[1 - ax]])
            s_out, s_here = support(ax, c_prev, lo_, hi_), support(ax, a[ax], lo_, hi_)
            if s_out >= 0.5 and s_out > s_here:
                a[ax] = b[ax] = c_prev
                pts = clean(pts)
                changed = True
                break
    return pts


# enforce CCW before snapping/flattening
s2 = sum(pts[k][0] * pts[(k + 1) % len(pts)][1] - pts[(k + 1) % len(pts)][0] * pts[k][1] for k in range(len(pts)))
if s2 < 0:
    pts = pts[::-1]
def refine_by_profile(pts, reach=0.6, step=0.1, min_run=0.3):
    """Re-fit every wall as a profile: walk along each edge in `step` bins, find the dominant wall plane just under
    the ceiling within `reach` outward (or 0.1 m inward), and split the edge into runs. Handles window bays,
    furniture against walls (bookcases, cabinets, plant stands) and corner notches in one pass.
    Bins with no wall data keep the current line."""
    N = len(pts)
    runs_per_edge = []
    for k in range(N):
        a, b = pts[k], pts[(k + 1) % N]
        horiz = abs(a[1] - b[1]) < 1e-6
        ax = 1 if horiz else 0
        L = abs(b[1 - ax] - a[1 - ax])
        dirn = 1 if b[1 - ax] > a[1 - ax] else -1
        # outward sign along ax for a CCW polygon: outward normal = (dy, -dx)
        dx, dy = b[0] - a[0], b[1] - a[1]
        sgn = np.sign(dy if ax == 0 else -dx)
        c = a[ax]
        offs = []
        for s0 in np.arange(0, max(L, step), step):
            u0, u1 = a[1 - ax] + dirn * s0, a[1 - ax] + dirn * min(s0 + step, L)
            ulo, uhi = sorted([u0, u1])
            t = (wc[:, ax] - c) * sgn
            sel = (np.abs(wn[:, ax]) > 0.85) & (wc[:, 1 - ax] >= ulo) & (wc[:, 1 - ax] < uhi) & (t > -0.1) & (t < reach)
            if wa[sel].sum() < 0.002:
                offs.append(np.nan)
                continue
            h, e = np.histogram(t[sel], bins=np.arange(-0.1, reach + 0.02, 0.02), weights=wa[sel])
            offs.append(e[np.argmax(h)] + 0.01)
        offs = np.array(offs)
        if np.isnan(offs).all():
            offs[:] = 0.0
        # fill gaps from neighbours, then median-filter to kill single-bin noise
        idx = np.arange(len(offs))
        good = ~np.isnan(offs)
        offs = np.interp(idx, idx[good], offs[good])
        offs = ndimage.median_filter(offs, size=5, mode="nearest")
        q = np.round(offs / 0.02) * 0.02
        # group into runs of similar offset, merge runs shorter than min_run into the longer neighbour
        runs = []  # [start_s, end_s, offset]
        for i, v in enumerate(q):
            s0, s1 = i * step, min((i + 1) * step, L)
            if runs and abs(runs[-1][2] - v) < 0.05:
                runs[-1][1] = s1
            else:
                runs.append([s0, s1, v])
        merged = True
        while merged and len(runs) > 1:
            merged = False
            for i, r in enumerate(runs):
                if r[1] - r[0] < min_run:
                    j = i - 1 if i > 0 and (i == len(runs) - 1 or runs[i - 1][1] - runs[i - 1][0] >= runs[i + 1][1] - runs[i + 1][0]) else i + 1
                    lo_i, hi_i = min(i, j), max(i, j)
                    runs[lo_i] = [runs[lo_i][0], runs[hi_i][1], runs[j][2]]
                    runs.pop(hi_i)
                    merged = True
                    break
        runs_per_edge.append((ax, c, sgn, dirn, a, [(r0, r1, c + sgn * off) for r0, r1, off in runs]))
    # rebuild the polygon from the runs
    out = []
    for k in range(N):
        ax, c, sgn, dirn, a, runs = runs_per_edge[k]
        nax, _nc, _nsgn, _ndirn, _na, nruns = runs_per_edge[(k + 1) % N]
        for i, (r0, _r1, line) in enumerate(runs):
            if i > 0:  # step between two runs of the same edge
                u = a[1 - ax] + dirn * r0
                p_prev, p_new = [0, 0], [0, 0]
                p_prev[ax], p_prev[1 - ax] = runs[i - 1][2], u
                p_new[ax], p_new[1 - ax] = line, u
                out += [p_prev, p_new]
        # corner with the next edge: this edge's last line on ax, next edge's first line on nax
        corner = [0, 0]
        corner[ax] = runs[-1][2]
        corner[nax] = nruns[0][2]
        out.append(corner)
    return [[round(float(x), 3), round(float(y), 3)] for x, y in out]


pts = clean(axisify(pts))
pts = snap_edges(pts)
pts = clean(refine_by_profile(clean(pts)))
pts = clean(flatten_notches(pts))
pts = clean(pts)

# origin: SW corner of the outline's bounding box
OX, OY = min(p[0] for p in pts), min(p[1] for p in pts)
outline = [[round(p[0] - OX, 3), round(p[1] - OY, 3)] for p in pts]

# ---------- 6. openings: gaps in the door band along each edge (floor continuing outside = doorway) ----------
floorm = (n[:, 2] > 0.9) & (cen[:, 2] < 0.08)
fi, fj = to_ij(cen[floorm, 0], cen[floorm, 1])
okf = (fi >= 0) & (fi < nx) & (fj >= 0) & (fj < ny)
floor = np.zeros((nx, ny), bool)
floor[fi[okf], fj[okf]] = True
floor = ndimage.binary_closing(floor, iterations=2)

openings = []
N = len(pts)
for k in range(N):
    a, b = pts[k], pts[(k + 1) % N]
    L = abs(a[0] - b[0]) + abs(a[1] - b[1])
    if L < 0.5:
        continue
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    onx, ony = uy, -ux  # outward normal (polygon is CCW)
    t = np.arange(0.05, L - 0.05, CELL)
    wall_here, floor_out = [], []
    for tt in t:
        px, py = a[0] + ux * tt, a[1] + uy * tt
        hit = False
        for d in (-0.1, -0.05, 0, 0.05, 0.1):
            ii, jj = to_ij(px + onx * d, py + ony * d)
            if 0 <= ii < nx and 0 <= jj < ny and doorband[ii, jj]:
                hit = True
        wall_here.append(hit)
        ii, jj = to_ij(px + onx * 0.35, py + ony * 0.35)
        floor_out.append(bool(0 <= ii < nx and 0 <= jj < ny and floor[ii, jj]))
    wall_here = np.array(wall_here)
    gap = ~wall_here
    lab1, nl = ndimage.label(gap)
    for q in range(1, nl + 1):
        idx = np.nonzero(lab1 == q)[0]
        w = len(idx) * CELL
        if w < 0.55:
            continue
        t0, t1 = t[idx[0]], t[idx[-1]]
        fout = np.mean(np.array(floor_out)[idx]) > 0.5
        p0 = [a[0] + ux * t0 - OX, a[1] + uy * t0 - OY]
        p1 = [a[0] + ux * t1 - OX, a[1] + uy * t1 - OY]
        # head height: the header's underside, i.e. the lowest surface above 1.5 m within the wall thickness (rays
        # cast up just outside the inner wall face; just inside it they would hit this room's ceiling)
        heads = []
        for f in (0.25, 0.5, 0.75):
            for d in (0.03, 0.06, 0.09):
                mx = a[0] + ux * (t0 + (t1 - t0) * f) + onx * d
                my = a[1] + uy * (t0 + (t1 - t0) * f) + ony * d
                hz = g.ray.intersects_location([[mx, my, 1.5]], [[0, 0, 1.0]], multiple_hits=False)[0]
                if len(hz):
                    heads.append(float(hz[0][2]))
        head = round(float(np.median(heads)), 2) if heads else None
        openings.append({
            "kind": "opening" if fout else "window-or-gap",
            "a": [round(v, 2) for v in p0], "b": [round(v, 2) for v in p1],
            "width": round(w, 2), "head": head, "edge": k,
            "note": "floor continues beyond: doorway/opening" if fout else "no floor beyond: window, mirror, or scan gap (check photos)",
        })
print(f"{len(openings)} candidate openings")

# ---------- 7. ceiling downstands: connected regions inside the room below the main ceiling ----------
downstands = []
Hr = np.where(room, H, np.nan)
for lv in levels:
    if lv >= main_ceiling - 0.03:
        continue
    reg = room & np.isfinite(Hr) & (np.abs(Hr - lv) < 0.04)
    reg = ndimage.binary_opening(reg, iterations=1)
    labr, nr = ndimage.label(reg)
    for q in range(1, nr + 1):
        cells = np.argwhere(labr == q)
        if len(cells) * CELL * CELL < 0.15:
            continue
        (i0, j0), (i1, j1) = cells.min(0), cells.max(0)
        downstands.append({"name": f"Soffit {lv:.2f} m", "rect": [round(x0 + i0 * CELL - OX, 2), round(y0 + j0 * CELL - OY, 2),
                                                                   round(x0 + (i1 + 1) * CELL - OX, 2), round(y0 + (j1 + 1) * CELL - OY, 2)], "z": lv})
top = max([lv for lv in levels if lv <= main_ceiling + 0.6] or [main_ceiling])
if top > main_ceiling + 0.03:  # main ceiling is itself a downstand under a higher area
    print("note: area higher than the main ceiling found at", top)

# ---------- 8. draft room.json ----------
alp = Path("scan/alignment.json")
if alp.exists():
    al = json.loads(alp.read_text())
else:  # older rooms aligned before alignment.json existed: keep room.json's own scan transform
    print("note: no scan/alignment.json; scan.position/rotationYDeg in the draft are placeholders")
    al = {"translate": [0.0, 0.0, 0.0], "rotationYDeg": 0.0}
tx, ty, tz = al["translate"]
draft = {
    "name": "<Room name>",
    "units": "meters",
    "frame": "Origin at SW interior corner. x = east, y = north, z = up. Plan rotation: rot 0 = item front faces south (-y), 90 = east, 180 = north, 270 = west.",
    "scan": {"file": "scan/scan_raw.glb", "rotationYDeg": al["rotationYDeg"], "position": [round(tx - OX, 4), round(ty, 4), round(tz + OY, 4)],
             "alignedOrigin": [round(OX, 3), round(OY, 3)], "note": "Generated by tools/map_room.py"},
    "outline": outline,
    "wallHeight": main_ceiling,
    "wallThickness": 0.12,
    "ceiling": {"top": main_ceiling, "downstands": downstands, "levelsFound": levels},
    "doors": [], "windows": [], "fixtures": [], "rules": [], "cameras": {},
    "candidateOpenings": openings,
}
(OUT / "room_draft.json").write_text(json.dumps(draft, indent=2) + "\n")

# ---------- 9. review images ----------
PX = 80  # px per meter
W, Hh = int(nx * CELL * PX), int(ny * CELL * PX)
img = Image.new("RGB", (W, Hh), (245, 245, 245))
d = ImageDraw.Draw(img)
P = lambda x, y: ((x - x0) * PX, Hh - (y - y0) * PX)
# floor / clutter / walls rasters
for (msk, col) in ((floor, (225, 210, 185)), (midwall, (150, 150, 150)), (header, (60, 60, 200))):
    for a_, b_ in zip(*np.nonzero(msk)):
        x, y = x0 + a_ * CELL, y0 + b_ * CELL
        d.rectangle([P(x, y + CELL), P(x + CELL, y)], fill=col)
d.line([P(p[0], p[1]) for p in pts] + [P(pts[0][0], pts[0][1])], fill=(220, 30, 30), width=3)
for o in openings:
    col = (0, 160, 0) if o["kind"] == "opening" else (230, 140, 0)
    d.line([P(o["a"][0] + OX, o["a"][1] + OY), P(o["b"][0] + OX, o["b"][1] + OY)], fill=col, width=7)
    d.text(P((o["a"][0] + o["b"][0]) / 2 + OX, (o["a"][1] + o["b"][1]) / 2 + OY), f'{o["width"]}m h{o["head"]}', fill=(0, 0, 0))
for k, p in enumerate(outline):
    d.text(P(pts[k][0], pts[k][1]), f"{p[0]},{p[1]}", fill=(150, 0, 0))
d.text((8, 8), "red = detected outline   blue = header band (above door height)   grey = walls 1.6 m+   "
               "green = opening (floor beyond)   orange = window/gap", fill=(0, 0, 0))
img.save(OUT / "review.png")

c_img = Image.new("RGB", (W, Hh), (255, 255, 255))
dc = ImageDraw.Draw(c_img)
lo_h, hi_h = min(levels + [main_ceiling]) - 0.05, max(levels + [main_ceiling]) + 0.05
for a_, b_ in zip(*np.nonzero(room & np.isfinite(H))):
    t = (H[a_, b_] - lo_h) / max(hi_h - lo_h, 0.01)
    t = min(max(t, 0), 1)
    col = (int(220 - 160 * t), int(80 + 90 * t), int(60 + 160 * t))
    x, y = x0 + a_ * CELL, y0 + b_ * CELL
    dc.rectangle([P(x, y + CELL), P(x + CELL, y)], fill=col)
dc.line([P(p[0], p[1]) for p in pts] + [P(pts[0][0], pts[0][1])], fill=(0, 0, 0), width=2)
dc.text((8, 8), f"ceiling heights inside the room: red low ({lo_h:.2f}) -> blue high ({hi_h:.2f}); levels {levels}", fill=(0, 0, 0))
c_img.save(OUT / "ceiling.png")

print(json.dumps({"outline": outline, "main_ceiling": main_ceiling, "downstands": len(downstands)}, indent=None))
