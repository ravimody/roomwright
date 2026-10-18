"""Agent instructions work in every coding agent: AGENTS.md is the one file (Claude Code, Codex, Antigravity, Cursor, …
read it), it stays under Antigravity's 24 KB per-file limit, its `@path` lines resolve, no other AGENTS.md or CLAUDE.md
hides in the tree, and every Blender tool loads the sandbox guard before bpy."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from roomwright import cli  # noqa: E402

LIMIT = 24_000  # bytes per file (Antigravity); Codex reads 32 KiB in total


def imports(path):
    """`- @path` lines. The path ends at whitespace for Claude Code, so nothing may follow it directly (`@a.md:` imports "a.md:")."""
    return [m.group(1) for m in re.finditer(r"^- @(\S+)", path.read_text(), re.M)]


def test_agents_md_is_the_one_instructions_file():
    files = [p for p in (REPO / "AGENTS.md", REPO / "scripts/public/AGENTS.public.md") if p.exists()]  # the public one: dev checkout only
    for p in files:
        assert p.stat().st_size < LIMIT, f"{p.name}: {p.stat().st_size} bytes; move detail into the docs it points to"
    for p in files:  # the public one lands at the export's root, next to the same docs
        for rel in imports(p):
            assert (REPO / rel).exists(), f"{p.name}: {rel}"
    r = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=False)
    tracked = r.stdout.split() if r.returncode == 0 else [str(p.relative_to(REPO)) for p in REPO.rglob("*.md") if ".venv" not in p.parts]
    others = [f for f in tracked if Path(f).name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md") and f != "AGENTS.md"]
    assert not others, f"{others}: agents load these as rules for their folder (or instead of AGENTS.md)"


def test_init_writes_agents_md_for_every_agent(tmp_path):
    assert cli.main(["init", str(tmp_path)]) == 0
    agents = tmp_path / "AGENTS.md"
    assert agents.stat().st_size < LIMIT and not (tmp_path / "CLAUDE.md").exists()
    assert imports(agents), "the read-first list should use @path lines (Claude Code loads them; others read the paths)"
    for rel in imports(agents):
        assert (tmp_path / rel).exists(), rel
    for name in ("DESIGN_GUIDE.md", "MODELING.md", "AGENT_SETUP.md", "ENGINE_AGENTS.md"):
        assert name in agents.read_text() and any((tmp_path / ".roomwright" / d / name).exists() for d in ("", "docs")), name
    assert not (tmp_path / ".roomwright/docs/AGENTS.md").exists() and not (tmp_path / ".roomwright/docs/COOKBOOK.md").exists()
    assert json.loads((tmp_path / ".gemini/settings.json").read_text())["context"]["fileName"][0] == "AGENTS.md"
    py = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert any(d.startswith("roomwright") for d in py["project"]["dependencies"])


def test_blender_tools_load_the_sandbox_guard_first():
    for p in sorted((REPO / "tools").glob("*.py")):
        lines = p.read_text().splitlines()
        top = [i for i, ln in enumerate(lines) if ln.split("#")[0].rstrip() == "import bpy"]  # top level only (render_modal imports it on Modal)
        if not top:
            continue
        guard = next((i for i, ln in enumerate(lines) if ln.startswith("import sandbox_guard")), None)
        bpy = top[0]
        assert guard is not None and guard < bpy, f"{p.name}: `import sandbox_guard` must come before `import bpy`"
