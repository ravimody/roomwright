"""Every room's data validates (schema + semantic checks) and every layout survives the layout checker."""


import subprocess

import pytest
import validate_room
from conftest import REPO

ROOM_DIRS = [d for d in (REPO / "rooms", REPO / "examples/rooms") if d.is_dir()]  # this repo, or the public repo's demo
ROOMS = sorted(p for d in ROOM_DIRS for p in d.iterdir() if (p / "room.json").exists())


def test_shared_and_household_catalogs_validate():
    rep = validate_room.Report()
    validate_room.check_shared_catalogs([d.parent for d in ROOM_DIRS], rep)
    assert not rep.errors, "\n".join(rep.errors)


@pytest.mark.parametrize("room", ROOMS, ids=lambda p: p.name)
def test_room_validates(room):
    rep = validate_room.Report()
    validate_room.check_room(room, rep)
    assert not rep.errors, "\n".join(rep.errors)


@pytest.mark.parametrize("layout", sorted(p for d in ROOM_DIRS for p in d.glob("*/layouts/*.json")), ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_check_layout_runs(layout):
    """The CLI checker may report issues (exit 1) but must not crash."""
    r = subprocess.run(["node", str(REPO / "tools/check_layout.mjs"), str(layout.relative_to(layout.parent.parent))],
                       cwd=layout.parent.parent, capture_output=True, text=True, check=False)
    assert r.returncode in (0, 1) and "Error:" not in r.stderr, r.stderr[-800:]
