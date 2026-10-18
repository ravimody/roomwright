# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4.18"]
# ///
"""Check a room's data before rendering: room.json, catalog.json, layouts/, render_sets/ and report/build.json against
the JSON Schemas in schema/, plus the checks a schema can't express (a door that isn't on a wall is silently dropped by
the renderer, a layout item whose type no catalog defines renders as a grey box, a render set naming a missing camera).

Usage:
  uv run ../../tools/validate_room.py            (from inside rooms/<room>/)
  uv run tools/validate_room.py --all            (from the repo root: every room, plus the shared and household catalogs)

Prints ERROR and WARN lines; exits 1 if there is any error.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roomframe import household_root, load_catalog

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / "schema"
PRESETS = {"day", "night", "evening", "standard"}
EDGE_TOL = 0.03  # m: door/window endpoints must sit on an outline edge (blender_scene.on_edge uses the same tolerance)


def core_models():
    """The engine's own models (box, parts, glb, mat, roundRug), from tools/blender_models.py CORE."""
    py = (REPO / "tools/blender_models.py").read_text()
    return set(re.findall(r'"(\w+)":', re.search(r"^CORE = \{(.*?)\}$", py, re.M | re.S).group(1)))


def registered(path):
    """Builder names a builder module registers, parsed without running it: BUILDERS = {"name": fn, ...} in a .py file,
    export const BUILDERS = { name(s, g) {...}, other: fn, ... } in a .js file."""
    s = Path(path).read_text()
    if Path(path).suffix == ".py":
        m = re.search(r"^BUILDERS = \{(.*?)\}$", s, re.M | re.S)
        return set(re.findall(r'"(\w+)":', m.group(1))) if m else set()
    m = re.search(r"^export const BUILDERS = \{$(.*?)^\};", s, re.M | re.S)
    body = m.group(1) if m else ""
    return set(re.findall(r"^  (\w+)\(", body, re.M)) | set(re.findall(r"^  (\w+)(?:: *\w+)?,$", body, re.M))


def builder_dirs(room_dir):
    """<household>/builders and <room>/builders, where they exist (as tools/blender_models.py builder_dirs)."""
    rd = Path(room_dir).resolve()
    hh = household_root(rd)
    return [d for d in (hh / "builders" if hh else None, rd / "builders") if d and d.is_dir()]


def builder_names(dirs=()):
    """(photoreal builders, editor builders): the core models plus every name registered by the builder modules in
    dirs (Python for photoreal renders, JavaScript for the editor; files starting with _ are helpers)."""
    blender, editor = core_models(), core_models()
    for d in dirs:
        for f in sorted(Path(d).iterdir()):
            if f.name.startswith("_"):
                continue
            if f.suffix == ".py":
                blender |= registered(f)
            elif f.suffix == ".js":
                editor |= registered(f)
    return blender, editor


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, where, msg):
        self.errors.append(f"ERROR {where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"WARN  {where}: {msg}")


def load(path, rep):
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        rep.error(path, f"invalid JSON: {e}")
    return None


def schema_check(data, name, where, rep):
    v = Draft202012Validator(json.loads((SCHEMA / f"{name}.schema.json").read_text()))
    for e in sorted(v.iter_errors(data), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in e.path) or "(top)"
        rep.error(where, f"{loc}: {e.message[:200]}")


def on_edge(p, outline):
    """Index of the outline edge point p lies on (within EDGE_TOL), else None."""
    n = len(outline)
    for i in range(n):
        (ax, ay), (bx, by) = outline[i], outline[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / L
        d = abs((p[0] - ax) * dy - (p[1] - ay) * dx) / L
        if d < EDGE_TOL and -EDGE_TOL < t < L + EDGE_TOL:
            return i
    return None


def check_room(room_dir, rep):
    """Every check on one room folder; its catalog is checked against the builders it can use (core models plus the
    household's and the room's builders/)."""
    rd = Path(room_dir)
    blender, editor = builder_names(builder_dirs(rd))
    where = rd / "room.json"
    room = load(where, rep)
    if room is None:
        return
    schema_check(room, "room", where, rep)
    out = room.get("outline", [])
    if len(out) >= 3:
        area = sum(out[i][0] * out[(i + 1) % len(out)][1] - out[(i + 1) % len(out)][0] * out[i][1] for i in range(len(out))) / 2
        if area <= 0:
            rep.error(where, "outline must be counter-clockwise (x east, y north)")
        for i in range(len(out)):
            if math.dist(out[i], out[(i + 1) % len(out)]) < 1e-6:
                rep.error(where, f"outline has a repeated vertex at index {i}")
        for kind in ("doors", "windows"):
            for o in room.get(kind, []):
                ea, eb = on_edge(o.get("a", (1e9, 1e9)), out), on_edge(o.get("b", (1e9, 1e9)), out)
                if ea is None or eb is None or ea != eb:
                    rep.error(where, f"{kind[:-1]} {o.get('id')}: a and b must lie on the same outline edge (within {EDGE_TOL * 100:.0f} cm), or it isn't built")
    top = room.get("ceiling", {}).get("top", 99)
    for w in room.get("windows", []):
        if not w.get("z0", 0) < w.get("z1", 0) <= top + 0.01:
            rep.error(where, f"window {w.get('id')}: needs z0 < z1 <= ceiling top ({top})")
    for d in room.get("doors", []):
        if d.get("height", 0) > top + 0.01:
            rep.warn(where, f"door {d.get('id')}: taller than the ceiling top ({d['height']} > {top})")
    for f in room.get("fixtures", []):
        wall = f.get("wall")
        need = {"north": ("x0", "x1", "y"), "south": ("x0", "x1", "y"), "east": ("y0", "y1", "x"), "west": ("y0", "y1", "x")}.get(wall)
        if need and not all(k in f for k in need):
            rep.error(where, f"fixture {f.get('id')}: a {wall}-wall fixture needs {', '.join(need)}")
    fixture_ids = {f.get("id") for f in room.get("fixtures", [])}
    for r in room.get("rules", []):
        if r.get("fixture") and r["fixture"] not in fixture_ids:
            rep.error(where, f"rule {r.get('name') or r.get('kind')}: unknown fixture {r['fixture']!r}")
    check_lighting(room, where, rep)
    if not room.get("cameras"):
        rep.warn(where, "no cameras: add named views before rendering")
    for name in ("materials", "scenes"):
        if name not in room and room.get("cameras"):
            rep.warn(where, f"no {name!r}: renders use the engine's neutral defaults")
    if not (rd / "scan/scan_aligned.glb").exists() and not rd.name.startswith("_"):
        rep.warn(rd, "no scan/scan_aligned.glb (or Git LFS content not pulled)")

    cpath = rd / "catalog.json"
    if cpath.exists():
        cat = load(cpath, rep)
        if cat is not None:
            schema_check(cat, "catalog", cpath, rep)
            check_catalog(cat, cpath, blender, editor, rep)
    try:
        catalog = load_catalog(rd)  # shared, household, room
    except (json.JSONDecodeError, KeyError):
        catalog = {}
    cams = set(room.get("cameras", {}))
    scenes = set(room.get("scenes", {})) | PRESETS
    layouts = {}
    for lp in sorted((rd / "layouts").glob("*.json")):
        lay = load(lp, rep)
        if lay is None:
            continue
        layouts[lp.stem] = lay
        schema_check(lay, "layout", lp, rep)
        ids = [it.get("id") for it in lay.get("items", [])]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            rep.error(lp, f"duplicate item id {dup!r}")
        for it in lay.get("items", []):
            if it.get("type") not in catalog:
                rep.error(lp, f"item {it.get('id')}: type {it.get('type')!r} is in no catalog (renders as a box)")
    for sp in sorted((rd / "render_sets").glob("*.json")):
        sets = load(sp, rep)
        if sets is None:
            continue
        schema_check(sets, "render_sets", sp, rep)
        for st in sets if isinstance(sets, list) else []:
            if st.get("layout") not in layouts:
                rep.error(sp, f"layout {st.get('layout')!r} not in layouts/")
            for v in filter(None, (st.get("views") or "").split(",")):
                if v not in cams:
                    rep.error(sp, f"view {v!r} is not a room.json camera")
            for lt in (st.get("lighting") or "standard").split(","):
                if lt not in scenes:
                    rep.error(sp, f"lighting {lt!r} is neither a preset nor a room.json scene")
    bp = rd / "report/build.json"
    if bp.exists():
        b = load(bp, rep)
        if b is not None:
            schema_check(b, "build", bp, rep)


LEGACY_LIGHTING = {  # keys from before photometric lights (2026-10) -> what replaces them
    ("lights", "eveningEnergy"): "lights.cans.lumens and a scene's cans (dimmer setting)",
    ("lights", "canEnergy"): "lights.cans.lumens plus a scene (base standard) with its cans setting",
    ("lights", "spotDeg"): "lights.cans.beam",
    ("daylight", "ambient"): "nothing (light comes in through the windows only); daylight.scale to calibrate",
    ("daylight", "energyPerM2"): "daylight.illuminance (lux) or daylight.scale",
    ("daylight", "energy"): "daylight.scale",
    ("daylight", "skyStrength"): "daylight.illuminance",
    ("daylight", "skyColor"): "daylight.sky",
    ("daylight", "lightColor"): "daylight.sky",
    ("daylight", "worldColor"): "daylight.sky",
}


def check_lighting(room, where, rep):
    """Old lighting keys are ignored by the renderer now: say what replaces them. Scene references must exist."""
    for (sect, key), new in LEGACY_LIGHTING.items():
        if key in room.get(sect, {}):
            rep.error(where, f"{sect}.{key} is no longer used: use {new} (see COOKBOOK 'Lighting model')")
    for key in ("exposure", "whiteBalance"):
        if isinstance(room.get(key), dict):
            rep.error(where, f"room-level {key} per preset is no longer used: scenes take {key} (\"auto\" by default)")
    for name, d in [("lights", room.get("lights") or {}), *((f"scene {n}", s) for n, s in (room.get("scenes") or {}).items())]:
        if isinstance(d, dict) and "cans" in d and "downlights" in d:
            rep.error(where, f"{name}: give `downlights` or `cans` (the same thing), not both")
    fireplaces = [f for f in room.get("fixtures", []) if f.get("kind") == "fireplace"]
    wants_fire = any(isinstance(s, dict) and s.get("fire") for s in (room.get("scenes") or {}).values())
    for f in fireplaces:
        if f.get("insert", "none") == "none" and (wants_fire or f.get("fire")):
            rep.warn(where, f"fixture {f.get('id')}: a scene or `fire` asks for a fire, but `insert` is none (the default): "
                            "set insert wood or gas, or it shows no flames")
    screens = {f.get("id") for f in room.get("fixtures", []) if f.get("screen") is not None}
    for f in room.get("fixtures", []):
        if "fireWatts" in f:
            rep.error(where, f"fixture {f.get('id')}: fireWatts is no longer used: use fire.lumens")
        for k in ("lights", "pictureLight"):
            if isinstance(f.get(k), dict) and "watts" in f[k]:
                rep.warn(where, f"fixture {f.get('id')}: {k}.watts is a legacy weight: give {k}.lumens")
    for name, sc in room.get("scenes", {}).items():
        if "uplights" in sc:
            rep.error(where, f"scene {name}: uplights were removed (no fixture the room has)")
        for s in sc.get("screens", []):
            if s not in screens:
                rep.error(where, f"scene {name}: screen {s!r} is not a fixture with a `screen`")
        for k in ("cans", "downlights", "ceiling", *sc.get("lampDim", {}).values()):
            v = sc.get(k) if k in ("cans", "downlights", "ceiling") else k
            if isinstance(v, (int, float)) and not 0 <= v <= 1:
                rep.error(where, f"scene {name}: dimmer settings are 0-1 (got {v})")


def check_catalog(cat, where, blender, editor, rep):
    for k, it in cat.get("items", {}).items():
        li = it.get("interiorLight") or {}
        if "watts" in li or "color" in li:
            rep.warn(where, f"{k}: interiorLight watts/color are legacy: give lumens and kelvin")
        if "watts" in it and "light" not in it:
            rep.warn(where, f"{k}: watts is the builder's legacy weight; give light.lumens (and kelvin) from the bulb")
        m = it.get("model")
        if m and m not in blender and m not in editor:
            rep.error(where, f"{k}: model {m!r} has no builder (core models: {', '.join(sorted(core_models()))}; or add builders/{m}.py and .js)")
        elif m and m not in blender:
            rep.warn(where, f"{k}: model {m!r} exists only in the editor; photoreal renders draw a box")
        elif m and m not in editor:
            rep.warn(where, f"{k}: model {m!r} has no editor builder; the editor draws a box")
        if m == "parts" and not it.get("parts"):
            rep.warn(where, f"{k}: model 'parts' with no parts; drawn as a box")
        here = Path(where).resolve().parent  # a room folder or a household folder
        if m == "glb" and it.get("file") and not any(p and (p / it["file"]).is_file() for p in (here, household_root(here))):
            rep.warn(where, f"{k}: model file {it['file']!r} not found next to this catalog or in the household folder")


def check_shared_catalogs(households, rep):
    """shared/catalog.json (core models only) and each household's catalog.json (against its builders/)."""
    core = core_models()
    shared = REPO / "shared/catalog.json"
    doc = load(shared, rep)
    if doc is not None:
        schema_check(doc, "catalog", shared, rep)
        check_catalog(doc, shared, core, core, rep)
    for hh in households:
        p = hh / "catalog.json"
        doc = load(p, rep) if p.exists() else None
        if doc is not None:
            schema_check(doc, "catalog", p, rep)
            check_catalog(doc, p, *builder_names([hh / "builders"] if (hh / "builders").is_dir() else []), rep)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--all", action="store_true", help="every room under rooms/ plus the shared and household catalogs")
    ap.add_argument("rooms", nargs="*", help="room folders (default: the current folder)")
    ap.add_argument("--rooms-dir", help="with --all: the folder holding the rooms (default: ./rooms, else the engine's rooms/)")
    a = ap.parse_args()
    rep = Report()
    rooms_dir = Path(a.rooms_dir) if a.rooms_dir else Path("rooms") if Path("rooms").is_dir() else REPO / "rooms"
    rooms = sorted(p for p in rooms_dir.iterdir() if (p / "room.json").exists()) if a.all else [Path(r) for r in a.rooms or ["."]]
    if a.all:  # the shared and household catalogs are checked once, not per room
        check_shared_catalogs(sorted({h for h in (household_root(r) for r in rooms) if h}), rep)
    for r in rooms:
        if not (Path(r) / "room.json").exists():
            sys.exit(f"{r}: no room.json (run from inside rooms/<room>/, or pass --all from the repo root)")
        check_room(r, rep)
    for line in rep.errors + rep.warnings:
        print(line)
    print(f"{len(rooms)} room(s): {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    sys.exit(1 if rep.errors else 0)


if __name__ == "__main__":
    main()
