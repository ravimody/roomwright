# Quickstart

From a room (a phone scan, or a tape measure and photos) to a measured model, layout options and photoreal renders. A coding agent (Claude Code, Codex, Antigravity, Cursor, …; setup: [AGENT_SETUP](AGENT_SETUP.md)) normally drives these steps and reads the [COOKBOOK](../COOKBOOK.md) (best practices for each step) and the [design guide](DESIGN_GUIDE.md) (widely shared practice, as guidance) as it goes; you can run every step yourself too.

## Choose your path

- **Chat only.** Give your agent the scan or measurements, photos and a few notes, and ask for what you want. The agent installs what it needs, runs every tool and sends results the way your `HOUSEHOLD.md` says (images in chat, a PDF, a phone-friendly page or a local report). You never need a terminal; the rest of this page is what the agent does.
- **Command line.** Run the commands below yourself, or alongside the agent.

Tell the agent how deep to go: **quick** (ideas, about 30 minutes, not scan-verified), **standard** (most rooms) or **verified** (anything cut to fit or drawn for builders). What each includes: [COOKBOOK, How much to do](../COOKBOOK.md#how-much-to-do).

## What to capture

- **A scan, if you can.** Best: a phone or tablet with LiDAR and a scanning app that exports GLB. Walk slowly and get the ceiling and every corner. Without LiDAR, a photo-mode (photogrammetry) app works on many phones; it is less accurate and leaves holes on plain walls.
- **No scan?** Measure each wall, both diagonals, door and window positions and heights, and the ceiling height, with a tape or laser. `roomwright new-room <name>` without a scan creates `rooms/<name>/` from the template; the agent types your measurements into `room.json`. The scan checks are skipped and the report says the model is not scan-verified (details: [COOKBOOK, Without a scan](../COOKBOOK.md#without-a-scan)).
- **Photos:** 10–20 from the corners and doorways, plus a few with the lights as you use them at night, and close-ups of anything odd.
- **Notes:** what the walls and floor are, which way doors swing, what stays, how the room is used, and what you want from it.

## Install (command line)

You need [uv](https://docs.astral.sh/uv/) and Node 18+ (layout checks). Git with [Git LFS](https://git-lfs.com) is optional: it keeps history and a backup of your rooms, with scans and photos stored outside the repo's history. Blender is **not** needed: the render tools install Blender as a Python module (`bpy`, about 400 MB) on first use.

```sh
uv tool install git+https://github.com/ravimody/roomwright   # the `roomwright` command
roomwright doctor                                           # checks the above; --full also installs bpy
```

The CLI's own commands are `init`, `demo`, `new-room`, `serve`, `list`, `docs` and `doctor`, plus `render-modal` (it runs `modal run tools/render_modal.py`). Every other `roomwright <tool>` runs the matching file in `tools/` from a room folder. Working inside the engine repo instead? Use `uv run ../../tools/<tool_with_underscores>.py` with the same arguments (`.mjs` tools with `node`, `.sh` with `bash`).

## Try the sample household first (optional)

```sh
roomwright demo my-demo && cd my-demo/rooms/sample-living   # a made-up living room with a stand-in scan
roomwright geometry-check draft-with-mistakes                # finds the three planted mistakes
roomwright render-photoreal proposal --lighting evening --views fireplace --samples 16
```

## Start a household and a room

```sh
roomwright init my-home && cd my-home        # optional: git init && git lfs install
# then fill in HOUSEHOLD.md, or ask the agent to interview you
roomwright new-room living-room ~/Downloads/scan.glb        # template + align + map + views + furniture draft (~1 min)
roomwright new-room study                                   # no scan: the template only
```

Run `new-room` from the household folder. Put photos in `rooms/<room>/photos/originals/` and notes in the room's `README.md`.

## The loop (from inside `rooms/<room>/`)

| Step | Command | Output |
|---|---|---|
| Read the draft | open `renders/map/review.png`, `renders/views/plan.png`, `elev_*.png` | outline, openings, ceiling levels |
| Measure a wall | `roomwright wall-profile north` (wall names are plan labels, not compass directions: [COOKBOOK](../COOKBOOK.md#accuracy-and-directions)) | depth past the wall at 10 heights every 5 cm |
| Fill in `room.json` | doors (swing), windows, fixtures, materials, lights, scenes, cameras | the model |
| Model the furniture | catalog entries: `box`, then `parts` or a model file (`roomwright model-import file.fbx --spec W,D,H`); [MODELING.md](MODELING.md) | `catalog.json`, `models/` |
| Validate | `roomwright validate-room` | schema and consistency errors |
| Check against the scan (when there is one) | `roomwright geometry-check as-scanned` | `renders/geometry_check/`: per-camera depth diff, plan height map, ranked items |
| Lay out | `roomwright serve`, then the editor in a browser | `layouts/*.json` |
| Check a layout | `roomwright check-layout layouts/<name>.json`, `roomwright flow-plan <name>` | overlaps, clearances, path widths |
| Render | `roomwright render-photoreal <layout> --lighting day --views a,b --samples 16` (`--lighting` takes `day`, `night`, `evening`, `standard` or a scene you named in `room.json`) | `renders/photoreal/<layout>/` |
| Compare with the scan | `roomwright scan-compare <render folder name> [views]` (a folder name under `renders/photoreal/`, not a path) | `renders/scan_compare/` |
| Batch | `roomwright render-batch render_sets/report.json` (or `roomwright render-modal --batch …` on cloud GPUs) | many sets |
| Match real photos | `roomwright photo-match <photo> --f35 24 --eye … --target … --points pts.json`, then `roomwright photo-compare`, `roomwright color-match`, `roomwright light-match` | 1:1 sheets, fitted exposure, white balance, colours and each light's lumens and kelvin |
| Report | `roomwright build-report`, then open `report/index.html`; `roomwright export-pdf report/index.html` for a PDF | the deliverable, in the household's language |

`roomwright list` shows every tool with a one-line description; [TOOLS.md](TOOLS.md) has every tool's options.

## Check the whole household

```sh
roomwright validate-room --all          # from the repo root
roomwright smoke-rooms --fast           # every pipeline step on every room; drop --fast to include Blender steps
```
