"""roomwright command line: run the engine's tools from a room folder, without paths to the engine.

  roomwright <tool> [args]        run tools/<tool>.py (with uv; each tool declares its own dependencies), .mjs (node) or .sh
  roomwright list                 every tool with its one-line description
  roomwright serve [--root DIR]   the layout editor for the rooms in DIR (default: the current repo)
  roomwright new-room NAME [SCAN] rooms/NAME/ from the template; with a scan, plus the first automatic pass (align, map,
                                views, furniture)
  roomwright doctor [--full]      check uv, git-lfs, node, Python 3.11 / bpy, Chrome, Modal
  roomwright docs [--sync DIR]    print where the engine docs are, or copy them into DIR (default .roomwright) for agents
  roomwright init [DIR]           start a household repo: rooms/, HOUSEHOLD.md, AGENTS.md (read by Claude Code, Codex,
                                Antigravity, Cursor, …), pyproject.toml pinning this engine, catalog.json, builders/
                                (with an example), models/, .gitattributes, .gemini/settings.json, docs
  roomwright demo [DIR]         the sample household in DIR (default roomwright-demo/): a made-up living room with a
                                stand-in scan, layouts (one with planted mistakes) and simple furniture models

Tool names accept dashes or underscores (geometry-check = geometry_check). Run room tools from inside rooms/<room>/.
"""

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

from roomwright import __version__


def engine_root():
    """The folder holding tools/, editor/, shared/, schema/: the installed package, or the repo in a dev checkout."""
    here = Path(__file__).resolve().parent
    for cand in (here, here.parent):
        if (cand / "tools").is_dir() and (cand / "shared").is_dir():
            return cand
    sys.exit("roomwright: engine files not found next to the package (broken install?)")


ENGINE = engine_root()
TOOLS = ENGINE / "tools"
DOCS = [ENGINE / "docs", *(ENGINE / n for n in ("ARCHITECTURE.md", "COOKBOOK.md") if (ENGINE / n).exists())]
# The engine's own agent instructions go into a household's docs as ENGINE_AGENTS.md: a file named AGENTS.md in a
# subfolder is loaded as rules by agents that open files there (Claude Code, Antigravity). In a development checkout
# the public version lives in scripts/public/ (the repo's own AGENTS.md is the household's).
ENGINE_AGENTS = next((p for p in (ENGINE / "scripts/public/AGENTS.public.md", ENGINE / "AGENTS.md") if p.exists()), None)


def tool_path(name):
    name = name.replace("-", "_")
    for ext in (".py", ".mjs", ".sh"):
        p = TOOLS / f"{name}{ext}"
        if p.exists() and p.name not in ("roomframe.py", "blender_models.py", "measure_common.py", "sandbox_guard.py"):
            return p
    return None


def describe(p):
    """First sentence of a tool's docstring or header comment."""
    s = p.read_text()
    m = re.search(r'"""(.+?)(?:\n\n|""")', s, re.S) if p.suffix == ".py" else re.search(r"^(?://|#)(?!!)\s*(.+)$", s, re.M)
    return " ".join(m.group(1).split())[:110] if m else ""


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, check=False, **kw).returncode
    except FileNotFoundError:
        sys.exit(f"roomwright: {cmd[0]} not found (run `roomwright doctor`)")


def run_tool(p, args):
    if p.suffix == ".py":
        if not shutil.which("uv"):
            sys.exit("roomwright: the tools run with uv; install it from https://docs.astral.sh/uv/")
        if p.stem == "render_modal":  # a Modal app: `modal run` calls its entrypoint (it needs `modal setup` once)
            return run(["uv", "tool", "run", "--quiet", "--from", "modal", "modal", "run", str(p), *args])
        return run(["uv", "run", "--quiet", str(p), *args])
    if p.suffix == ".mjs":
        return run(["node", str(p), *args])
    return run(["bash", str(p), *args])


def cmd_list():
    width = max(len(p.stem) for p in TOOLS.iterdir())
    for p in sorted(TOOLS.iterdir()):
        if p.suffix in (".py", ".mjs", ".sh") and p.name not in ("roomframe.py", "blender_models.py", "measure_common.py", "sandbox_guard.py"):
            print(f"  {p.stem.replace('_', '-'):{width}s}  {describe(p)}")


def cmd_serve(args):
    root = Path.cwd()
    if "--root" not in args:  # serve the rooms of the repo we're in (walk up from a room folder)
        for d in (root, *root.parents):
            if (d / "rooms").is_dir():
                root = d
                break
        args = [*args, "--root", str(root)]
    return run(["uv", "run", "--quiet", str(ENGINE / "server.py"), *args])


def cmd_new_room(args):
    rooms = Path.cwd() / "rooms"
    if not rooms.is_dir():
        sys.exit("roomwright new-room: run it from your repo's root (the folder with rooms/); `roomwright init` creates one")
    return run(["bash", str(TOOLS / "new_room.sh"), *args], env={**os.environ, "ROOMS_DIR": str(rooms)})


def sync_docs(dest):
    """Copy the engine docs into a household (default `.roomwright/`) in the repo's own layout, so their links work:
    COOKBOOK.md and ARCHITECTURE.md at the top, the rest in docs/, the engine's agent rules as ENGINE_AGENTS.md."""
    dest = Path(dest)
    (dest / "docs").mkdir(parents=True, exist_ok=True)
    for src in DOCS:
        if src.is_dir():
            shutil.copytree(src, dest / "docs", dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest / src.name)
    if ENGINE_AGENTS:
        shutil.copy2(ENGINE_AGENTS, dest / "ENGINE_AGENTS.md")
    for stale in ("AGENTS.md", "COOKBOOK.md", "ARCHITECTURE.md", "ENGINE_AGENTS.md", "VERSION"):  # older, flat syncs into docs/
        (dest / "docs" / stale).unlink(missing_ok=True)
    (dest / "VERSION").write_text(f"roomwright {__version__}\n")
    print(f"engine docs (roomwright {__version__}) copied to {dest}")


def cmd_docs(args):
    if args[:1] == ["--sync"]:
        sync_docs(args[1] if len(args) > 1 else ".roomwright")
    else:
        for d in [*DOCS, ENGINE_AGENTS]:
            if d:
                print(d)
    return 0


INIT_FILES = {
    ".gitattributes": "*.glb filter=lfs diff=lfs merge=lfs -text\n*.fbx filter=lfs diff=lfs merge=lfs -text\n*.HEIC filter=lfs diff=lfs merge=lfs -text\n"
                      "*.heic filter=lfs diff=lfs merge=lfs -text\n*.jpg filter=lfs diff=lfs merge=lfs -text\n*.png filter=lfs diff=lfs merge=lfs -text\n"
                      "*.exr filter=lfs diff=lfs merge=lfs -text\n",
    ".gitignore": "__pycache__/\n.DS_Store\n.venv/\nrooms/*/renders/photoreal/scratch*/\nrooms/*/renders/_smoke/\nrooms/*/renders/photoreal/_smoke/\n",
    "AGENTS.md": """# Agent instructions

Instructions for every coding agent working in this household's repo (Claude Code, Codex, Antigravity, Cursor, Gemini CLI, …).
Keep this file under 24 KB (Antigravity's limit per file) and lean: a line belongs here only if removing it would cause mistakes.

## Read before working
Agents that follow `@path` imports (Claude Code) load these automatically; every other agent: read them first.
- @HOUSEHOLD.md — this household (who lives here, region, language and units, buying, taste, how results are delivered)
- @.roomwright/docs/QUICKSTART.md — the commands, in order
- @.roomwright/COOKBOOK.md — the pipeline step by step, and best practices (read before starting a room)
- On demand, in `.roomwright/docs/`: `DESIGN_GUIDE.md` (design guidance), `MODELING.md` (modelling furniture), `TOOLS.md`
  (every tool's options), `DATA.md` (every data key), `AGENT_SETUP.md` (agent sandboxes), `PERSONAS.md`; and
  `.roomwright/ENGINE_AGENTS.md` (engine conventions)

## Working rules
- The engine is the `roomwright` package, pinned in `pyproject.toml`. Run tools from inside `rooms/<room>/` as
  `uv run roomwright <tool> …` (`uv run roomwright list` shows them; `uv run roomwright doctor` checks this machine and the agent's
  sandbox). After upgrading the engine, refresh these docs with `uv run roomwright docs --sync` (into `.roomwright/`).
- Talk to the person, and write reports, in the language and units HOUSEHOLD.md gives; keep file names and data keys
  in English. Ask rather than assume taste: lighting habits, colour of light, how full they like a room, culture.
- Match the effort to the person (HOUSEHOLD.md): quick (rough measurements, no scan checks, say so), standard, or
  verified. When a scan exists and results must fit, run `geometry-check <layout>` after any geometry or layout change
  and fix or explain every `CHECK` item before showing renders; measure fixes from the scan, never by eye.
- Read the room's `style` and `sourcing` (room.json) before proposing anything. Design advice from `DESIGN_GUIDE.md` is
  guidance to explain and offer, never rules; `HOUSEHOLD.md` and each room's style override it.
- Product dimensions come from the spec sheet. Model furniture at its real size (box, then parts, or a model file:
  `MODELING.md`); item types go in `catalog.json` (the whole household) or `rooms/<room>/catalog.json`, code builders in
  `builders/<name>.py` + `.js` pairs.
- Lights come from real bulbs (lumens, kelvin, dimmer settings). An `ASSUMED:` line in a render means: ask for the bulb, or
  fit it to the person's photos with `light-match`.
- If the household uses git, every change goes through a branch and a pull request; otherwise keep a dated change log
  in each room's README. Keep each room's README, layouts and report in sync.
- Engine bugs and lessons for any room can go upstream to roomwright (a PR or an issue), only with the person's agreement and
  stripped of household details; household preferences go in `HOUSEHOLD.md`, room
  decisions in the room's README.
""",
    ".gemini/settings.json": json.dumps({"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}}, indent=2) + "\n",
    "catalog.json": json.dumps({"note": "This household's item types (metres: w = width as you face the front, d = depth, h = height). "
                                        "Rooms add their own in rooms/<room>/catalog.json; later entries win. See .roomwright/docs/MODELING.md.",
                                "items": {}}, indent=2) + "\n",
    "models/README.md": "# Model files\n\nGLB files for catalog entries (`\"model\": \"glb\", \"file\": \"models/<name>.glb\"`), prepared with "
                        "`roomwright model-import`. Record each one's source and licence below; don't publish files whose licence forbids it.\n\n"
                        "| Model | Source | Licence |\n|---|---|---|\n",
    "builders/README.md": "# Builders\n\nCode models for families of pieces this household reuses with options (most pieces need only `parts` in the "
                          "catalog: .roomwright/docs/MODELING.md). Each builder is a pair: `<name>.py` (photoreal renders: "
                          "`BUILDERS = {\"name\": fn(spec, builder, materials)}`, importing helpers from `blender_models`) and `<name>.js` "
                          "(the editor: `export const BUILDERS = { name(s, g) {...} }`, importing from `/editor/src/kit.js`). Files starting "
                          "with `_` are shared helpers. `stool.py`/`stool.js` are a small example; delete them when you add your own.\n",
    "builders/stool.py": '"""Example builder: a round stool with three splayed legs (`seatH`, `legs`). Pairs with stool.js."""\n\n'
                         "import math\n\nfrom blender_models import hex_rgb, wood\n\n\n"
                         "def b_stool(s, b, m):\n"
                         "    top = wood(f\"stool_{s.get('color')}\", hex_rgb(s.get(\"color\", \"#8a6a4a\")))\n"
                         "    h, r = s[\"h\"], s[\"w\"] / 2\n"
                         "    b.cyl(r, 0.03, 0, 0, h - 0.015, top)  # seat\n"
                         "    for k in range(s.get(\"legs\", 3)):  # legs splay out from under the seat to the footprint's edge\n"
                         "        a = 2 * math.pi * k / s.get(\"legs\", 3)\n"
                         "        leg = b.cyl(0.015, h - 0.02, math.cos(a) * r * 0.75, math.sin(a) * r * 0.75, (h - 0.03) / 2, top)\n"
                         "        leg.rotation_euler = (math.sin(a) * 0.12, -math.cos(a) * 0.12, 0)  # feet out\n\n\n"
                         "BUILDERS = {\"stool\": b_stool}\n",
    "builders/stool.js": "// Example editor builder: the round stool of stool.py (cheaper is fine: footprint, height, silhouette).\n"
                         "import { cyl, mat } from \"/editor/src/kit.js\";\n\n"
                         "export const BUILDERS = {\n"
                         "  stool(s, g) {\n"
                         "    const top = mat(s.color ?? \"#8a6a4a\", { roughness: 0.6 });\n"
                         "    const r = s.w / 2;\n"
                         "    cyl(g, r, 0.03, 0, s.h - 0.015, 0, top, \"y\", 24);\n"
                         "    for (let k = 0; k < (s.legs ?? 3); k++) {\n"
                         "      const a = (2 * Math.PI * k) / (s.legs ?? 3);\n"
                         "      cyl(g, 0.015, s.h - 0.02, Math.cos(a) * r * 0.75, (s.h - 0.03) / 2, -Math.sin(a) * r * 0.75, top, \"y\", 8);\n"
                         "    }\n"
                         "  },\n"
                         "};\n",
}


def engine_requirement():
    """This engine as a pyproject dependency: the git commit, wheel or folder it was installed from (PEP 610
    direct_url.json), else the released version; a source checkout that isn't installed pins its own folder."""
    try:
        dist = importlib.metadata.distribution("roomwright")
    except importlib.metadata.PackageNotFoundError:
        return "roomwright", f'roomwright = {{ path = "{ENGINE}", editable = true }}'
    du = json.loads(dist.read_text("direct_url.json") or "null")
    if not du:
        return f"roomwright=={dist.version}", None
    url = du["url"]
    if "vcs_info" in du:
        return f"roomwright @ {du['vcs_info']['vcs']}+{url}@{du['vcs_info']['commit_id']}", None
    if "dir_info" in du and url.startswith("file://"):
        editable = "true" if du["dir_info"].get("editable") else "false"
        return "roomwright", f'roomwright = {{ path = "{urllib.parse.unquote(urllib.parse.urlparse(url).path)}", editable = {editable} }}'
    return f"roomwright @ {url}", None


def household_pyproject(name):
    req, source = engine_requirement()
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "home"
    text = (f'[project]\nname = "{slug}"\nversion = "0"\ndescription = "Rooms and preferences of one household (roomwright)"\n'
            f'requires-python = ">=3.11"\ndependencies = ["{req}"]\n\n[tool.uv]\npackage = false\n')
    return text + (f"\n[tool.uv.sources]\n{source}\n" if source else "")


def cmd_init(args):
    dest = Path(args[0] if args else ".").resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for name, text in INIT_FILES.items():
        p = dest / name
        if p.exists():
            print(f"kept existing {name}")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            print(f"wrote {name}")
    pp = dest / "pyproject.toml"
    if pp.exists():
        print("kept existing pyproject.toml (add roomwright to its dependencies if it isn't there)")
    else:
        pp.write_text(household_pyproject(dest.name))
        print("wrote pyproject.toml (pins this engine; `uv run roomwright …` installs it on first use)")
    hh = dest / "HOUSEHOLD.md"
    template = ENGINE / "shared/HOUSEHOLD.template.md"  # a neutral questionnaire; examples/HOUSEHOLD.example.md shows filled ones
    if not hh.exists():
        shutil.copy2(template, hh) if template.exists() else hh.write_text("# Household profile\n\nRegion, language and units; who lives here and who decides; renting or owning; climate and power; budget and where you buy; lighting habits and taste; how results are delivered.\n")
        print("wrote HOUSEHOLD.md (answer its questions first, or let your agent ask you)")
    (dest / "rooms").mkdir(exist_ok=True)
    sync_docs(dest / ".roomwright")
    print(f"\nNext: `git init` (and `git lfs install`), fill in HOUSEHOLD.md, then `uv run roomwright new-room <name> [scan.glb]` from {dest} (the scan is optional)")
    return 0




def cmd_demo(args):
    """Copy the sample household (a made-up living room with a stand-in scan, so every tool runs) into a folder."""
    src = ENGINE / "examples"
    if not (src / "rooms").is_dir():
        sys.exit("roomwright demo: this install has no sample household (examples/)")
    home = Path(args[0] if args else "roomwright-demo").resolve()
    if home.exists() and any(home.iterdir()):
        sys.exit(f"roomwright demo: {home} exists and isn't empty; give a new folder")
    cmd_init([str(home)])
    shutil.copytree(src / "rooms", home / "rooms", dirs_exist_ok=True, ignore=shutil.ignore_patterns("renders", "__pycache__"))
    shutil.copy2(src / "catalog.json", home / "catalog.json")
    for sub in ("models", "builders"):
        if (src / sub).is_dir():
            shutil.copytree(src / sub, home / sub, dirs_exist_ok=True)
    rooms = sorted(p.parent.name for p in (home / "rooms").glob("*/room.json") if p.parent.name != "_template")
    room = home / "rooms" / rooms[0]
    print(f"sample household ready: {home} (rooms: {', '.join(rooms)})\nTry, from {room}:\n"
          "  roomwright validate-room\n  roomwright geometry-check draft-with-mistakes   # finds the three planted mistakes\n"
          "  roomwright render-photoreal proposal --lighting night --views fireplace --samples 16\n"
          f"  roomwright serve   (from {home}) for the 3D editor; tick \"Original scan\"")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        cmd_list()
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd in ("--version", "version"):
        print(f"roomwright {__version__} ({ENGINE})")
        return 0
    special = {"list": lambda a: cmd_list() or 0, "serve": cmd_serve, "new-room": cmd_new_room, "new_room": cmd_new_room,
               "docs": cmd_docs, "init": cmd_init, "demo": cmd_demo}
    if cmd in special:
        return special[cmd](args)
    p = tool_path(cmd)
    if not p:
        sys.exit(f"roomwright: no tool {cmd!r}; `roomwright list` shows them")
    return run_tool(p, args)


if __name__ == "__main__":
    sys.exit(main())
