# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1", "pillow-heif", "scipy"]
# ///
"""Recover the camera of a real photo of the room, so model renders can be compared 1:1 with it.

Renders the textured scan (flat Workbench, fast) from a candidate camera at low resolution, scores how well its edges
line up with the photo's, and searches the camera's position and aim (yaw, pitch, roll) from a rough starting guess.
The focal length comes from the photo: its 35 mm-equivalent (EXIF FocalLengthIn35mmFilm, read automatically; or pass
--f35) is converted for the photo's aspect (Blender lens = f35 x 1.04 for 4:3, 1.00 for 3:2, 0.955 for 16:9; 36 mm
sensor across the long side). Edges, not colours, are compared, so night photos with mixed light still match the
flat-lit scan. Photos may be JPEG, PNG or HEIC.

Usage, from inside rooms/<room>/:
  uv run ../../tools/photo_match.py <photo> --eye x,y,z --target x,y,z [--f35 24] [--points landmarks.json]
      [--fit-lens] [--name n] [--iters 400] [--out renders/photo_match]

Writes <out>/<name>.json ({"eye", "target", "lens", "roll", "score", "portrait"}) and <out>/<name>_overlay.jpg (photo,
scan from the found camera, and a blend) to check by eye. Copy eye/target/lens/roll into a room.json camera entry:
render_photoreal, scan_compare and geometry_check all apply roll the same way (roomframe.apply_camera). A wrong start
can lock onto a similar-looking wall: check the overlay.
"""

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

import roomframe
from roomframe import origin

ap = argparse.ArgumentParser()
ap.add_argument("photo")
ap.add_argument("--f35", type=float, help="35 mm-equivalent focal length (default: the photo's EXIF FocalLengthIn35mmFilm)")
ap.add_argument("--eye", required=True)
ap.add_argument("--target", required=True)
ap.add_argument("--points", help="landmarks JSON: [[u, v, x, y, z], ...], u/v in pixels of the photo scaled to 1200 px on its long side; solves the camera from them first (robust where edges mislead: mirrors, changed rooms)")
ap.add_argument("--roll", type=float, default=0.0)
ap.add_argument("--fit-lens", action="store_true", help="also fit the focal length from the landmarks (needs 6+ points)")
ap.add_argument("--name")
ap.add_argument("--iters", type=int, default=400)
ap.add_argument("--width", type=int, default=200, help="working resolution (long side)")
ap.add_argument("--out", default="renders/photo_match")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--starts", type=int, default=40, help="random starts around the guess for the coarse search")
a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])

out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
name = a.name or Path(a.photo).stem
photo = roomframe.load_photo(a.photo)
portrait = photo.height > photo.width
W = a.width if not portrait else round(a.width * photo.width / photo.height)
H = round(W * photo.height / photo.width)
f35 = a.f35 or roomframe.photo_f35(a.photo)
if not f35:
    sys.exit(f"{a.photo}: no FocalLengthIn35mmFilm in its EXIF; pass --f35 (24 for an iPhone main camera, 13-14 ultra-wide)")
lens = roomframe.lens_from_f35(f35, photo.width, photo.height)
print(f"{name}: f35 {f35:g} mm -> Blender lens {lens:.2f} mm ({photo.width}x{photo.height})")


SIG = [2.0]  # edge blur: wide for the coarse search, then tighter


def edges(im):
    g = ImageOps.equalize(im.convert("L").resize((W, H), Image.LANCZOS)).filter(ImageFilter.GaussianBlur(1.2))
    x = np.asarray(g, dtype=np.float32)
    gx, gy = np.zeros_like(x), np.zeros_like(x)
    gx[:, 1:-1], gy[1:-1, :] = x[:, 2:] - x[:, :-2], x[2:, :] - x[:-2, :]
    m = np.hypot(gx, gy)
    m = np.asarray(Image.fromarray(np.uint8(255 * m / (m.max() + 1e-6))).filter(ImageFilter.GaussianBlur(SIG[0])), dtype=np.float32)
    return (m - m.mean()) / (m.std() + 1e-6), (x - x.mean()) / (x.std() + 1e-6)



bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(roomframe.require_file("scan/scan_aligned.glb", "aligned scan")))
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "TEXTURE"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.5, 0.5, 0.5)
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.image_settings.file_format = "PNG"
cd = bpy.data.cameras.new("cam")
cd.lens, cd.clip_start, cd.sensor_width, cd.sensor_fit = lens, 0.05, 36, "AUTO"
cam = bpy.data.objects.new("cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam
OX, OY = origin()
tmp = out / f"_{name}.png"


def target_of(p):
    """Camera params (x, y, z, yaw, pitch, roll) -> a point 1 m ahead. yaw: heading in the plan (0 = +x, 90 = +y);
    pitch: up/down; roll: about the view axis, as render_photoreal applies it (roomframe.camera_axes)."""
    x, y, z, yaw, pitch, _ = p
    yw, pt = math.radians(yaw), math.radians(pitch)
    return (x + math.cos(yw) * math.cos(pt), y + math.sin(yw) * math.cos(pt), z + math.sin(pt))


def set_cam(p):
    roomframe.apply_camera(cam, {"eye": p[:3], "target": target_of(p), "lens": cd.lens, "roll": p[5]}, (OX, OY, 0))


def render(p, res=None):
    set_cam(p)
    if res:
        sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.filepath = str(tmp)
    bpy.ops.render.render(write_still=True)
    im = Image.open(tmp).convert("RGB")
    if res:
        sc.render.resolution_x, sc.render.resolution_y = W, H
    return im


REF = {}


def score(p):
    if SIG[0] not in REF:
        REF[SIG[0]] = edges(photo)
    P_edge, P_gray = REF[SIG[0]]
    e, g = edges(render(p))
    return float((e * P_edge).mean()) + 0.25 * float((g * P_gray).mean())


eye, tgt = [float(v) for v in a.eye.split(",")], [float(v) for v in a.target.split(",")]
d = [t - e for t, e in zip(tgt, eye)]
p = [*eye, math.degrees(math.atan2(d[1], d[0])), math.degrees(math.atan2(d[2], math.hypot(d[0], d[1]))), a.roll]
rnd = random.Random(a.seed)
if a.points:
    # camera from landmark correspondences: least-squares reprojection over position, heading, pitch, roll
    from scipy.optimize import least_squares

    pts = np.array(json.loads(Path(a.points).read_text()), dtype=float)
    Lp = 1200.0
    Wp, Hp = (Lp, Lp * photo.height / photo.width) if not portrait else (Lp * photo.width / photo.height, Lp)
    fpx = lens / 36.0 * Lp

    def resid(q):
        x, y, z, _, _, roll = q[:6]
        f_ = fpx * q[6] if len(q) > 6 else fpx
        R = np.array(roomframe.camera_axes((x, y, z), target_of(q[:6]), roll))  # rows: right, up, back
        out_ = []
        for u, v, X, Y, Z in pts:
            pc = R @ np.array((X - x, Y - y, Z - z))
            dz = max(-pc[2], 1e-3)
            out_ += [Wp / 2 + f_ * pc[0] / dz - u, Hp / 2 - f_ * pc[1] / dz - v]
        return out_

    best_sol = None
    for dyaw in (-30, -15, 0, 15, 30):  # a few headings: least squares is local
        for dpitch in (-10, 0, 10):
            q0 = p[:3] + [p[3] + dyaw, p[4] + dpitch, p[5]] + ([1.0] if a.fit_lens else [])
            sol = least_squares(resid, q0, x_scale=[0.5, 0.5, 0.3, 10, 5, 3] + ([0.1] if a.fit_lens else []), diff_step=1e-4)
            if best_sol is None or sol.cost < best_sol.cost:
                best_sol = sol
    q = list(best_sol.x)
    err = np.sqrt(np.mean(np.array(resid(q)) ** 2))
    if a.fit_lens:
        lens *= q[6]
        cd.lens = lens
        print(f"{name}: fitted lens {lens:.1f} mm (f35 ~ {f35 * q[6]:.1f})")
    p = q[:6]
    print(f"{name}: landmarks {len(pts)}, rms reprojection {err:.1f} px (of 1200)")
# 1) coarse: many starts around the guess (position +-0.4 m, heading +-25 deg, pitch +-10 deg), wide edge blur
SIG[0] = 4.0
cands = [p] + ([] if a.points else [[p[0] + rnd.uniform(-0.4, 0.4), p[1] + rnd.uniform(-0.4, 0.4), p[2] + rnd.uniform(-0.2, 0.2),
                p[3] + rnd.uniform(-25, 25), p[4] + rnd.uniform(-10, 10), p[5]] for _ in range(a.starts)])
scored = sorted(((score(c), c) for c in cands), key=lambda t: -t[0])[:3]


def refine(p, best, step, iters):
    fails = 0
    for _it in range(iters):
        q = [v + rnd.gauss(0, s) for v, s in zip(p, step)]
        q[2] = min(max(q[2], 0.3), 2.3)
        s = score(q)
        if s > best:
            p, best, fails = q, s, 0
        else:
            fails += 1
            if fails > 20:  # nothing better nearby: tighten the search
                step = [v * 0.6 for v in step]
                fails = 0
                if step[0] < 0.01:
                    break
    return p, best


# 2) refine the three best starts, coarse then fine, keep the winner
results = []
for s0, c in scored:
    SIG[0] = 4.0
    c, _ = refine(c, s0, [0.2, 0.2, 0.1, 5.0, 3.0, 2.0], a.iters // 6)
    SIG[0] = 2.0
    c, sc_ = refine(c, score(c), [0.08, 0.08, 0.05, 2.0, 1.5, 1.0], a.iters // 6)
    results.append((sc_, c))
best, p = max(results, key=lambda t: t[0])
print(f"{name}: score {best:.3f} eye ({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}) yaw {p[3]:.1f} pitch {p[4]:.1f} roll {p[5]:.1f}")

yaw, pitch = math.radians(p[3]), math.radians(p[4])
target = [p[0] + math.cos(yaw) * math.cos(pitch), p[1] + math.sin(yaw) * math.cos(pitch), p[2] + math.sin(pitch)]
res = {"eye": [round(v, 3) for v in p[:3]], "target": [round(v, 3) for v in target], "lens": round(lens, 1), "roll": round(p[5], 1),
       "score": round(best, 3), "portrait": portrait, "photo": str(a.photo)}
(out / f"{name}.json").write_text(json.dumps(res, indent=2) + "\n")
big = (900, round(900 * H / W)) if not portrait else (round(900 * W / H), 900)
scan = render(p, big)
ph = photo.resize(big)
o = Image.new("RGB", (big[0] * 3 + 20, big[1]), "white")
o.paste(ph, (0, 0))
o.paste(scan, (big[0] + 10, 0))
o.paste(Image.blend(ph, scan, 0.5), (2 * big[0] + 20, 0))
o.save(out / f"{name}_overlay.jpg", quality=85)
tmp.unlink(missing_ok=True)
