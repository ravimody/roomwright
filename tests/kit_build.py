# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*"]
# ///
"""Build the core models (box, parts, glb) with Blender in a throwaway household and check each lands at its catalog
size and plan position. Run by tests/test_kit.py when ROOMWRIGHT_BPY=1; by hand: uv run tests/kit_build.py <empty dir>."""

import json
import math
import os
import sys
from pathlib import Path

home = Path(sys.argv[-1]).resolve()
room = home / "rooms/r"
(room / "layouts").mkdir(parents=True, exist_ok=True)
(home / "models").mkdir(exist_ok=True)
(room / "room.json").write_text(json.dumps({"outline": [[0, 0], [5, 0], [5, 4], [0, 4]], "ceiling": {"top": 2.5}, "doors": [], "windows": []}))
os.environ["ROOM"] = str(room)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import bpy  # noqa: E402

import blender_models  # noqa: E402

# a model file: a 2 x 1 x 3 box off-centre, as downloaded models often are
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(5, 7, 9))
bpy.context.active_object.scale = (2, 1, 3)
bpy.ops.export_scene.gltf(filepath=str(home / "models/thing.glb"), export_format="GLB")

TABLE = {"model": "parts", "w": 1.2, "d": 0.8, "h": 0.75, "color": "#8a6a4a",
         "materials": {"top": {"hex": "#9a7652", "kind": "wood"}, "brass": {"hex": "#b08d57", "kind": "metal"}},
         "parts": [{"size": [1.2, 0.8, 0.03], "at": [0, 0, 0.735], "material": "top"},
                   {"shape": "cylinder", "r": 0.025, "h": 0.72, "at": [0.55, 0.35, 0.36], "mirror": "xy"},
                   {"shape": "lathe", "profile": [[0.05, 0], [0.03, 0.05], [0.0, 0.08]], "at": [0, 0, 0.75], "material": "brass"},
                   {"shape": "extrude", "points": [[-0.1, -0.1], [0.1, -0.1], [0, 0.1]], "h": 0.02, "at": [0.2, 0, 0.75]},
                   {"shape": "sphere", "r": 0.05, "scale": [1, 1, 0.5], "at": [-0.3, 0, 0.775]},
                   {"shape": "cone", "r0": 0.05, "r1": 0.02, "h": 0.1, "at": [-0.5, 0, 0.8], "rot": [0, 0, 45]}]}
catalog = {"table": TABLE, "thing": {"model": "glb", "file": "models/thing.glb", "w": 0.6, "d": 0.3, "h": 0.9},
           "stretched": {"model": "glb", "file": "models/thing.glb", "fit": "stretch", "w": 0.5, "d": 0.5, "h": 0.5},
           "crate": {"model": "box", "w": 0.4, "d": 0.3, "h": 0.2, "color": "#777777"}}
layout = {"items": [{"id": "t", "type": "table", "x": 1, "y": 1, "rot": 0}, {"id": "t2", "type": "table", "x": 3, "y": 1, "rot": 90, "w": 1.8},
                    {"id": "g", "type": "thing", "x": 2, "y": 3, "rot": 0}, {"id": "s", "type": "stretched", "x": 4, "y": 3, "rot": 0},
                    {"id": "c", "type": "crate", "x": 0.5, "y": 3, "rot": 0}]}
bpy.ops.wm.read_factory_settings(use_empty=True)
coll = bpy.context.scene.collection
blender_models.place_items(layout, catalog, coll, json.loads((room / "room.json").read_text()))
bpy.context.view_layer.update()


def bbox(item_id):
    root = next(o for o in bpy.data.objects if o.get("item_id") == item_id)
    pts = [o.matrix_world @ v.co for o in root.children_recursive if o.type == "MESH" for v in o.data.vertices]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def expect(item_id, x, y, w, d, h, tol=0.012):
    lo, hi = bbox(item_id)
    got = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], lo[2])
    want = (x, y, w, d, h, 0.0)
    bad = [f"{n} {g:.3f} != {e:.3f}" for n, g, e in zip(("x", "y", "w", "d", "h", "z0"), got, want) if not math.isclose(g, e, abs_tol=tol)]
    print(f"{item_id}: {'ok' if not bad else 'WRONG ' + ', '.join(bad)}")
    return not bad


ok = all([expect("t", 1, 1, 1.2, 0.8, 0.85), expect("t2", 3, 1, 0.8, 1.8, 0.85),  # top 0.75 + the cone; t2 rotated 90, stretched to w 1.8
          expect("g", 2, 3, 0.6, 0.3, 0.9),  # uniform: the 2 x 1 x 3 model scaled by 0.3
          expect("s", 4, 3, 0.5, 0.5, 0.5), expect("c", 0.5, 3, 0.4, 0.3, 0.2)])
legs = [o for o in bpy.data.objects if o.name.startswith("part1") and o.parent and o.parent.get("item_id") == "t"]
ok &= len(legs) == 4
print(f"mirrored legs: {len(legs)}")
sys.exit(0 if ok else 1)
