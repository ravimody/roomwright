# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10.1", "pillow-heif"]
# ///
"""1:1 sheets of the owner's photos next to the model rendered from the same camera.

Each camera in room.json with a "photo" key (set when the camera was recovered from that photo with
tools/photo_match.py) gets PHOTO | MODEL, the model taken from a photoreal render folder that has a PNG for that camera.

Usage, from inside rooms/<room>/:
  uv run ../../tools/photo_compare.py <photoreal-folder> [camera ...] [--out renders/photo_compare] [--height 900] [--show]

Typical run: render the photo cameras first, e.g.
  uv run ../../tools/render_photoreal.py <today-layout> --lighting <night-scene> --views photo_1,photo_2 --tag photo-compare
  uv run ../../tools/photo_compare.py renders/photoreal/photo-compare
Writes <out>/<photo-stem>.jpg per camera and <out>/all.jpg (every sheet stacked).
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
from pillow_heif import register_heif_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roomframe import font, show

register_heif_opener()
ap = argparse.ArgumentParser()
ap.add_argument("folder", help="photoreal render folder, e.g. renders/photoreal/photo-compare")
ap.add_argument("cameras", nargs="*", help="cameras to include (default: every camera with a photo and a render)")
ap.add_argument("--out", default="renders/photo_compare")
ap.add_argument("--height", type=int, default=900, help="height of each image in the sheet (px)")
ap.add_argument("--show", action="store_true")
a = ap.parse_args()

if not Path("room.json").exists():
    sys.exit("run from inside rooms/<room>/ (no room.json here)")
cams = json.loads(Path("room.json").read_text()).get("cameras", {})
folder, out = Path(a.folder), Path(a.out)
names = a.cameras or [n for n, c in cams.items() if c.get("photo") and (folder / f"{n}.png").exists()]
if not names:
    sys.exit(f"no camera has both a room.json 'photo' and a render in {folder}")
out.mkdir(parents=True, exist_ok=True)
F, PAD, HEAD = font(26), 12, 48
sheets = []
for n in names:
    c = cams.get(n) or sys.exit(f"{n}: not a room.json camera")
    if not c.get("photo"):
        sys.exit(f"{n}: the camera has no 'photo' key")
    photo = ImageOps.exif_transpose(Image.open(c["photo"])).convert("RGB")
    model = Image.open(folder / f"{n}.png").convert("RGB")
    H = a.height
    photo = photo.resize((round(photo.width * H / photo.height), H), Image.LANCZOS)
    model = model.resize((round(model.width * H / model.height), H), Image.LANCZOS)
    sheet = Image.new("RGB", (photo.width + model.width + PAD, H + HEAD), "white")
    sheet.paste(photo, (0, HEAD))
    sheet.paste(model, (photo.width + PAD, HEAD))
    d = ImageDraw.Draw(sheet)
    d.text((8, 10), f"PHOTO  {Path(c['photo']).stem}", fill="black", font=F)
    d.text((photo.width + PAD + 8, 10), f"MODEL  {folder.name}, camera {n} (recovered from the photo)", fill="black", font=F)
    path = out / f"{Path(c['photo']).stem}.jpg"
    sheet.save(path, quality=88)
    sheets.append(sheet)
    print("wrote", path)
W = max(s.width for s in sheets)
stack = Image.new("RGB", (W, sum(s.height for s in sheets) + PAD * (len(sheets) - 1)), "white")
y = 0
for s in sheets:
    stack.paste(s, (0, y))
    y += s.height + PAD
stack.save(out / "all.jpg", quality=85)
print("wrote", out / "all.jpg")
if a.show:
    show([out / "all.jpg"])
