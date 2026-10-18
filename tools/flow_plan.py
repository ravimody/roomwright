# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10.1", "shapely"]
# ///
"""Flow & function plan: traffic paths, walkway widths at pinch points, and seating distances for a layout.

Run from inside rooms/<room>/:
  uv run ../../tools/flow_plan.py <layout> [--out renders/flow/<layout>.png] [--scale 150]

Paths and distances come from the layout's "flow" block, else room.json "flow":
  "flow": {
    "paths": [{"name": "Between the openings", "points": [[x, y], ...], "min": 0.9}],   # main paths >= 0.9 m (36 in)
    "distances": [{"a": "<item id>", "b": "<item id>", "label": "Sofa to sofa"}]
  }
Each path is sampled every 5 cm; at each sample the clear width perpendicular to the path is measured to the nearest
obstacle: the floor contact of the furniture (`baseW`/`baseD` when given, e.g. a speaker stand's plate), fixtures and
walls. Rugs and other `floorLayer` items, wall-mounted items above 1.2 m and ceiling-hung items don't count. The
narrowest point is marked and colour-coded: green >= target, orange within 15 cm of target, red below. A path that passes
through an obstacle or outside the room between free stretches is reported as blocked (width 0 at the first
blocked point); starting or ending at a piece of furniture (the seat it leads to) is fine. Writes a PNG and a
JSON summary next to it.
"""

import argparse
import itertools
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_common import footprint as item_footprint
from measure_common import load_catalog

from roomframe import font as label_font

ap = argparse.ArgumentParser()
ap.add_argument("layout")
ap.add_argument("--out")
ap.add_argument("--scale", type=int, default=150, help="pixels per metre in the image (default 150)")
args = ap.parse_args()

room = json.loads(Path("room.json").read_text())
cat = load_catalog()
layout = json.loads(Path(f"layouts/{args.layout}.json").read_text())
flow = layout.get("flow") or room.get("flow") or {}


def footprint(it):
    """(merged spec, full footprint, floor-contact footprint)."""
    s = {**cat.get(it["type"], cat.get("generic_box", {})), **it}
    return s, Polygon(item_footprint(s)), Polygon(item_footprint(s, base=True))


items = [footprint(it) for it in layout["items"]]
# what you walk into: the floor contact of standing items; not rugs, not things hung from the ceiling or high on a wall
hung = lambda s: s.get("ceiling") is not None or (s.get("hang") == "ceiling" and not s.get("z"))  # pendants, fans, ceiling lights
solid = [(s, b) for s, _, b in items if not s.get("floorLayer") and not hung(s) and (s.get("z") or 0) < 1.2]
roomp = Polygon(room["outline"])


def fixture_poly(f):
    if f["wall"] in ("north", "south"):
        sgn = -1 if f["wall"] == "north" else 1
        y0, y1 = sorted([f["y"], f["y"] + sgn * f.get("depth", 0.05)])
        return Polygon([(f["x0"], y0), (f["x1"], y0), (f["x1"], y1), (f["x0"], y1)])
    sgn = -1 if f["wall"] == "east" else 1
    x0, x1 = sorted([f["x"], f["x"] + sgn * f.get("depth", 0.05)])
    return Polygon([(x0, f["y0"]), (x1, f["y0"]), (x1, f["y1"]), (x0, f["y1"])])


fixtures = [fixture_poly(f) for f in room.get("fixtures", []) if f.get("z0", 0) < 1.0 and f.get("depth", 0) > 0.05]
obstacles = unary_union([p for _, p in solid] + fixtures)
walls = roomp.exterior


def clear_reach(pt, nx, ny, reach=3.0):
    """Free floor from pt along the normal (nx, ny), each way: (distance to the first obstacle or wall at +n, at -n)."""
    out = []
    for sgn in (1, -1):
        ray = LineString([pt, (pt[0] + sgn * nx * reach, pt[1] + sgn * ny * reach)])
        hit = ray.intersection(obstacles.union(walls))
        dist = reach
        if not hit.is_empty:
            dist = min(Point(pt).distance(g) for g in getattr(hit, "geoms", [hit]))
        out.append(dist)
    return out


results, gauges = [], []
for path in flow.get("paths", []):
    line = LineString(path["points"])
    L = line.length
    samples = []
    k = 0.05
    while k < L - 0.05:
        p0, p1 = line.interpolate(k - 0.02), line.interpolate(k + 0.02)
        dx, dy = p1.x - p0.x, p1.y - p0.y
        n = math.hypot(dx, dy) or 1
        pt = line.interpolate(k)
        samples.append((pt, -dy / n, dx / n, obstacles.contains(pt) or not roomp.contains(pt)))
        k += 0.05
    # a path may start or end at a piece of furniture (a seat, the keyboard) or on a door threshold; it is blocked only
    # where it passes through an obstacle between free stretches
    free = [i for i, sm in enumerate(samples) if not sm[3]]
    best, blocked = None, None
    for i in range(free[0], free[-1] + 1) if free else []:
        pt, nx_, ny_, inside = samples[i]
        if inside:
            blocked = blocked or (0.0, pt.x, pt.y)
            continue
        dp, dm = clear_reach((pt.x, pt.y), nx_, ny_)
        if best is None or dp + dm < best[0]:
            best = (dp + dm, pt.x, pt.y, (pt.x + nx_ * dp, pt.y + ny_ * dp), (pt.x - nx_ * dm, pt.y - ny_ * dm))
    best = blocked or best
    tgt = path.get("min", 0.9)
    results.append({"name": path["name"], "minWidth": round(best[0], 2) if best else None, "at": [round(best[1], 2), round(best[2], 2)] if best else None,
                    "target": tgt, "ok": bool(best and best[0] >= tgt), "blocked": blocked is not None})
    gauges.append(best[3:] if best and not blocked else None)  # the measured span across the pinch point, for the drawing

dists, dist_lines = [], []
byid = {s["id"]: p for s, p, _ in items}
for d in flow.get("distances", []):
    if d["a"] in byid and d["b"] in byid:
        g = byid[d["a"]].distance(byid[d["b"]])
        dists.append({"label": d.get("label", f'{d["a"]} - {d["b"]}'), "m": round(g, 2), "in": round(g / 0.0254)})
        dist_lines.append(nearest_points(byid[d["a"]], byid[d["b"]]))

# ---- drawing ----
# drawn at SS x the output size and scaled down, for smooth lines and text
SS, PAD = 2, 0.45
PX = args.scale * SS
xs = [p[0] for p in room["outline"]]
ys = [p[1] for p in room["outline"]]
x0, y0, x1, y1 = min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD
HEAD = 64 * SS
W = int((x1 - x0) * PX)
F = lambda n: label_font(n * SS)
small, mid, big, title = F(13), F(15), F(17), F(21)
ftin = lambda m: f"{m:.2f} m ({m / 0.0254:.0f} in)"
# the key: one entry per path, wrapped to the image width
key, row, rows = [], 24 * SS, 0
measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
for r_ in results:
    txt = f'{r_["name"]}: target {ftin(r_["target"])}'
    w_ = 34 * SS + measure.textlength(txt, font=small) + 30 * SS
    if row + w_ > W and row > 24 * SS:
        row, rows = 24 * SS, rows + 1
    key.append((row, rows, txt, r_))
    row += w_
FOOT = (30 + 26 * (rows + 1)) * SS
H = int((y1 - y0) * PX) + HEAD + FOOT
BG, INK, MUTED = (250, 248, 244), (34, 34, 34), (110, 106, 100)
GOOD, CLOSE, TIGHT = (38, 135, 72), (214, 128, 20), (196, 44, 44)
img = Image.new("RGB", (W, H), BG)
dr = ImageDraw.Draw(img)
P = lambda x, y: ((x - x0) * PX, (y1 - y) * PX + HEAD)


def hex_rgb(h, default=(176, 166, 150)):
    try:
        h = h.lstrip("#")
        return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))
    except (AttributeError, ValueError):
        return default


def tint(c, t):  # mix a colour toward the background: furniture reads as a soft plan, not as blocks
    return tuple(int(a + (b - a) * t) for a, b in zip(c, BG))


def short(s):  # "Sofa, 213 cm (84 in), styled" -> "Sofa"
    name = s.get("label") or s.get("name") or s.get("type", "")
    return name.split(",")[0].split("(")[0].strip()


taken = []  # pixel boxes already used by furniture names and labels


def overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def pill(anchors, text, fnt, col):
    """A label in a rounded box near one of the anchor points, on whichever side covers the least furniture and the
    fewest other labels."""
    pd, gap = 6 * SS, 14 * SS
    tw = dr.textlength(text, font=fnt)
    th = fnt.size
    best = None
    for (x, y), (dx, dy) in itertools.product(anchors,  ((gap, -th / 2), (-gap - tw, -th / 2), (-tw / 2, gap), (-tw / 2, -gap - th), (gap, gap), (-gap - tw, gap),
                   (gap, -gap - th), (-gap - tw, -gap - th))):
        box = (x + dx - pd, y + dy - pd, x + dx + tw + pd, y + dy + th + pd)
        cost = sum(overlap(box, o) for o in taken) * 20 + sum(overlap(box, o) for o in furn_boxes)
        cost += 1e9 * (box[0] < 0 or box[1] < HEAD or box[2] > W or box[3] > H - FOOT)
        if best is None or cost < best[0]:
            best = (cost, box)
    box = best[1]
    taken.append(box)
    dr.rounded_rectangle(box, radius=8 * SS, fill=(255, 255, 255), outline=col, width=2 * SS)
    dr.text((box[0] + pd, box[1] + pd), text, font=fnt, fill=col)


def arrow_line(a, b, col, w):
    dr.line([a, b], fill=col, width=w)
    for (px_, py_), (qx, qy) in ((a, b), (b, a)):
        ang = math.atan2(py_ - qy, px_ - qx)
        hl = 9 * SS
        dr.polygon([(px_, py_), (px_ - hl * math.cos(ang - 0.45), py_ - hl * math.sin(ang - 0.45)),
                    (px_ - hl * math.cos(ang + 0.45), py_ - hl * math.sin(ang + 0.45))], fill=col)


dr.polygon([P(*q) for q in room["outline"]], fill=(241, 236, 226))
for ln in range(int(min(xs) * 2), int(max(xs) * 2) + 1):  # 0.5 m grid
    dr.line([P(ln / 2, min(ys)), P(ln / 2, max(ys))], fill=(232, 226, 214), width=SS)
for ln in range(int(min(ys) * 2), int(max(ys) * 2) + 1):
    dr.line([P(min(xs), ln / 2), P(max(xs), ln / 2)], fill=(232, 226, 214), width=SS)
dr.line([P(*q) for q in room["outline"] + [room["outline"][0]]], fill=INK, width=7 * SS, joint="curve")
for w in room.get("windows", []):
    dr.line([P(*w["a"]), P(*w["b"])], fill=(150, 190, 225), width=7 * SS)
    dr.line([P(*w["a"]), P(*w["b"])], fill=(255, 255, 255), width=2 * SS)
for dd in room.get("doors", []):
    (ax, ay), (bx, by) = dd["a"], dd["b"]
    dr.line([P(ax, ay), P(bx, by)], fill=(241, 236, 226), width=9 * SS)
    if dd.get("style", "door") != "door" or dd.get("swing") not in ("in", "out"):
        continue
    hx, hy, fx, fy = (bx, by, ax, ay) if dd.get("hinge") == "b" else (ax, ay, bx, by)
    r = math.hypot(fx - hx, fy - hy)
    ux, uy = (fx - hx) / r, (fy - hy) / r
    nx_, ny_ = -uy, ux
    if roomp.contains(Point((hx + fx) / 2 + nx_ * 0.05, (hy + fy) / 2 + ny_ * 0.05)) != (dd["swing"] == "in"):
        nx_, ny_ = -nx_, -ny_
    arc = [P(hx + r * (ux * math.cos(t) + nx_ * math.sin(t)), hy + r * (uy * math.cos(t) + ny_ * math.sin(t)))
           for t in [k * math.pi / 2 / 24 for k in range(25)]]
    for k in range(0, 24, 2):
        dr.line(arc[k:k + 2], fill=MUTED, width=2 * SS)
    dr.line([P(hx, hy), P(hx + nx_ * r, hy + ny_ * r)], fill=MUTED, width=3 * SS)
for fp in fixtures:
    dr.polygon([P(*c) for c in fp.exterior.coords], fill=(222, 216, 204), outline=(150, 145, 136))
on_floor = lambda s: s.get("floorLayer") or not (s.get("z") or 0) or hung(s)  # not lamps on tables, vases, wall art
furn_boxes = []
for s, pg, _ in sorted(items, key=lambda t: not t[0].get("floorLayer")):  # rugs first
    if not on_floor(s):
        continue
    col = hex_rgb(s.get("color"))
    if s.get("floorLayer"):
        dr.polygon([P(*c) for c in pg.exterior.coords], fill=tint(col, 0.55), outline=tint(col, 0.3), width=2 * SS)
        continue
    if hung(s):  # ceiling lights and fans: not in the way
        continue
    dr.polygon([P(*c) for c in pg.exterior.coords], fill=tint(col, 0.35 if sum(col) > 240 else 0.6), outline=(90, 84, 76), width=2 * SS)
    (bx0, by0), (bx1, by1) = P(pg.bounds[0], pg.bounds[3]), P(pg.bounds[2], pg.bounds[1])
    furn_boxes.append((bx0, by0, bx1, by1))
names = []  # placed now (labels avoid them), drawn last so lines don't cross them
for s, pg, _ in items:  # names, where they fit
    if s.get("floorLayer") or hung(s) or not on_floor(s) or pg.area < 0.12:
        continue
    c, name = pg.centroid, short(s)
    bw = (pg.bounds[2] - pg.bounds[0]) * PX
    for fnt in (mid, small):
        if dr.textlength(name, font=fnt) < bw * 0.92:
            names.append((P(c.x, c.y), name, fnt, tint(hex_rgb(s.get("color")), 0.35 if sum(hex_rgb(s.get("color"))) > 240 else 0.6)))
            l_, t_, r_, b_ = dr.textbbox(P(c.x, c.y), name, font=fnt, anchor="mm")
            taken.append((l_ - 10 * SS, t_ - 10 * SS, r_ + 10 * SS, b_ + 10 * SS))
            break
for (a, b), d in zip(dist_lines, dists):  # seating distances
    pa, pb = P(a.x, a.y), P(b.x, b.y)
    arrow_line(pa, pb, (70, 90, 120), 2 * SS)
    pill([(pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t) for t in (0.5, 0.3, 0.7)], f'{d["label"]}: {ftin(d["m"])}', small, (70, 90, 120))
for r_, path, g in zip(results, flow.get("paths", []), gauges):
    col = GOOD if r_["ok"] else (CLOSE if r_["minWidth"] and r_["minWidth"] >= r_["target"] - 0.15 else TIGHT)
    pts = [P(*q) for q in path["points"]]
    for (ax_, ay_), (bx_, by_) in itertools.pairwise(pts):  # dashed path line
        seg = math.hypot(bx_ - ax_, by_ - ay_)
        n = max(1, int(seg / (14 * SS)))
        for k in range(0, n, 2):
            dr.line([(ax_ + (bx_ - ax_) * k / n, ay_ + (by_ - ay_) * k / n), (ax_ + (bx_ - ax_) * min(k + 1, n) / n, ay_ + (by_ - ay_) * min(k + 1, n) / n)], fill=col, width=4 * SS)
    ex, ey = pts[-1]
    px_, py_ = pts[-2]
    ang = math.atan2(ey - py_, ex - px_)
    hl = 15 * SS
    dr.polygon([(ex, ey), (ex - hl * math.cos(ang - 0.4), ey - hl * math.sin(ang - 0.4)), (ex - hl * math.cos(ang + 0.4), ey - hl * math.sin(ang + 0.4))], fill=col)
    if r_["at"]:
        cx, cy = P(*r_["at"])
        if g:
            arrow_line(P(*g[0]), P(*g[1]), col, 3 * SS)
        else:
            dr.ellipse([cx - 9 * SS, cy - 9 * SS, cx + 9 * SS, cy + 9 * SS], outline=col, width=4 * SS)
        pill([(cx, cy)], "BLOCKED" if r_["blocked"] else ftin(r_["minWidth"]), big, col)
for xy, name, fnt, halo in names:
    dr.text(xy, name, fill=INK, font=fnt, anchor="mm", stroke_width=4 * SS, stroke_fill=halo)
dr.text((24 * SS, 16 * SS), f'{layout.get("name", args.layout)}: walkways', fill=INK, font=title)
dr.text((24 * SS, 44 * SS), "the narrowest point of each path, between furniture and walls; 0.5 m grid", fill=MUTED, font=small)
for lx, rw, txt, r_ in key:
    col = GOOD if r_["ok"] else (CLOSE if r_["minWidth"] and r_["minWidth"] >= r_["target"] - 0.15 else TIGHT)
    ly = H - FOOT + (22 + 26 * rw) * SS
    dr.line([(lx, ly), (lx + 26 * SS, ly)], fill=col, width=5 * SS)
    dr.text((lx + 34 * SS, ly), txt, fill=MUTED, font=small, anchor="lm")
img = img.resize((W // SS, H // SS), Image.LANCZOS)
out = Path(args.out or f"renders/flow/{args.layout}.png")
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out)
summary = {"layout": args.layout, "paths": results, "distances": dists}
out.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=1))
