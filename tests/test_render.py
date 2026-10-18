"""Fast checks of the shared room-frame helpers used by the render and check tools (no Blender needed)."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import roomframe as rf

ROOM = {
    "outline": [[0, 0], [4, 0], [4, 3], [2, 3], [2, 3.5], [0, 3.5]],  # north wall steps out west of x=2
    "ceiling": {
        "top": 2.5,
        "downstands": [
            {"name": "beam", "rect": [1, 0, 1.3, 3], "z": 2.2},
            {"name": "slope", "rect": [3, 0, 4, 3], "z": 1.5, "slope": {"axis": "x", "from": 3, "to": 4, "zFrom": 2.5, "zTo": 1.5}},
            {"name": "poly", "poly": [[0, 3], [1, 3], [1, 3.5], [0, 3.5]], "z": 2.0},
        ],
    },
}


def test_point_in_poly():
    assert rf.point_in_poly((1, 1), ROOM["outline"])
    assert not rf.point_in_poly((3, 3.2), ROOM["outline"])
    assert rf.point_in_poly((1, 3.2), ROOM["outline"])


def test_ceiling_z_flat_rect_poly_and_slope():
    assert rf.ceiling_z(ROOM, 0.5, 1) == 2.5
    assert rf.ceiling_z(ROOM, 1.1, 1) == 2.2
    assert rf.ceiling_z(ROOM, 0.5, 3.2) == 2.0
    assert rf.ceiling_z(ROOM, 3.5, 1) == pytest.approx(2.0)  # halfway down the slope
    assert rf.ceiling_z(ROOM, 4.0, 1) == pytest.approx(1.5)


def test_wall_line_follows_steps():
    assert rf.wall_line(ROOM, "north", 1.0) == 3.5
    assert rf.wall_line(ROOM, "north", 3.0) == 3.0
    assert rf.wall_line(ROOM, "south", 2.0) == 0
    assert rf.wall_line(ROOM, "east", 1.0) == 4


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


@pytest.mark.parametrize("roll", [0, 4.5, -30])
def test_camera_axes_orthonormal_and_looking_forward(roll):
    eye, tgt = (1, 1, 1.6), (4, 2, 1.0)
    r, u, b = rf.camera_axes(eye, tgt, roll)
    for v in (r, u, b):
        assert _dot(v, v) == pytest.approx(1)
    assert _dot(r, u) == pytest.approx(0, abs=1e-12)
    d = [t - e for t, e in zip(tgt, eye)]
    n = math.sqrt(_dot(d, d))
    assert _dot(b, d) / n == pytest.approx(-1)  # camera looks along -back
    if roll == 0:
        assert r[2] == pytest.approx(0, abs=1e-12)  # no roll: horizon level


def test_camera_axes_straight_down():
    _, u, b = rf.camera_axes((0, 0, 2), (0, 0, 0))
    assert b == pytest.approx((0, 0, 1))
    assert u == pytest.approx((0, 1, 0))  # Blender keeps local Y along world +Y looking down


def test_camera_rays_centre_and_sensor_fit():
    np = pytest.importorskip("numpy")
    cam = {"eye": [0, 0, 1.5], "target": [5, 0, 1.5], "lens": 18}
    d = rf.camera_rays(cam, 3, 3).reshape(3, 3, 3)
    assert d[1, 1] == pytest.approx([1, 0, 0])
    # landscape: horizontal half-angle = atan(18 / lens); portrait: the vertical one is
    half = math.atan(18 / 18)
    land = rf.camera_rays(cam, 1001, 501).reshape(501, 1001, 3)
    edge = land[250, 0]
    assert math.atan2(edge[1], edge[0]) == pytest.approx(half, abs=2e-3)
    port = rf.camera_rays(cam, 501, 1001).reshape(1001, 501, 3)
    top = port[0, 250]
    assert math.atan2(top[2], top[0]) == pytest.approx(half, abs=2e-3)
    assert np.allclose(np.linalg.norm(land, axis=-1), 1)


def test_lfs_pointer(tmp_path):
    p = tmp_path / "x.glb"
    p.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n")
    assert rf.is_lfs_pointer(p)
    q = tmp_path / "y.glb"
    q.write_bytes(b"glTF\x02\x00\x00\x00")
    assert not rf.is_lfs_pointer(q)
    with pytest.raises(SystemExit):
        rf.require_file(p, "scan")


def test_downlights_alias():
    """`downlights` (lights and scenes) is the same as `cans`, the US word the code uses; both at once is an error."""
    import validate_room

    room = rf.normalize_room({"lights": {"recessed": [[1, 1]], "downlights": {"lumens": 500}}, "scenes": {"dinner": {"base": "night", "downlights": 0.3}}})
    assert room["lights"]["cans"] == {"lumens": 500} and "downlights" not in room["lights"]
    assert room["scenes"]["dinner"]["cans"] == 0.3
    rep = validate_room.Report()
    validate_room.check_lighting({"lights": {"cans": {}, "downlights": {}}, "scenes": {}}, "room.json", rep)
    assert any("not both" in e for e in rep.errors)


def test_scene_presets_are_neutral():
    """`night` switches every light on (as people do); taste such as downlights off belongs in a named scene."""
    src = (Path(__file__).resolve().parent.parent / "tools/render_photoreal.py").read_text()
    assert 'BASES = ("day", "night", "evening", "standard")' in src
    assert 'sc.setdefault("cans", 1.0 if base in ("standard", "night") else 0.0)' in src
