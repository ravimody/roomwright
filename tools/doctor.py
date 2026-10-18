# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check that this machine can run the pipeline, and say how to fix what's missing.

Usage (from the repo root or any room folder):
  uv run tools/doctor.py            quick checks (seconds)
  uv run tools/doctor.py --full     also installs and imports Blender's Python module (bpy 4.5, ~400 MB on first run)

Checks: uv, git, Git LFS (installed, and scans/textures pulled rather than pointer files), Node (layout checker and
editor tests), Python 3.11 for bpy, optional Chrome (PDF export), optional Modal (cloud renders). Inside a coding
agent's sandbox it also checks what the sandbox blocks: writing uv's cache, the network for first-run downloads, and
(with --full) whether Blender starts at all. docs/AGENT_SETUP.md has the per-agent setup.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OK, WARN, FAIL = "ok  ", "warn", "FAIL"
results = []


def run(cmd):
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}  # look outside doctor's own venv
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False, env=env)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def check(status, name, detail, fix=""):
    results.append(status)
    print(f"[{status}] {name}: {detail}" + (f"\n        fix: {fix}" if fix and status != OK else ""))


def version(cmd, pattern=r"(\d+)\.(\d+)"):
    if not shutil.which(cmd[0]):
        return None
    rc, out = run(cmd)
    m = re.search(pattern, out)
    return tuple(int(x) for x in m.groups()) if rc == 0 and m else None


def lfs_pointers():
    """Tracked LFS files that are still pointer stubs (content not pulled)."""
    rc, out = run(["git", "-C", str(REPO), "lfs", "ls-files", "-n"])
    if rc:
        return None
    bad = []
    for rel in out.splitlines():
        p = REPO / rel
        if p.is_file() and p.stat().st_size < 200 and p.read_bytes().startswith(b"version https://git-lfs"):
            bad.append(rel)
    return bad


def agent_checks():
    """What an agent's sandbox blocks. Codex marks its sandboxed commands with CODEX_SANDBOX (seatbelt on macOS)."""
    sandbox = os.environ.get("CODEX_SANDBOX")
    agent = "Codex (sandboxed: " + sandbox + ")" if sandbox else "Claude Code" if os.environ.get("CLAUDECODE") else None
    if agent:
        check(OK, "agent", agent)
    rc, cache = run(["uv", "cache", "dir"])
    if rc == 0 and cache:
        try:
            Path(cache).mkdir(parents=True, exist_ok=True)
            tempfile.TemporaryFile(dir=cache).close()
            check(OK, "uv cache writable", cache)
        except OSError:
            check(FAIL, "uv cache writable", f"{cache} is read-only here, so every `uv run` fails",
                  f'Codex: add it to ~/.codex/config.toml: [sandbox_workspace_write] writable_roots = ["{cache}"]; '
                  "other sandboxes: allow writes there, or set UV_CACHE_DIR inside the workspace")
    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED"):
        check(WARN, "network", "disabled in this sandbox: first runs that download Python, bpy or packages will fail",
              "run `roomwright doctor --full` once outside the sandbox (it fills uv's cache), or set "
              "[sandbox_workspace_write] network_access = true")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="also install and import bpy (slow the first time)")
    a = ap.parse_args()
    print(f"roomwright engine at {REPO}\n")
    v = version(["uv", "--version"])
    check(OK if v and v >= (0, 5) else FAIL, "uv", f"{'.'.join(map(str, v))}" if v else "not found",
          "install uv: https://docs.astral.sh/uv/getting-started/installation/")
    v = version(["git", "--version"])
    check(OK if v else WARN, "git", ".".join(map(str, v)) if v else "not found (optional: history and backups)", "install git")
    v = version(["git", "lfs", "version"])
    if not v:
        check(WARN, "git lfs", "not installed (optional; needed to keep scans and photos in git, and to clone a repo that has them)",
              "install git-lfs, then `git lfs install && git lfs pull`")
    else:
        bad = lfs_pointers()
        if bad is None:
            check(WARN, "git lfs", "installed; could not list LFS files (not a git checkout?)")
        elif bad:
            check(FAIL, "git lfs content", f"{len(bad)} file(s) are LFS pointers, e.g. {bad[0]}", "`git lfs pull`")
        else:
            check(OK, "git lfs", "installed, content pulled")
    v = version(["node", "--version"], r"v(\d+)\.(\d+)")
    check(OK if v and v >= (18, 0) else WARN, "node", "v" + ".".join(map(str, v)) if v else "not found",
          "install Node 18+ (layout checker `tools/check_layout.mjs`, ceiling model grid, tests)")
    rc, out = run(["uv", "python", "find", "--system", "3.11"])
    check(OK if rc == 0 else WARN, "python 3.11 (for bpy)", out.splitlines()[-1] if rc == 0 else "not installed yet",
          "`uv python install 3.11` (uv also does this on the first render)")
    agent_checks()
    if a.full:
        rc, out = run(["uv", "run", "--no-project", "--python", "3.11", "--with", "bpy==4.5.*", "--with", "numpy<2", "python", "-c",
                       "import bpy; print(bpy.app.version_string)"])
        crashed = rc in (139, -11)
        check(OK if rc == 0 else FAIL, "bpy (Blender as a Python module)",
              "crashed on import (SIGSEGV)" if crashed else out.splitlines()[-1] if out else "?",
              "Blender can't start inside this sandbox (Codex on macOS hides the Metal GPU from it): run the render tools "
              "outside the sandbox (approve them) or give the project full access; see docs/AGENT_SETUP.md" if crashed else
              "bpy wheels exist for macOS (arm64/x86_64), Linux x86_64 and Windows; see https://pypi.org/project/bpy/")
    else:
        check(OK, "bpy", "not checked (run with --full)")
    chrome = next((c for c in ("google-chrome", "chromium", "chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                   if shutil.which(c) or Path(c).exists()), None)
    check(OK if chrome else WARN, "chrome (optional: PDF export, editor screenshots)", chrome or "not found", "install Chrome or set CHROME=/path/to/chrome")
    check(OK if shutil.which("modal") or (Path.home() / ".modal.toml").exists() else WARN, "modal (optional: cloud GPU renders)",
          "configured" if (Path.home() / ".modal.toml").exists() else "not set up", "`uv tool install modal && modal setup`")
    fails = results.count(FAIL)
    print(f"\n{fails} problem(s), {results.count(WARN)} warning(s)" if fails or WARN in results else "\nall good")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
