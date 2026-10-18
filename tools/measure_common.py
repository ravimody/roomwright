"""Shared helpers for the measurement tools (pure Python, no Blender): the room.json ceiling model, ceiling levels for
colour ranges and probe heights, grids sized from the outline, a height colour ramp, and the merged furniture catalog.
Run the tools from inside rooms/<room>/.
"""

import itertools
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def point_in_poly(p, poly):
    x, y, inside = p[0], p[1], False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _in_downstand(d, x, y):
    if "rect" in d:
        x0, y0, x1, y1 = d["rect"]
        return min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)
    return point_in_poly((x, y), d["poly"])


def ceiling_z(room, x, y):
    """Modelled ceiling height at (x, y): the lowest downstand (flat or sloped) over the point, else the top. Same rule
    as the editor's ceilingOver (editor/src/geom.js) at a point."""
    c = room["ceiling"]
    z = c["top"]
    for d in c.get("downstands", []):
        if not _in_downstand(d, x, y):
            continue
        s = d.get("slope")
        if s:
            t = min(max(x if s["axis"] == "x" else y, s["from"]), s["to"])
            z = min(z, s["zFrom"] + (s["zTo"] - s["zFrom"]) * (t - s["from"]) / (s["to"] - s["from"]))
        else:
            z = min(z, d["z"])
    return z


def ceiling_levels(room):
    """(lowest, highest) ceiling height anywhere in room.json, slopes included."""
    c = room["ceiling"]
    zs = [c["top"]]
    for d in c.get("downstands", []):
        if d.get("slope"):
            zs += [d["slope"]["zFrom"], d["slope"]["zTo"]]
        elif "z" in d:
            zs.append(d["z"])
    return min(zs), max(zs)


def extents(room):
    xs, ys = [p[0] for p in room["outline"]], [p[1] for p in room["outline"]]
    return min(xs), min(ys), max(xs), max(ys)


def grid(room, step, margin=0.0):
    """Cell-centre coordinates covering the outline's bounding box (+ margin): (xs, ys, origin(x0, y0))."""
    x0, y0, x1, y1 = extents(room)
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    nx, ny = math.ceil((x1 - x0) / step - 1e-9), math.ceil((y1 - y0) / step - 1e-9)
    xs = [x0 + (i + 0.5) * step for i in range(nx)]
    ys = [y0 + (j + 0.5) * step for j in range(ny)]
    return xs, ys, (x0, y0)


_STOPS = [(0, (200, 40, 40)), (0.35, (240, 200, 60)), (0.6, (120, 190, 110)), (1, (60, 110, 200))]


def height_color(z, lo, hi, nan=(245, 245, 245)):
    """red (low) -> yellow -> green -> blue (high) over [lo, hi]."""
    if z is None or z != z:
        return nan
    t = min(max((z - lo) / max(hi - lo, 1e-6), 0), 1)
    for (t0, c0), (t1, c1) in itertools.pairwise(_STOPS):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(int(c0[k] + (c1[k] - c0[k]) * f) for k in range(3))
    return _STOPS[-1][1]


def load_catalog(room_dir="."):
    """shared/catalog.json, then the household's catalog.json, then the room's own (later wins): roomframe.load_catalog."""
    import roomframe

    return roomframe.load_catalog(room_dir)


def layout_items(layout, room_dir="."):
    """Layout items with their catalog entry merged in (item keys win), as in the editor and the render tools."""
    cat = load_catalog(room_dir)
    lay = json.loads((Path(room_dir) / "layouts" / f"{layout}.json").read_text())
    return [{**cat.get(it["type"], cat.get("generic_box", {})), **it} for it in lay["items"]], lay


def footprint(s, base=False):
    """Rotated footprint polygon of an item (x, y centre, w, d, rot in degrees). base=True uses baseW/baseD."""
    w, d = (s.get("baseW", s["w"]), s.get("baseD", s["d"])) if base else (s["w"], s["d"])
    a = math.radians(s.get("rot", 0))
    ca, sa = math.cos(a), math.sin(a)
    return [(s["x"] + ca * u - sa * v, s["y"] + sa * u + ca * v) for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]
