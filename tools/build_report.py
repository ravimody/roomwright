# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Copy the latest renders (and other images) into report/img as JPEGs for report/index.html.

Run from inside rooms/<room>/:
  uv run ../../tools/build_report.py

Reads report/build.json:
  {"images": {"<name>": "<photoreal folder>/<view>"},     -> renders/photoreal/<folder>/<view>.png -> report/img/<name>.jpg
   "copy":   {"<name>": "<path relative to the room>"}}   -> any other image (flow plans, speaker plans, textures)
Exits 1 if any source is missing.
"""

import json
import sys
from pathlib import Path

from PIL import Image

cfg = Path("report/build.json")
if not cfg.exists():
    sys.exit('no report/build.json here. Run from inside rooms/<room>/ and list the report images, e.g.\n'
             '  {"images": {"today_main": "today-day/main"}, "copy": {"flow_today": "renders/flow/as-scanned.png"}}')
conf = json.loads(cfg.read_text())
out = Path("report/img")
out.mkdir(parents=True, exist_ok=True)
missing = 0
jobs = [(name, Path(f"renders/photoreal/{rel}.png"), 88) for name, rel in conf.get("images", {}).items()]
jobs += [(name, Path(rel), 90) for name, rel in conf.get("copy", {}).items()]
for name, src, quality in jobs:
    if src.exists():
        Image.open(src).convert("RGB").save(out / f"{name}.jpg", quality=quality)
        print("wrote", f"img/{name}.jpg")
    else:
        missing += 1
        print("missing", src)
sys.exit(1 if missing else 0)
