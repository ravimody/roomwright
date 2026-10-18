"""The modelling kit's data side: where households keep catalogs, builders and model files, and (with Blender, when
ROOMWRIGHT_BPY=1) that box, parts and glb items are built at their catalog size."""

import json
import os
import shutil
import subprocess

import pytest
import validate_room
from conftest import REPO

import roomframe


def household(tmp_path):
    room = tmp_path / "rooms/r"
    room.mkdir(parents=True)
    (tmp_path / "catalog.json").write_text(json.dumps({"items": {"chair": {"model": "box", "w": 1, "d": 1, "h": 1}, "lamp": {"model": "box", "w": 2, "d": 2, "h": 2}}}))
    (room / "catalog.json").write_text(json.dumps({"items": {"lamp": {"model": "box", "w": 3, "d": 3, "h": 3}}}))
    return room


def test_household_root_is_the_folder_holding_rooms(tmp_path):
    room = household(tmp_path)
    assert roomframe.household_root(room) == tmp_path
    assert roomframe.household_root(tmp_path / "loose") is None


def test_catalogs_merge_shared_household_room(tmp_path):
    cat = roomframe.load_catalog(household(tmp_path))
    assert "generic_box" in cat  # the engine's shared entries
    assert cat["chair"]["w"] == 1 and cat["lamp"]["w"] == 3  # household entries; the room's win


def test_asset_path_room_first_then_household(tmp_path):
    room = household(tmp_path)
    (tmp_path / "models").mkdir()
    (tmp_path / "models/a.glb").write_text("x")
    assert roomframe.asset_path("models/a.glb", room) == tmp_path / "models/a.glb"
    (room / "models").mkdir()
    (room / "models/a.glb").write_text("y")
    assert roomframe.asset_path("models/a.glb", room) == room / "models/a.glb"


def test_builder_modules_are_discovered_per_room(tmp_path):
    room = household(tmp_path)
    (tmp_path / "builders").mkdir()
    (tmp_path / "builders/stool.py").write_text('BUILDERS = {"stool": None, "bar_stool": None}\n')
    (tmp_path / "builders/stool.js").write_text("export const BUILDERS = {\n  stool(s, g) {\n  },\n  bar_stool: stool,\n};\n")
    (tmp_path / "builders/_helpers.py").write_text('BUILDERS = {"not_a_builder": None}\n')
    (room / "builders").mkdir()
    (room / "builders/lamp.js").write_text("export const BUILDERS = {\n  lamp(s, g) {},\n};\n")
    blender, editor = validate_room.builder_names(validate_room.builder_dirs(room))
    core = validate_room.core_models()
    assert blender == core | {"stool", "bar_stool"}
    assert editor == core | {"stool", "bar_stool", "lamp"}


def test_parts_schema_accepts_the_modeling_examples():
    """Every catalog entry in docs/MODELING.md's examples is valid catalog data."""
    text = (REPO / "docs/MODELING.md").read_text()
    blocks = [b.split("```", 1)[0] for b in text.split("```json")[1:]]
    entries = [json.loads(b) for b in blocks]
    assert len(entries) >= 4
    for e in entries:
        rep = validate_room.Report()
        validate_room.schema_check({"items": e}, "catalog", "MODELING.md", rep)
        assert not rep.errors, rep.errors


@pytest.mark.skipif(os.environ.get("ROOMWRIGHT_BPY") != "1" or not shutil.which("uv"),
                    reason="set ROOMWRIGHT_BPY=1 to build the core models with Blender (uv fetches bpy on first use)")
def test_core_models_build_to_catalog_size(tmp_path):
    r = subprocess.run(["uv", "run", "--quiet", str(REPO / "tests/kit_build.py"), str(tmp_path)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
