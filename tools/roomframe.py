"""Shared room-frame helpers for the measurement tools (run from inside rooms/<room>/ or set ROOM=).

Room frame: x east, y north, z up, meters, origin at the room's SW interior corner.
room.json["scan"]["alignedOrigin"] is where that corner sits inside scan/scan_aligned.glb
(Blender Z-up coords; glTF stores Y-up, so glTF (x, y, z) = Blender (x, z, -y)).
"""

import json
import os
from pathlib import Path

ROOM = Path(os.environ.get("ROOM", ".")).resolve()
ENGINE = Path(__file__).resolve().parent.parent  # tools/, editor/, shared/, schema/


def household_root(room_dir=None):
    """The household folder of a room: the folder holding its rooms/ (rooms/<room> -> the repo root,
    examples/rooms/<room> -> examples/). It holds HOUSEHOLD.md, catalog.json, builders/ and models/. None if the room
    isn't under a rooms/ folder."""
    d = Path(room_dir or ROOM).resolve()
    return d.parent.parent if d.parent.name == "rooms" else None


def load_catalog(room_dir=None):
    """Item types for a room: the engine's shared/catalog.json (generic entries), then the household's catalog.json,
    then the room's own catalog.json; later entries win."""
    rd = Path(room_dir or ROOM).resolve()
    hh = household_root(rd)
    cat = {}
    for p in (ENGINE / "shared/catalog.json", hh / "catalog.json" if hh else None, rd / "catalog.json"):
        if p and p.exists():
            cat.update(json.loads(p.read_text())["items"])
    return cat


def asset_path(rel, room_dir=None):
    """A file named in room data (a texture, a model): relative to the room folder if it is there, else to the
    household folder (shared models/ and textures)."""
    rd = Path(room_dir or ROOM).resolve()
    p = rd / rel
    hh = household_root(rd)
    if not p.exists() and hh and (hh / rel).exists():
        return hh / rel
    return p


def room_json():
    return json.loads((ROOM / "room.json").read_text())


def origin():
    """(OX, OY): room origin inside the aligned scan."""
    return tuple(room_json()["scan"]["alignedOrigin"])


def extents():
    """(x0, y0, x1, y1) bounding box of the room outline."""
    pts = room_json()["outline"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def scan_mesh():
    """trimesh mesh of the aligned scan, converted to the room frame (Z up)."""
    import numpy as np
    import trimesh

    ox, oy = origin()
    g = trimesh.load(ROOM / "scan/scan_aligned.glb").to_geometry()
    v = g.vertices
    g.vertices = np.c_[v[:, 0] - ox, -v[:, 2] - oy, v[:, 1]]
    return g


def show(paths):
    """Open files in the system viewer (Preview on macOS, xdg-open on Linux). NO_OPEN=1 disables it (CI, agents
    working headless)."""
    import subprocess
    import sys

    paths = [str(p) for p in paths]
    if not paths or os.environ.get("NO_OPEN"):
        return
    if sys.platform == "darwin":
        subprocess.run(["open", *paths], check=False)
    elif sys.platform.startswith("win"):
        for p in paths:
            os.startfile(p)  # type: ignore[attr-defined]
    else:
        for p in paths:
            subprocess.run(["xdg-open", p], check=False)


def font(size=15):
    """A TrueType font for labels on any OS (Helvetica on macOS, DejaVu/Liberation on Linux, Arial on Windows), else
    Pillow's scalable default (Pillow >= 10.1)."""
    from PIL import ImageFont

    for path in ("/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                 "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------- geometry shared by the render and check tools


def normalize_room(room):
    """Fill room.json's optional lists (doors, windows, fixtures, ceiling downstands) so code can iterate them, and map
    the `downlights` keys (lights.downlights, a scene's downlights) to `cans`, the name the code uses; returns the same
    dict."""
    for k in ("doors", "windows", "fixtures"):
        room.setdefault(k, [])
    room.setdefault("ceiling", {}).setdefault("downstands", [])
    for d in [room.get("lights") or {}, *[s for s in (room.get("scenes") or {}).values() if isinstance(s, dict)]]:
        if "downlights" in d:
            d.setdefault("cans", d.pop("downlights"))
    return room


def point_in_poly(p, poly):
    """Even-odd test of plan point p = (x, y) against a polygon [(x, y), ...]."""
    x, y, inside = p[0], p[1], False
    for (x0, y0), (x1, y1) in zip(poly, list(poly[1:]) + list(poly[:1])):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def ceiling_z(room, x, y):
    """Ceiling height at plan point (x, y): the lowest downstand over it (flat, or sloped along x or y), else the top."""
    c = room["ceiling"]
    z = c["top"]
    for d in c.get("downstands", []):
        if "rect" in d:
            x0, y0, x1, y1 = d["rect"]
            inside = min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)
        else:
            inside = point_in_poly((x, y), d["poly"])
        if not inside:
            continue
        s = d.get("slope")
        if s:
            t = min(max(x if s["axis"] == "x" else y, s["from"]), s["to"])
            z = min(z, s["zFrom"] + (s["zTo"] - s["zFrom"]) * (t - s["from"]) / (s["to"] - s["from"]))
        else:
            z = min(z, d["z"])
    return z


def wall_line(room, wall, s):
    """Where the named wall's face is at position s along it (x for north/south, y for east/west): the outline edge
    facing that way that covers s (the outermost if several), else the outline's bounding box. Handles stepped walls,
    bays and chimney breasts."""
    pts = [tuple(p) for p in room["outline"]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    box, ax, sgn = {"north": (max(ys), "y", 1), "south": (min(ys), "y", -1), "east": (max(xs), "x", 1), "west": (min(xs), "x", -1)}[wall]
    hits = []
    for (ax_, ay_), (bx_, by_) in zip(pts, pts[1:] + pts[:1]):
        nx_, ny_ = by_ - ay_, -(bx_ - ax_)  # outward normal of a CCW outline edge
        if ax == "y" and abs(ay_ - by_) < 1e-6 and ny_ * sgn > 0 and min(ax_, bx_) - 1e-6 <= s <= max(ax_, bx_) + 1e-6:
            hits.append(ay_)
        if ax == "x" and abs(ax_ - bx_) < 1e-6 and nx_ * sgn > 0 and min(ay_, by_) - 1e-6 <= s <= max(ay_, by_) + 1e-6:
            hits.append(ax_)
    return (max(hits) if sgn > 0 else min(hits)) if hits else box


# ---------------------------------------------------------------- cameras (room.json "cameras" entries)
# One convention everywhere (render_photoreal, scan_compare, geometry_check, photo_match, color checks): Blender's
# (target - eye).to_track_quat("-Z", "Y") (level horizon), then a rotation of -roll degrees about the camera's own
# Z axis (photo_match fits roll in this convention), a 36 mm sensor fitted to the longer side of the frame (Blender's
# AUTO sensor fit), lens in mm.

SENSOR = 36.0


def _norm(v):
    n = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def camera_axes(eye, target, roll=0.0):
    """(right, up, back) unit vectors of a camera at `eye` looking at `target`: the columns of its world rotation.
    Same as Blender's to_track_quat("-Z", "Y") followed by a rotation of -roll degrees about the local Z axis."""
    import math

    d = _norm((target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]))
    back = (-d[0], -d[1], -d[2])
    if abs(d[0]) < 1e-9 and abs(d[1]) < 1e-9:  # straight up/down: Blender keeps local Y along world Y
        up0 = (0.0, 1.0 if d[2] < 0 else -1.0, 0.0)
        right0 = _norm(_cross(up0, back))
    else:
        right0 = _norm(_cross(d, (0.0, 0.0, 1.0)))
        up0 = _cross(back, right0)
    a = math.radians(-roll)
    c, s = math.cos(a), math.sin(a)
    right = tuple(c * r + s * u for r, u in zip(right0, up0))
    up = tuple(-s * r + c * u for r, u in zip(right0, up0))
    return right, up, back


def camera(cam):
    """Normalise a room.json camera entry: (eye, target, lens, roll)."""
    return tuple(cam["eye"]), tuple(cam["target"]), float(cam["lens"]), float(cam.get("roll", 0.0))


def apply_camera(obj, cam, offset=(0.0, 0.0, 0.0)):
    """Point a Blender camera object at a room.json camera (eye, target, lens, roll); `offset` shifts it into another
    frame (e.g. the aligned scan's: (OX, OY, 0))."""
    import math

    from mathutils import Quaternion, Vector

    eye, target, lens, roll = camera(cam)
    obj.location = Vector(eye) + Vector(offset)
    obj.rotation_mode = "XYZ"
    # exactly the construction camera_axes() reproduces (kept bit-for-bit, so renders don't drift)
    q = (Vector(target) - Vector(eye)).to_track_quat("-Z", "Y") @ Quaternion((0, 0, 1), math.radians(-roll))
    obj.rotation_euler = q.to_euler()
    obj.data.lens = lens
    obj.data.sensor_width = SENSOR
    obj.data.sensor_fit = "AUTO"


def camera_rays(cam, w, h):
    """Unit ray directions (h*w x 3 numpy array, rows top to bottom) through pixel centres of a w x h frame, matching
    a Blender render of the same camera (36 mm sensor fitted to the longer side)."""
    import numpy as np

    eye, target, lens, roll = camera(cam)
    r, u, b = (np.array(v) for v in camera_axes(eye, target, roll))
    half = SENSOR / 2 / lens
    hx, hy = (half, half * h / w) if w >= h else (half * w / h, half)
    us = ((np.arange(w) + 0.5) / w * 2 - 1) * hx
    vs = (1 - (np.arange(h) + 0.5) / h * 2) * hy
    U, V = np.meshgrid(us, vs)
    d = U[..., None] * r + V[..., None] * u - b
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    return d.reshape(-1, 3)


def check_views(room, names, key="cameras"):
    """Fail with a helpful message when a view name isn't a camera in room.json."""
    import sys

    cams = room.get(key, {})
    bad = [n for n in names if n not in cams]
    if bad or not names:
        sys.exit(f"unknown view(s) {', '.join(bad) or '(none given)'}; room.json {key}: {', '.join(cams) or '(none: add cameras first)'}")


# ---------------------------------------------------------------- files


def is_lfs_pointer(path):
    """True when `path` is a Git LFS pointer (the clone has no LFS content) instead of the real file."""
    try:
        with open(path, "rb") as f:
            return f.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


def require_file(path, what="file"):
    """Exit with a clear message when a needed file is missing or still an LFS pointer."""
    import sys

    p = Path(path)
    if not p.exists():
        sys.exit(f"missing {what}: {p}")
    if is_lfs_pointer(p):
        sys.exit(f"{p} is a Git LFS pointer, not the {what}: run `git lfs install && git lfs pull` in the repo")
    return p


# ---------------------------------------------------------------- photos


def load_photo(path):
    """A photo as an upright RGB PIL image. HEIC/HEIF via pillow-heif when installed (any OS), else macOS `sips`."""
    from PIL import Image, ImageOps

    p = require_file(path, "photo")
    if p.suffix.lower() in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except ImportError:
            import shutil
            import subprocess
            import sys
            import tempfile

            if not shutil.which("sips"):
                sys.exit(f"{p}: reading HEIC needs pillow-heif (the tools that read photos declare it) or macOS sips")
            jpg = Path(tempfile.mkdtemp()) / (p.stem + ".jpg")
            subprocess.run(["sips", "-s", "format", "jpeg", str(p), "--out", str(jpg)], check=True, capture_output=True)
            p = jpg
    return ImageOps.exif_transpose(Image.open(p)).convert("RGB")


def photo_f35(path):
    """35 mm-equivalent focal length from the photo's EXIF (FocalLengthIn35mmFilm), or None."""
    from PIL import Image

    p = Path(path)
    if p.suffix.lower() in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except ImportError:
            return None
    try:
        exif = Image.open(p).getexif()
    except OSError:
        return None
    v = exif.get_ifd(0x8769).get(0xA405) or exif.get(0xA405)
    return float(v) if v else None


def photo_ev100(path):
    """Exposure value at ISO 100 from the photo's EXIF (ExposureTime, FNumber, ISOSpeedRatings), or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    p = Path(path)
    if p.suffix.lower() in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except ImportError:
            return None
    try:
        ex = Image.open(p).getexif().get_ifd(0x8769)
    except OSError:
        return None
    t, n, iso = ex.get(0x829A), ex.get(0x829D), ex.get(0x8827)
    if isinstance(iso, tuple):
        iso = iso[0]
    if not (t and n and iso):
        return None
    import photometry

    return photometry.ev100(float(t), float(n), float(iso))


def lens_from_f35(f35, width, height):
    """Blender lens (mm; 36 mm sensor fitted to the long side) for a photo's 35 mm-equivalent focal length. The 35 mm
    equivalent is defined on the diagonal (43.27 mm), so the factor depends on the aspect: 1.04 for 4:3, 1.00 for 3:2,
    0.955 for 16:9."""
    long_, short = max(width, height), min(width, height)
    return f35 * SENSOR * (1 + (short / long_) ** 2) ** 0.5 / 43.267
