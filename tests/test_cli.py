"""The roomwright CLI finds the engine and every tool, in a checkout as in an installed wheel."""

import json
import shutil
import subprocess
import sys

import pytest
import validate_room
from conftest import REPO

sys.path.insert(0, str(REPO))
from roomwright import cli

TOOL_FILES = sorted(p for p in (REPO / "tools").iterdir() if p.suffix in (".py", ".mjs", ".sh") and p.name not in ("roomframe.py", "blender_models.py", "measure_common.py", "sandbox_guard.py"))


def test_engine_root():
    assert cli.ENGINE == REPO and (cli.TOOLS / "render_photoreal.py").exists()


@pytest.mark.parametrize("tool", TOOL_FILES, ids=lambda p: p.name)
def test_every_tool_resolves_and_describes_itself(tool):
    assert cli.tool_path(tool.stem.replace("_", "-")) is not None  # a .py wins over a same-named .mjs
    assert cli.describe(tool), f"{tool.name}: needs a docstring or header comment (shown by `roomwright list`)"


def test_list_and_help(capsys):
    assert cli.main(["list"]) == 0
    assert "render-photoreal" in capsys.readouterr().out
    assert cli.main([]) == 0


def test_render_modal_runs_through_modal(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "run", lambda cmd, **kw: calls.append(cmd) or 0)
    assert cli.main(["render-modal", "--layout", "x"]) == 0
    assert calls[0][-5:] == ["modal", "run", str(cli.TOOLS / "render_modal.py"), "--layout", "x"]


def test_render_modal_uploads_the_household():
    # the container's household folder must hold what roomframe.household_root reads (item types, builders, models)
    src = (REPO / "tools/render_modal.py").read_text()
    for part in ('"builders"', '"models"', '"textures"', '"catalog.json"', '"/repo/rooms"'):
        assert part in src, f"render_modal.py does not upload {part}"


def test_unknown_tool():
    with pytest.raises(SystemExit):
        cli.main(["no-such-tool"])


def test_init_scaffolds_a_household(tmp_path):
    assert cli.main(["init", str(tmp_path)]) == 0
    for name in ("AGENTS.md", "HOUSEHOLD.md", ".gitattributes", ".gitignore", "rooms", ".roomwright/docs/QUICKSTART.md",
                 ".roomwright/docs/DESIGN_GUIDE.md"):
        assert (tmp_path / name).exists(), name
    # AGENTS.md contents and its @path lines: tests/test_agents.py
    assert (tmp_path / ".roomwright/docs/MODELING.md").exists()
    assert json.loads((tmp_path / "catalog.json").read_text())["items"] == {}
    # the example builder pair is valid: both halves register the same name, and the JS parses
    assert validate_room.registered(tmp_path / "builders/stool.py") == validate_room.registered(tmp_path / "builders/stool.js") == {"stool"}
    if shutil.which("node"):
        r = subprocess.run(["node", "--check", str(tmp_path / "builders/stool.js")], capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr
    compile((tmp_path / "builders/stool.py").read_text(), "stool.py", "exec")


def test_demo(tmp_path):
    """`demo` copies the sample household (examples/) into a new folder, ready to use; it never overwrites a folder."""
    home = tmp_path / "home"
    assert cli.main(["demo", str(home)]) == 0
    rooms = [p.parent for p in (home / "rooms").glob("*/room.json") if p.parent.name != "_template"]
    assert rooms, "no sample room"
    for room in rooms:
        assert (room / "scan/scan_aligned.glb").stat().st_size > 100_000, "the sample room ships its stand-in scan"
        assert not (room / "renders").exists()
        rep = validate_room.Report()
        validate_room.check_room(room, rep)
        assert not rep.errors, rep.errors
    assert json.loads((home / "catalog.json").read_text())["items"], "the sample household's item types"
    assert (home / "HOUSEHOLD.md").read_text().strip()
    with pytest.raises(SystemExit, match="isn't empty"):
        cli.main(["demo", str(home)])


def test_init_household_profile_is_a_neutral_questionnaire(tmp_path):
    """`init` writes the questionnaire, not a filled-in example: no one household's taste becomes everyone's default."""
    assert cli.main(["init", str(tmp_path / "h")]) == 0
    text = (tmp_path / "h/HOUSEHOLD.md").read_text()
    template = cli.ENGINE / "shared/HOUSEHOLD.template.md"
    if template.exists():
        assert text == template.read_text()
    assert "2700" not in text and "overheads off" not in text.lower()


def test_wheel_carries_every_example_room():
    """The wheel force-includes the sample household's data path by path (force-include would also take renders/), so a
    new example room needs its own lines in pyproject.toml."""
    py = (REPO / "pyproject.toml").read_text()
    for room in (REPO / "examples/rooms").glob("*/room.json"):
        rel = room.parent.relative_to(REPO).as_posix()
        for part in ("room.json", "layouts", "scan"):
            assert f'"{rel}/{part}"' in py, f"pyproject.toml doesn't ship {rel}/{part}"


def test_synced_docs_keep_their_links(tmp_path):
    """`init` copies the engine docs into .roomwright/ in the repo's own layout, so links between them still work."""
    import re
    from pathlib import Path

    assert cli.main(["init", str(tmp_path)]) == 0
    root = tmp_path / ".roomwright"
    synced = {p.resolve() for p in root.rglob("*.md")}
    broken = []
    for doc in synced:
        for target in re.findall(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)", doc.read_text()):
            if target.startswith("http"):
                continue
            dest = (doc.parent / target).resolve()
            engine_doc = Path(target).name in {"COOKBOOK.md", "ARCHITECTURE.md"} or "docs" in Path(target).parts or doc.parent.name == "docs"
            if engine_doc and dest.name in {p.name for p in synced} and dest not in synced:
                broken.append(f"{doc.relative_to(root)} -> {target}")
    assert not broken, broken
