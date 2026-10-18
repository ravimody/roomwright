# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow"]
# ///
"""Recover a rug (or any floor covering) texture from the textured scan: top-down orthographic view with everything
above the rug clipped away, then fill the occluded parts using the rug's mirror symmetry.

Run from inside rooms/<room>/:
  uv run ../../tools/rug_from_scan.py snap x0 x1 y0 y1 [--clip 0.03] [--ppm 300]
      -> renders/rug/top_<x0>_<y0>_<x1>_<y1>.png: raw top-down of that room-coordinate rectangle, to find the rug's edges
  uv run ../../tools/rug_from_scan.py rug x0 x1 y0 y1 --out textures/rug-x.jpg [--sym xy|x|y|none]
        [--corners "x,y x,y x,y x,y"] [--size W,H]
      -> the rug rectangle, holes (under furniture) filled from the mirrored quadrants, then diffused.
         Phone scans drift, so a rug can come out as a slightly skewed quadrilateral: pass its corners in room coords
         (TL, TR, BR, BL as seen from above, north up) and its true size in metres to rectify it first.

Room coords as in room.json (x east, y north, metres). The scan is placed with room.json scan.alignedOrigin, as in
scan_compare.py. "Holes" are pixels where the clipped scan has no surface (magenta background) or where furniture
skirts survive the clip; the fill takes the first mirror image that is valid (x-flip, y-flip, both), so a 2-fold
symmetric medallion rug comes back almost whole. Whatever is still missing is filled by repeated blurring.
"""

import argparse
import json
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

import bmesh
import numpy as np
from PIL import Image, ImageFilter

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["snap", "rug"])
ap.add_argument("x0", type=float)
ap.add_argument("x1", type=float)
ap.add_argument("y0", type=float)
ap.add_argument("y1", type=float)
ap.add_argument("--clip", type=float, default=0.03, help="drop scan faces higher than this above the floor (m)")
ap.add_argument("--ppm", type=int, default=300, help="pixels per metre")
ap.add_argument("--sym", default="xy", choices=["xy", "x", "y", "none"])
ap.add_argument("--out")
ap.add_argument("--corners", help='rug corners in room coords, "x,y x,y x,y x,y" = TL TR BR BL (north up)')
ap.add_argument("--size", help="true rug size W,H in metres (x by y) for the rectified texture")
ap.add_argument("--center", default="0.5,0.5", help="symmetry centre (the medallion) as fractions u,v of the rug image")
ap.add_argument("--bad", default="", help='extra regions to re-fill (smeared scan), "u0,v0,u1,v1 ..." as image fractions')
args = ap.parse_args()
if args.corners and not args.size:
    ap.error("--corners needs --size W,H")

room = json.loads(Path("room.json").read_text())
OX, OY = room["scan"]["alignedOrigin"]
x0, x1, y0, y1 = args.x0, args.x1, args.y0, args.y1
W, H = round((x1 - x0) * args.ppm), round((y1 - y0) * args.ppm)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath="scan/scan_aligned.glb")
for ob in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
    me = ob.data
    me.transform(ob.matrix_world)
    ob.matrix_world.identity()
    bm = bmesh.new()
    bm.from_mesh(me)
    cx0, cx1, cy0, cy1 = x0 + OX - 0.05, x1 + OX + 0.05, y0 + OY - 0.05, y1 + OY + 0.05
    drop = [f for f in bm.faces if max(v.co.z for v in f.verts) > args.clip
            or not all(cx0 <= v.co.x <= cx1 and cy0 <= v.co.y <= cy1 for v in f.verts)]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    bm.to_mesh(me)
    bm.free()

sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "TEXTURE"
sc.view_settings.view_transform = "Standard"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (1, 0, 1)
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
cd = bpy.data.cameras.new("top")
cd.type = "ORTHO"
cd.ortho_scale = max(x1 - x0, y1 - y0)
cam = bpy.data.objects.new("top", cd)
sc.collection.objects.link(cam)
sc.camera = cam
cam.location = ((x0 + x1) / 2 + OX, (y0 + y1) / 2 + OY, 3.0)  # looking straight down, +y (north) up in the image
cam.rotation_euler = (0, 0, 0)
out_dir = Path("renders/rug")
out_dir.mkdir(parents=True, exist_ok=True)
raw = out_dir / f"top_{x0:g}_{y0:g}_{x1:g}_{y1:g}.png"
sc.render.filepath = str(raw)
bpy.ops.render.render(write_still=True)
print("wrote", raw)
if args.mode == "snap":
    raise SystemExit

shot = Image.open(raw).convert("RGB")
if args.corners:  # perspective-rectify the skewed quad to a W x H rectangle
    rw, rh = (float(v) for v in args.size.split(","))
    src = [((float(a) - x0) * args.ppm, (y1 - float(b)) * args.ppm) for a, b in (c.split(",") for c in args.corners.split())]
    ow, oh = round(rw * args.ppm), round(rh * args.ppm)
    dst_pts = [(0, 0), (ow, 0), (ow, oh), (0, oh)]
    A = []
    for (u, v), (x, y) in zip(dst_pts, src):  # coefficients mapping output (u, v) -> input (x, y)
        A.append([u, v, 1, 0, 0, 0, -x * u, -x * v])
        A.append([0, 0, 0, u, v, 1, -y * u, -y * v])
    coef = np.linalg.solve(np.array(A, float), np.array([c for xy in src for c in xy], float))
    shot = shot.transform((ow, oh), Image.Transform.PERSPECTIVE, tuple(coef), Image.Resampling.NEAREST, fillcolor=(255, 0, 255))
shot.save(out_dir / "rectified.png")  # before filling: check the edges and the medallion centre here
img = np.asarray(shot).astype(np.float32)
hole = np.abs(img - np.array([255, 0, 255], np.float32)).sum(2) < 200  # magenta background (and its anti-aliased fringe)
hole = np.asarray(Image.fromarray((hole * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0  # grow a little
Hh, Ww = hole.shape
for box in args.bad.split():
    u0, v0, u1, v1 = (float(c) for c in box.split(","))
    hole[round(v0 * Hh):round(v1 * Hh), round(u0 * Ww):round(u1 * Ww)] = True
out = img.copy()
filled = hole.copy()
cu, cv = (float(c) for c in args.center.split(","))
yy, xx = np.mgrid[0:Hh, 0:Ww]
flips = {"xy": [(1, 0), (0, 1), (1, 1)], "x": [(1, 0)], "y": [(0, 1)], "none": []}[args.sym]
for fx, fy in flips:  # mirror about the medallion centre; a pixel takes the first valid mirror image
    sx = np.round(2 * cu * (Ww - 1) - xx).astype(int) if fx else xx
    sy = np.round(2 * cv * (Hh - 1) - yy).astype(int) if fy else yy
    inside = (sx >= 0) & (sx < Ww) & (sy >= 0) & (sy < Hh)
    sxc, syc = np.clip(sx, 0, Ww - 1), np.clip(sy, 0, Hh - 1)
    ok = inside & ~hole[syc, sxc]
    take = hole & ok
    out[take] = out[syc[take], sxc[take]]
    hole = hole & ~ok  # still missing where the mirror is missing too
# where every mirror is missing too (e.g. a long sofa along one side): borrow the same band of the field from a
# nearby offset, along the rug's length and width, so the motif texture continues rather than smearing
for du, dv in ((0, 0.22), (0, -0.22), (0.22, 0), (-0.22, 0), (0, 0.33), (0, -0.33), (0.33, 0), (-0.33, 0)):
    if not hole.any():
        break
    sx, sy = xx + round(du * Ww), yy + round(dv * Hh)
    inside = (sx >= 0) & (sx < Ww) & (sy >= 0) & (sy < Hh)
    sxc, syc = np.clip(sx, 0, Ww - 1), np.clip(sy, 0, Hh - 1)
    ok = inside & ~hole[syc, sxc]
    take = hole & ok
    out[take] = out[syc[take], sxc[take]]
    hole = hole & ~ok
# diffuse whatever is left from its neighbours
known = ~hole
out[~known] = 0
for _ in range(200):
    if known.all():
        break
    blur = np.asarray(Image.fromarray(out.astype(np.uint8)).filter(ImageFilter.BoxBlur(3))).astype(np.float32)
    kb = np.asarray(Image.fromarray((known * 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(3))).astype(np.float32) / 255
    ok = (~known) & (kb > 0.05)
    out[ok] = blur[ok] / kb[ok][:, None]
    known = known | ok
# soften the seams between real and borrowed pixels
seam = Image.fromarray((filled * 255).astype(np.uint8))
seam = np.asarray(seam.filter(ImageFilter.MaxFilter(7))).astype(bool) & ~np.asarray(seam.filter(ImageFilter.MinFilter(7))).astype(bool)
soft = np.asarray(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))).astype(np.float32)
out[seam] = soft[seam]
res = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
dst = Path(args.out or "textures/rug-from-scan.jpg")
dst.parent.mkdir(parents=True, exist_ok=True)
res.save(dst, quality=90)
print("wrote", dst, res.size, f"{int(hole.sum())} px filled by diffusion")
