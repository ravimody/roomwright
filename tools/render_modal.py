# /// script
# requires-python = ">=3.11"
# dependencies = ["modal"]
# ///
"""Render photoreal views on Modal cloud GPUs, in parallel. Same output as tools/render_photoreal.py.

Run from the folder that holds rooms/ (the repo root) or from a room folder (then --room defaults to it):
  modal run tools/render_modal.py --room <room> --layout <layout> --lighting evening \
      --views <cam1>,<cam2> --samples 48 --res 1400x875 [--tag <folder>] [--gpu L4]

  # several lighting presets at once (each preset × each view is one GPU job):
  modal run tools/render_modal.py --room <room> --layout <layout> --lighting day,evening

  # many sets in one run: the same sets file as render_batch.py, plus "room" per set
  modal run tools/render_modal.py --batch rooms/<room>/render_sets/<name>.json
  roomwright render-modal …  (the same, with the engine installed as a package)

Each (lighting, view) pair runs in its own container. Results land in rooms/<room>/renders/photoreal/<folder>/<view>.png,
with the same folder naming as render_batch.py: <tag> when one lighting is given, else <tag or layout>-<lighting>.
(render_photoreal.py run directly writes <tag or layout>.) A set's "meterLayout", "samples" and "res" work as in
render_batch.py. Uploaded: the engine (tools/, shared/), the household's catalog.json, builders/, models/ and textures/,
and rooms/ without scans, photos, reports and renders (room.json, catalogs, builders, layouts, render sets, textures).

Cost: Modal bills GPU-seconds (plus a little CPU/RAM). An L4 is ~$0.80/h. See COOKBOOK "Cloud renders".
"""

import inspect
import os
import time
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent  # the engine: tools/ and shared/ (a checkout, or the installed package)
# the household: the folder holding rooms/, found from the current folder (the repo root or a room folder)
def _household():
    """The folder holding rooms/: from a --batch file's path when given (it may be another household's), else from the
    current folder (the repo root or a room folder)."""
    import sys

    argv = sys.argv
    batch = next((a.split("=", 1)[1] for a in argv if a.startswith("--batch=")), None)
    if batch is None and "--batch" in argv and argv.index("--batch") + 1 < len(argv):
        batch = argv[argv.index("--batch") + 1]
    if batch:
        for d in Path(batch).resolve().parents:
            if d.name == "rooms":
                return d.parent
    return next((d for d in (Path.cwd(), *Path.cwd().parents) if (d / "rooms").is_dir()), Path.cwd())


HOUSEHOLD = _household()
ROOMS = HOUSEHOLD / "rooms"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libxrender1", "libxxf86vm1", "libxfixes3", "libxi6", "libxkbcommon0", "libgl1", "libsm6", "libglib2.0-0", "libgomp1")
    .pip_install("bpy==4.5.*", "numpy<2", "pillow")
    .add_local_dir(REPO / "tools", "/repo/tools", ignore=["__pycache__"])
    .add_local_dir(REPO / "shared", "/repo/shared")
    .add_local_dir(ROOMS, "/repo/rooms", ignore=["*/renders/**", "*/photos/**", "*/report/**", "*/scan/**", "_template/**"])
)
# the household's own item types, builders and model files (roomframe.household_root is /repo in the container)
for _sub in ("builders", "models", "textures"):
    if (HOUSEHOLD / _sub).is_dir():
        image = image.add_local_dir(HOUSEHOLD / _sub, f"/repo/{_sub}", ignore=["__pycache__"])
if (HOUSEHOLD / "catalog.json").is_file():
    image = image.add_local_file(HOUSEHOLD / "catalog.json", "/repo/catalog.json")
app = modal.App("roomwright-renders", image=image)
# a fresh container per render (bpy keeps state between scenes); modal >= 1.3 calls it single_use_containers
ONE_USE = ({"single_use_containers": True} if "single_use_containers" in inspect.signature(modal.App.function).parameters
           else {"max_inputs": 1})


def _render(room, layout, lighting, view, samples, res, device, meter_layout=None):
    """Runs inside the container: render one view and return (png bytes, seconds)."""
    import sys

    os.environ["ROOM"] = f"/repo/rooms/{room}"
    os.chdir(f"/repo/rooms/{room}")
    sys.path.insert(0, "/repo/tools")
    import render_photoreal as rp

    os.environ["CYCLES_DEVICE"] = device  # render_photoreal enables OptiX/CUDA when this is GPU
    tag = f"job-{lighting}-{view}"
    t0 = time.time()
    rp.render(layout, samples, [view], res, lighting, tag, meter_layout=meter_layout)
    out = Path(f"/repo/rooms/{room}/renders/photoreal/{tag}/{view}.png")
    return out.read_bytes(), time.time() - t0


@app.function(gpu="L4", timeout=1800, **ONE_USE)
def render_l4(room, layout, lighting, view, samples, res, meter_layout=None):
    return _render(room, layout, lighting, view, samples, res, "GPU", meter_layout)


@app.function(gpu="T4", timeout=1800, **ONE_USE)
def render_t4(room, layout, lighting, view, samples, res, meter_layout=None):
    return _render(room, layout, lighting, view, samples, res, "GPU", meter_layout)


@app.function(cpu=8.0, memory=8192, timeout=3600, **ONE_USE)
def render_cpu(room, layout, lighting, view, samples, res, meter_layout=None):
    return _render(room, layout, lighting, view, samples, res, "CPU", meter_layout)


@app.function(gpu="L4", timeout=600)
def probe():
    """Report GPUs and Cycles devices visible inside the container."""
    import subprocess

    import bpy

    out = [subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, check=False).stdout.strip()]
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for b in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = b
            prefs.get_devices()
            out.append(f"{b}: " + ", ".join(f"{d.name}({d.type})" for d in prefs.devices))
        except Exception as e:
            out.append(f"{b}: ERR {e}")
    return "\n".join(out)


PRICE_PER_HOUR = {"L4": 0.80, "T4": 0.59, "CPU": 0.38}  # approx. Modal list prices incl. typical CPU/RAM share


@app.local_entrypoint()
def main(room: str = "", layout: str = "", probe_gpu: bool = False, lighting: str = "standard", views: str = "", samples: int = 48,
         res: str = "1400x875", tag: str = "", gpu: str = "L4", batch: str = ""):
    """--batch sets.json renders many sets in ONE run (all views in parallel). Separate `modal run` processes at the
    same time tend to hang, so batch instead: [{"room", "layout", "lighting", "views", "tag"}, ...]."""
    import json

    if probe_gpu:
        print(probe.remote())
        return
    fn = {"L4": render_l4, "T4": render_t4, "CPU": render_cpu}[gpu]
    import re
    import sys

    here = Path.cwd().resolve()
    if not room and not batch and here.parent == ROOMS.resolve():
        room = here.name  # run from a room folder
    sets = json.loads(Path(batch).read_text()) if batch else [{"room": room, "layout": layout, "lighting": lighting, "views": views, "tag": tag}]
    # a sets file inside rooms/<room>/ (render_sets/*.json, shared with render_batch.py) needs no "room" per set
    parts = Path(batch).resolve().parts if batch else ()
    batch_room = parts[parts.index("rooms") + 1] if "rooms" in parts and parts.index("rooms") + 1 < len(parts) else ""
    for st in sets:
        st.setdefault("room", batch_room)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", st.get("room") or "") or not (ROOMS / st["room"] / "room.json").exists():
            sys.exit(f"unknown room {st.get('room')!r}: give --room (or \"room\" per set) naming a folder in rooms/")
    jobs, folders = [], []
    for st in sets:
        vs = st.get("views") or ",".join(json.loads((ROOMS / st["room"] / "room.json").read_text())["cameras"])
        lt, tg = st.get("lighting", "standard"), st.get("tag", "")
        for L in lt.split(","):
            for v in vs.split(","):
                w, h = (int(n) for n in st.get("res", res).split("x"))
                jobs.append((st["room"], st["layout"], L, v, int(st.get("samples", samples)), (w, h), st.get("meterLayout")))
                folders.append(tg if (tg and "," not in lt) else f"{tg or st['layout']}-{L}")
    t0 = time.time()
    total_s = 0.0
    failed = []
    # return_exceptions: a container that dies (it happens) costs one view, not the whole batch
    results = fn.starmap(jobs, return_exceptions=True)
    for (rm, lay, L, v, *_), folder, res in zip(jobs, folders, results):
        if isinstance(res, BaseException):
            failed.append(f"{rm} {lay} {L} {v}")
            print(f"FAILED {rm}/{folder}/{v}: {type(res).__name__}: {str(res)[:200]}")
            continue
        png, secs = res
        out = ROOMS / rm / "renders" / "photoreal" / folder / f"{v}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)
        total_s += secs
        print(f"RENDERED {os.path.relpath(out)}  ({secs:.0f}s on {gpu})")
    if failed:
        print(f"{len(failed)} view(s) failed; re-run just those (often a transient container failure):\n  " + "\n  ".join(failed))
    wall = time.time() - t0
    est = total_s / 3600 * PRICE_PER_HOUR[gpu]
    print(f"{len(jobs)} views, wall {wall:.0f}s, render time {total_s:.0f}s, est. cost ${est:.2f} "
          f"(+ container start-up, ~10–30 s each)")
