# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2"]
# ///
"""Headless Blender: import scan, align walls to axes, floor to z=0, export aligned GLB, render plan + elevations.

Usage: uv run ../../tools/align_and_render.py [--] <in.glb> <out_dir>   (multi-mesh scans are joined first)
"""
import json
import math
import sys
from pathlib import Path

import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

import numpy as np
from mathutils import Euler, Vector

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
if len(args) < 2:
    sys.exit("usage: uv run ../../tools/align_and_render.py [--] <in.glb> <out_dir>")
src, out = args[:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
# one mesh: scans can come in chunks (several meshes / texture atlases) and under parent nodes; un-parent every mesh
# keeping its world transform, then join them so the whole scan is aligned and exported
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit(f"{src}: no mesh in the file")
for o in bpy.context.scene.objects:
    o.select_set(o in meshes)
obj = meshes[0]
bpy.context.view_layer.objects.active = obj
if any(o.parent for o in meshes):
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
if len(meshes) > 1:
    bpy.ops.object.join()
    print(f"joined {len(meshes)} scan meshes")
obj = bpy.context.view_layer.objects.active
obj.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

me = obj.data

def tri_geom():
    """Per-triangle unit normals, areas, centers computed from current vertex positions."""
    me.calc_loop_triangles()
    v = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", v); v = v.reshape(-1, 3)
    t = np.empty(len(me.loop_triangles) * 3, dtype=np.int32); me.loop_triangles.foreach_get("vertices", t)
    p = v[t.reshape(-1, 3)]
    cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(cr, axis=1) + 1e-12
    return cr / ln[:, None], ln / 2, p.mean(1), v

n, a, c, v = tri_geom()
# dominant wall direction (mod 90), fine histogram
vert = np.abs(n[:, 2]) < 0.2
ang = np.degrees(np.arctan2(n[vert, 1], n[vert, 0])) % 90
h, e = np.histogram(ang, bins=900, range=(0, 90), weights=a[vert])
h = np.convolve(np.concatenate([h[-10:], h, h[:10]]), np.ones(11) / 11, "same")[10:-10]
theta = (e[np.argmax(h)] + 0.05)
if theta > 45: theta -= 90
print(f"WALL_ANGLE {theta:.2f}")
obj.rotation_mode = "XYZ"  # glTF import defaults to QUATERNION, which ignores rotation_euler
obj.rotation_euler = Euler((0, 0, math.radians(-theta)))
bpy.ops.object.transform_apply(rotation=True)

# floor = dominant up-facing height
n, a, c, v = tri_geom()
up = n[:, 2] > 0.9
hh, ee = np.histogram(c[up, 2], bins=200, weights=a[up])
floor = ee[np.argmax(hh)] + (ee[1] - ee[0]) / 2
lo = np.percentile(v[:, :2], 0.5, axis=0)
obj.location = Vector((-lo[0], -lo[1], -floor))
bpy.ops.object.transform_apply(location=True)
n, a, c, v = tri_geom()
# Same transform expressed in the raw glTF's Y-up frame (for loading scan_raw.glb in three.js):
# rotate about +Y by -theta, then translate by (-lo_x, -floor, +lo_y).
print(f"GLTF_TRANSFORM rotY_deg={-theta:.6f} translate=[{-lo[0]:.6f}, {-floor:.6f}, {lo[1]:.6f}]")
Path(out).mkdir(parents=True, exist_ok=True)
(Path(out) / "alignment.json").write_text(json.dumps({
    "rotationYDeg": round(-theta, 6),
    "translate": [round(-lo[0], 6), round(-floor, 6), round(lo[1], 6)],
    "note": "glTF (Y-up) transform taking scan_raw.glb to scan_aligned.glb: rotate about +Y, then translate.",
}, indent=2) + "\n")
print("FLOOR_OFFSET", floor, "BOUNDS", v.min(0).round(3).tolist(), v.max(0).round(3).tolist())

bpy.ops.export_scene.gltf(filepath=f"{out}/scan_aligned.glb", use_selection=True, export_image_format="JPEG")

# render setup
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "TEXTURE"
sc.render.film_transparent = False
sc.world = bpy.data.worlds.new("w"); sc.world.color = (1, 0, 1)
mn, mx = v.min(0), v.max(0); ctr = (mn + mx) / 2
cam_d = bpy.data.cameras.new("cam"); cam_d.type = "ORTHO"
cam = bpy.data.objects.new("cam", cam_d); sc.collection.objects.link(cam); sc.camera = cam
PX_PER_M = 200

def shot(name, loc, rot, w, hgt, clip_start, clip_end=50):
    cam.location = loc; cam.rotation_euler = rot
    cam_d.ortho_scale = max(w, hgt); cam_d.clip_start = clip_start; cam_d.clip_end = clip_end
    sc.render.resolution_x = int(w * PX_PER_M); sc.render.resolution_y = int(hgt * PX_PER_M)
    cam_d.sensor_fit = "HORIZONTAL" if w >= hgt else "VERTICAL"
    sc.render.filepath = f"{out}/{name}.png"
    bpy.ops.render.render(write_still=True)

W, D, H = mx - mn
# plan: cut at 1.9 m (removes ceiling)
shot("plan_cut190", (ctr[0], ctr[1], 1.9), (0, 0, 0), W, D, 0.0)
shot("plan_cut100", (ctr[0], ctr[1], 1.0), (0, 0, 0), W, D, 0.0)
# elevations: camera at room center looking toward each wall (sees the half of room on that side)
z = (mn[2] + mx[2]) / 2
shot("elev_north_+y", (ctr[0], ctr[1], z), (math.pi/2, 0, 0), W, H, 0.0)
shot("elev_south_-y", (ctr[0], ctr[1], z), (math.pi/2, 0, math.pi), W, H, 0.0)
shot("elev_east_+x", (ctr[0], ctr[1], z), (math.pi/2, 0, -math.pi/2), D, H, 0.0)
shot("elev_west_-x", (ctr[0], ctr[1], z), (math.pi/2, 0, math.pi/2), D, H, 0.0)
