"""Fast checks on the engine itself: no Blender, no scans, no network."""

import json
import re
import subprocess

import pytest
import validate_room
from conftest import REPO

TOOLS = sorted(p for p in (REPO / "tools").glob("*.py") if p.name not in ("roomframe.py", "blender_models.py", "measure_common.py", "sandbox_guard.py"))
# household builder folders in this checkout (this repo's own, or the public repo's demo household)
BUILDER_DIRS = [d for d in (REPO / "builders", REPO / "examples/builders") if d.is_dir()]
ROOM_SLUGS = re.compile(r"basement-gym|living-room|dining-room|primary-bedroom|rooms/office")


@pytest.mark.parametrize("tool", TOOLS, ids=lambda p: p.name)
def test_tool_declares_dependencies(tool):
    """Every runnable tool carries PEP 723 metadata, so `uv run ../../tools/<tool>.py` works with nothing else."""
    s = tool.read_text()
    assert "# /// script" in s and "# requires-python" in s, f"{tool.name}: add a PEP 723 header"
    if re.search(r"^import bpy", s, re.M):
        assert '"bpy==' in s and '"==3.11.*"' in s, f"{tool.name}: bpy tools pin Python 3.11 and bpy"


@pytest.mark.parametrize("tool", TOOLS, ids=lambda p: p.name)
def test_tool_has_usage(tool):
    doc = re.search(r'^"""(.*?)"""', tool.read_text().split("# ///\n", 2)[-1], re.S | re.M)
    assert doc and ("uv run" in doc.group(1) or "modal run" in doc.group(1)), f"{tool.name}: module docstring needs a usage line (uv run ...)"


@pytest.mark.parametrize("tool", sorted((REPO / "tools").glob("*.py")), ids=lambda p: p.name)
def test_bpy_imported_before_bmesh(tool):
    """bpy 4.5 raises ModuleNotFoundError for bmesh/mathutils imported before bpy."""
    s = tool.read_text()
    bpy = [m.start() for m in re.finditer(r"^import bpy", s, re.M)]
    other = [m.start() for m in re.finditer(r"^(import bmesh|import mathutils|from mathutils)", s, re.M)]
    if other:
        assert bpy and min(bpy) < min(other), f"{tool.name}: import bpy before bmesh/mathutils"


def test_core_models_in_both_renderers():
    """The engine's own models (box, parts, glb, mat, roundRug) exist in the Blender kit and the editor kit."""
    core = validate_room.core_models()
    assert {"box", "parts", "glb"} <= core
    js = (REPO / "editor/src/kit.js").read_text()
    k = js.index("const builders = {")
    editor = set(re.findall(r"^  (\w+)\(s, g\)", js[k:], re.M)) | set(re.findall(r"^  (\w+): \w+,$", js[k:], re.M))
    assert core <= editor, f"core models missing from editor/src/kit.js: {sorted(core - editor)}"


@pytest.mark.parametrize("folder", BUILDER_DIRS, ids=lambda p: str(p.relative_to(REPO)))
def test_builder_parity(folder):
    """In a household's builders/ folder, every photoreal builder (.py) has an editor counterpart (.js) registering the
    same names; editor-only builders (photoreal draws a box) are allowed but validate_room warns where they are used."""
    blender, editor = validate_room.builder_names([folder])
    assert blender - editor == set(), f"add editor counterparts: {sorted(blender - editor)}"
    for f in folder.glob("*.py"):
        if not f.name.startswith("_"):
            assert validate_room.registered(f), f"{f.name}: no BUILDERS = {{...}}"


def test_engine_has_no_furniture_library():
    """The engine draws furniture only from catalog data (box, parts, glb) or a household's builders/; the shared
    catalog holds generic entries only."""
    shared = json.loads((REPO / "shared/catalog.json").read_text())["items"]
    assert {it["model"] for it in shared.values()} <= validate_room.core_models(), "shared/catalog.json may only use core models"
    assert not (REPO / "shared/models").exists(), "model files belong to a household (models/), not the engine"


def test_engine_names_no_room():
    """Engine code never names a room (ARCHITECTURE: the household and its rooms are data)."""
    offenders = []
    for p in [*(REPO / "tools").iterdir(), *(REPO / "editor").rglob("*"), REPO / "server.py"]:
        if p.is_file() and p.suffix in (".py", ".js", ".mjs", ".sh", ".html"):
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if ROOM_SLUGS.search(line):
                    offenders.append(f"{p.relative_to(REPO)}:{i}")
    assert not offenders, "room names in engine code:\n" + "\n".join(offenders)


def test_lessons_are_generic():
    """COOKBOOK and the engine docs are best practice for any room: no dates and no named rooms (a room's own story
    belongs in its README, a household's in HOUSEHOLD.md)."""
    named = re.compile(r"\b20\d\d-\d\d-\d\d\b|basement gym|the (?:living|dining) room's|the office's|primary bedroom", re.I)
    offenders = []
    for p in [REPO / "COOKBOOK.md", REPO / "ARCHITECTURE.md", *(REPO / "docs").glob("*.md")]:
        for i, line in enumerate(p.read_text().splitlines(), 1):
            line = re.sub(r"\]\([^)]*\)", "]", line)  # dates inside link URLs (a register's address) are fine
            if (m := named.search(line)) or (p.name == "COOKBOOK.md" and (m := ROOM_SLUGS.search(line))):
                offenders.append(f"{p.relative_to(REPO)}:{i}: {m.group(0)}")
    assert not offenders, "room-specific lessons:\n" + "\n".join(offenders)


def test_js_syntax():
    for p in [*(REPO / "editor/src").glob("*.js"), *(REPO / "tools").glob("*.mjs")]:
        r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, check=False)
        assert r.returncode == 0, f"{p.name}: {r.stderr}"
