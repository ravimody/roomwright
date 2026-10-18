"""Fast checks of the measurement helpers (tools/measure_common.py): no scan, no Blender."""

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from measure_common import ceiling_levels, ceiling_z, extents, footprint, grid, height_color, point_in_poly  # noqa: E402

ROOMS = sorted(p.parent for p in (REPO / "rooms").glob("*/room.json") if not p.parent.name.startswith("_"))
ROOM = {
    "outline": [[0, 0], [4, 0], [4, 3], [0, 3]],
    "ceiling": {"top": 2.5, "downstands": [
        {"name": "soffit", "rect": [0, 0, 1, 3], "z": 2.1},
        {"name": "slope", "rect": [2, 0, 4, 1], "z": 1.4, "slope": {"axis": "y", "from": 0, "to": 1, "zFrom": 1.4, "zTo": 2.5}},
    ]},
}


def test_ceiling_z_flat_downstand_and_slope():
    assert ceiling_z(ROOM, 3.0, 2.0) == 2.5
    assert ceiling_z(ROOM, 0.5, 2.0) == 2.1
    assert math.isclose(ceiling_z(ROOM, 3.0, 0.5), 1.95)
    assert math.isclose(ceiling_z(ROOM, 3.0, 0.0), 1.4)


def test_ceiling_levels_include_slope_ends():
    assert ceiling_levels(ROOM) == (1.4, 2.5)


def test_grid_covers_outline():
    xs, ys, (x0, y0) = grid(ROOM, 0.05)
    assert (x0, y0) == (0, 0)
    assert len(xs) == 80 and len(ys) == 60
    assert xs[-1] < 4 < xs[-1] + 0.05


def test_footprint_rotation_and_base():
    s = {"x": 1, "y": 1, "w": 2, "d": 1, "rot": 90, "baseW": 0.5, "baseD": 0.5}
    pts = footprint(s)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert math.isclose(max(xs) - min(xs), 1, abs_tol=1e-9) and math.isclose(max(ys) - min(ys), 2, abs_tol=1e-9)
    b = footprint(s, base=True)
    assert math.isclose(max(p[0] for p in b) - min(p[0] for p in b), 0.5, abs_tol=1e-9)


def test_point_in_poly_l_shape():
    L = [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]]
    assert point_in_poly((0.5, 1.5), L) and not point_in_poly((1.5, 1.5), L)


def test_height_color_ends():
    assert height_color(1.0, 1.0, 2.0) == (200, 40, 40)
    assert height_color(2.0, 1.0, 2.0) == (60, 110, 200)
    assert height_color(float("nan"), 1.0, 2.0) == (245, 245, 245)


@pytest.mark.parametrize("room_dir", ROOMS, ids=lambda p: p.name)
def test_every_room_ceiling_is_inside_its_levels(room_dir):
    room = json.loads((room_dir / "room.json").read_text())
    lo, hi = ceiling_levels(room)
    x0, y0, x1, y1 = extents(room)
    for i in range(11):
        for j in range(11):
            x, y = x0 + (x1 - x0) * i / 10, y0 + (y1 - y0) * j / 10
            assert lo - 1e-9 <= ceiling_z(room, x, y) <= hi + 1e-9
