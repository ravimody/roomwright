# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render several photoreal sets locally, one render_photoreal.py run per (layout, lighting).

Usage, from inside rooms/<room>/:
  uv run ../../tools/render_batch.py render_sets/<name>.json [--samples 48] [--res 1400x875] [--only tag1,tag2] [--show] [--dry-run]

The sets file is the same format as `modal run tools/render_modal.py --batch` (a list), so one file serves both:
  [{"layout": "proposal", "lighting": "day,evening", "views": "a,b", "tag": "zones"}, ...]
- "lighting" may list several scenes; each gets its own folder.
- Output folder: "tag" when one lighting is given, else "<tag or layout>-<lighting>" (as on Modal).
- "views" defaults to every camera in room.json; "samples"/"res" in a set override the command line.
- "room" is accepted (Modal needs it) and must match the current folder when present.
- "meterLayout": meter the auto exposure on another layout (e.g. today's), so a proposal renders at today's exposure
  and the difference shows (render_modal.py --batch does the same).
--show opens each finished folder in the system image viewer.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from roomframe import show  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("sets")
ap.add_argument("--samples", type=int, default=48)
ap.add_argument("--res", default="1400x875")
ap.add_argument("--only", help="comma-separated output folders to render (skip the rest)")
ap.add_argument("--show", action="store_true")
ap.add_argument("--dry-run", action="store_true", help="print the commands only")
a = ap.parse_args()

if not Path("room.json").exists():
    sys.exit("run from inside rooms/<room>/ (no room.json here)")
sets = json.loads(Path(a.sets).read_text())
room = Path.cwd().name
only = set(a.only.split(",")) if a.only else None
failed = []
for st in sets:
    if st.get("room") and st["room"] != room:
        sys.exit(f"set for room {st['room']!r} but the current folder is {room!r}")
    if not Path(f"layouts/{st['layout']}.json").exists():
        print(f"SKIP {st['layout']}: no layouts/{st['layout']}.json")
        failed.append(st["layout"])
        continue
    lights = st.get("lighting", "standard").split(",")  # the same default as render_photoreal.py
    for lt in lights:
        tag = st["tag"] if st.get("tag") and len(lights) == 1 else f"{st.get('tag') or st['layout']}-{lt}"
        if only and tag not in only:
            continue
        cmd = ["uv", "run", str(TOOLS / "render_photoreal.py"), st["layout"], "--lighting", lt, "--tag", tag,
               "--samples", str(st.get("samples", a.samples)), "--res", st.get("res", a.res)]
        if st.get("views"):
            cmd += ["--views", st["views"]]
        if st.get("meterLayout"):
            cmd += ["--meter-layout", st["meterLayout"]]
        print(" ".join(cmd), flush=True)
        if a.dry_run:
            continue
        r = subprocess.run(cmd, check=False)
        if r.returncode:
            failed.append(tag)
        elif a.show:
            show(sorted(Path(f"renders/photoreal/{tag}").glob("*.png")))
if failed:
    sys.exit(f"failed or skipped: {', '.join(failed)}")
