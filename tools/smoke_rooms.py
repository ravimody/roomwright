# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Stress-test the engine on every room: run each pipeline step that applies to a room and summarise pass/fail,
timings and the key numbers (validation errors, layout issues, geometry agreement, render brightness).

Usage (from the repo root, or anywhere with a rooms/ folder):
  uv run tools/smoke_rooms.py [room ...] [--fast] [--layout as-scanned] [--out smoke.md]

Steps per room (skipped when they don't apply):
  validate      tools/validate_room.py
  layouts       tools/check_layout.mjs on every layout (errors are reported, not failures: proposals can break rules)
  flow          tools/flow_plan.py <layout> when room.json has "flow"
  speakers      tools/speaker_plan.py <layout> when the layout has "listening"
  geometry      tools/geometry_check.py <layout> (Blender; skipped with --fast): worst view agreement
  render        tools/render_photoreal.py <layout>, first camera, 4 samples, 240 px (Blender; skipped with --fast)
Outputs go to each room's renders/_smoke/ (git-ignored), so tracked files stay untouched. Writes a Markdown table to --out (default: stdout only) and exits 1 if any step failed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("rooms", nargs="*")
ap.add_argument("--fast", action="store_true", help="skip the Blender steps (geometry check, render)")
ap.add_argument("--layout", default="as-scanned", help="layout to check and render (falls back to the first layout)")
ap.add_argument("--rooms-dir", default="rooms")
ap.add_argument("--out")
a = ap.parse_args()

root = Path(a.rooms_dir)
rooms = [root / r for r in a.rooms] if a.rooms else sorted(p for p in root.iterdir() if (p / "room.json").exists() and not p.name.startswith("_"))
rows, failed = [], 0


def step(room, name, cmd, parse=None, timeout=1800):
    """Run one tool inside the room folder; returns (ok, note)."""
    t = time.time()
    try:
        r = subprocess.run(cmd, cwd=room, capture_output=True, text=True, timeout=timeout, check=False, env={**os.environ, "NO_OPEN": "1"})
        out, ok = r.stdout + r.stderr, r.returncode == 0
    except subprocess.TimeoutExpired:
        out, ok = "timeout", False
    note = parse(out, ok) if parse else ""
    if not ok and not note:
        note = (out.strip().splitlines() or ["(no output)"])[-1][:120]
    rows.append((room.name, name, "ok" if ok else "FAIL", f"{time.time() - t:.0f}s", note))
    print(f"{room.name:18s} {name:10s} {'ok' if ok else 'FAIL':4s} {time.time() - t:5.0f}s  {note}", flush=True)
    return ok


for room in rooms:
    rj = json.loads((room / "room.json").read_text())
    layouts = sorted((room / "layouts").glob("*.json"))
    lay = next((p.stem for p in layouts if p.stem == a.layout), layouts[0].stem if layouts else None)
    ok = step(room, "validate", ["uv", "run", "-q", str(TOOLS / "validate_room.py")],
              lambda o, _: (re.findall(r"\d+ error\(s\), \d+ warning\(s\)", o) or [""])[-1])
    failed += not ok
    errs = 0
    for lp in layouts:
        r = subprocess.run(["node", str(TOOLS / "check_layout.mjs"), f"layouts/{lp.name}"], cwd=room, capture_output=True, text=True, check=False)
        if r.returncode not in (0, 1) or "Error:" in r.stderr:
            failed += 1
            rows.append((room.name, f"layout {lp.stem}", "FAIL", "", r.stderr.strip().splitlines()[-1][:120] if r.stderr.strip() else "crash"))
        errs += r.returncode == 1
    rows.append((room.name, "layouts", "ok", "", f"{len(layouts)} layouts, {errs} with rule errors"))
    print(f"{room.name:18s} layouts    ok           {len(layouts)} layouts, {errs} with rule errors")
    if lay is None:
        continue
    if rj.get("flow"):
        failed += not step(room, "flow", ["uv", "run", "-q", str(TOOLS / "flow_plan.py"), lay, "--out", f"renders/_smoke/flow_{lay}.png"],
                           lambda o, _: f'{o.count(chr(34) + "ok" + chr(34) + ": false")} path(s) below their minimum width')
    if json.loads((room / "layouts" / f"{lay}.json").read_text()).get("listening"):
        failed += not step(room, "speakers", ["uv", "run", "-q", str(TOOLS / "speaker_plan.py"), lay, "--out", f"renders/_smoke/speakers_{lay}.png"])
    if a.fast:
        continue
    if (room / "scan/scan_aligned.glb").exists():
        def agreement(o, _):
            p = room / "renders/_smoke/geometry/report.json"
            if not p.exists():
                return ""
            views = json.loads(p.read_text()).get("views", {})
            vals = [v.get("agree") for v in (views.values() if isinstance(views, dict) else views) if isinstance(v, dict) and v.get("agree") is not None]
            return f"views agree {min(vals):.0%}–{max(vals):.0%}" if vals else ""
        failed += not step(room, "geometry", ["uv", "run", "-q", str(TOOLS / "geometry_check.py"), lay, "--res", "350x220", "--out", "renders/_smoke/geometry"], agreement)
    cams = list(rj.get("cameras", {}))
    if cams:
        def brightness(o, ok):
            png = room / f"renders/photoreal/_smoke/{cams[0]}.png"
            if not ok or not png.exists():
                return ""
            data = png.read_bytes()
            return f"{len(data) // 1024} KB" + (" (suspiciously small: black frame?)" if len(data) < 20_000 else "")
        failed += not step(room, "render", ["uv", "run", "-q", str(TOOLS / "render_photoreal.py"), lay, "--views", cams[0], "--samples", "4",
                                            "--res", "240x160", "--tag", "_smoke", "--lighting", "day" if "day" in rj.get("scenes", {}) or rj.get("exposure", {}).get("day") else "evening"], brightness)

table = "| room | step | result | time | notes |\n|---|---|---|---|---|\n" + "\n".join(f"| {' | '.join(r)} |" for r in rows)
if a.out:
    Path(a.out).write_text(f"# Smoke test, {time.strftime('%Y-%m-%d %H:%M')}\n\n{table}\n")
print(f"\n{failed} failure(s)")
sys.exit(1 if failed else 0)
