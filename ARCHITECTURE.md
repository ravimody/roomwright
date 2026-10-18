# Architecture

Software for thoughtful, agent-driven interior design. You hand over a phone 3D scan of a room (or tape measurements and photos) plus a little guidance. An agent turns it into a measured model and layout options, renders photoreal "today vs. proposal" views by day and night, and writes a report with choices, reasoning, and things to buy, find secondhand or have made.

## Purpose

Two goals, equally important:
1. **Keep each household's (or client's) rooms current.** Each room's README, report, layouts and purchase plan reflect today's decisions.
2. **Generalize what's learned** into the engine and its docs, so the next room, in any household, starts further along.

## Principles

- **Engine and lessons are generic; the household and its rooms are data.** Code in `tools/` and `editor/` never names a room, and `COOKBOOK.md` holds generic best practice for any room, never a specific room, household or date. Everything room-specific (geometry, materials, lights, cameras, scenes, furniture, flow paths) lives in `rooms/<room>/`; household-wide preferences live in `HOUSEHOLD.md`.
- **Measure, then verify.** When there is a scan, geometric and visual claims are checked by a same-camera comparison with it (`geometry_check.py`, `scan_compare.py`, `blender_scene.py compare`). Phone scans place doors, windows and ceilings within a few cm, but can't identify them, so ask the person when unsure; anything that must fit exactly is confirmed on site. Without a scan, the model comes from tape measurements and photos, and reports say what wasn't verified. How deep to go is the person's choice ([COOKBOOK](COOKBOOK.md#how-much-to-do)).
- **Choices, not one answer.** Reports give a recommendation with its reasons and as many rendered alternatives as the person wants, with links, prices or specs. People have strong opinions, so the reasoning is shown.
- **Design guidance, not rules.** The engine has no taste of its own. [docs/DESIGN_GUIDE.md](docs/DESIGN_GUIDE.md) collects widely shared practice (clearances, light levels, colour, sizing conventions) with its sources, as starting points to explain; the person's style and `HOUSEHOLD.md` come first, and options include creative ones beyond the safe default.
- **Plain files, reviewable diffs.** JSON for data, HTML (or PDF) for reports. Engine changes go through pull requests; a household that keeps its rooms in git can do the same, with Git LFS for scans, photos and renders.

## Data model (per room: `rooms/<room>/`)

| File | What it holds |
|---|---|
| `scan/scan_raw.glb`, `scan_aligned.glb`, `alignment.json` | Phone scan (GLB from a LiDAR or photo-mode scanning app), its axis-aligned copy, and the transform between them; absent for a room measured by hand |
| `room.json` | The room's `style` and `sourcing` (new / secondhand / vintage-antique / custom / existing / mix), then the source of truth for the shell: outline (CCW, metres, origin at the plan's south-west interior corner; plan labels, not compass directions: [COOKBOOK](COOKBOOK.md#accuracy-and-directions)), ceiling (top + downstands, flat or sloped), doors (`style`: door / opening / glass / sliding), windows (`grid`), fixtures (`kind`: fireplace / niche / panel / shelves / art), `materials` (wall/trim/floor colours, `hex` allowed), `lights` (recessed downlights and the room's usual bulb), `daylight`, `scenes` (render lighting), `cameras`, `rules` (keep-clear zones, max distances), `flow` (paths and distances) |
| `catalog.json` | The room's own furniture: sizes, colours, how it's modelled (`box`, `parts`, `glb` or a builder), and product links or a spec card (secondhand and antique search terms, a maker's spec for custom pieces). Merged over the household's `catalog.json`, which is merged over the engine's `shared/catalog.json`; later wins. |
| `layouts/*.json` | Placements `{id, type, x, y, rot, z?, overrides…}`: "as scanned", proposals, options |
| `photos/` | Reference photos from the person |
| `renders/` | Generated: map/review images, scan comparisons, flow plans, photoreal sets |
| `report/index.html` + `report/build.json` | The deliverable, plus which render goes where |
| `README.md` | Brief, constraints, decisions, open questions |

Household (next to `rooms/`): `HOUSEHOLD.md` (the person's answers to the engine's questionnaire, written by `roomwright init`), `catalog.json` (item types used in several rooms), `builders/` (code models: a `<name>.py` + `<name>.js` pair each), `models/` (GLB model files, with their sources and licences).

Engine: `shared/catalog.json` (generic entries only), `shared/pbr/` (CC0 textures), and the modelling kit (`tools/blender_models.py`, `editor/src/kit.js`): the core models `box`, `parts` (primitives listed in the catalog), `glb` (a model file fitted to the item's size), `mat`/`roundRug` (rugs), plus the helpers builders use. No furniture library: see [docs/MODELING.md](docs/MODELING.md).

## Pipeline (`tools/`, run from inside the room folder)

1. **Align:** `align_and_render.py` finds the dominant wall angle and floor height, writes the aligned scan and `alignment.json`.
2. **Map:** `map_room.py` produces a clutter-robust draft outline (ceiling ray-cast plus header band plus under-ceiling wall profiles), ceiling levels and candidate openings. `room_views.py` renders gridded plan and elevations; `region_sections.py`, `wall_profile.py` and `corner_views.py` take targeted measurements.
3. **Verify:** `validate_room.py` (the data against `schema/` plus consistency checks), `ceiling_compare.py` (ray-cast ceiling vs. model), `geometry_check.py <layout>` (model vs. scan depth from every camera plus a top-down height map, with every mismatch pinned on a layout item or shell part), `blender_scene.py compare` (shell vs. scan) and `scan_compare.py` (photoreal vs. scan, same cameras). Against the person's own photos: `photo_match.py` recovers each photo's camera from landmarks, `photo_compare.py` sets photo and model side by side, `color_match.py` fits exposure, white balance and material colours, and `light_match.py` fits each light's brightness and colour temperature (one Cycles light group per light).
4. **Layout:** the browser editor (`server.py` + `editor/`, three.js) for dragging and saving; `check_layout.mjs` for overlaps, clearances, doors, ceiling height and rules; `flow_plan.py` for path widths and seating distances.
5. **Render:** `render_photoreal.py <layout> --lighting <scene>` (`render_batch.py` for sets, `render_modal.py` on cloud GPUs; local GPUs via OptiX, CUDA, Metal, HIP or oneAPI), Blender as a Python module (`bpy`) with Cycles. `blender_scene.py` builds the shell and fixtures from `room.json`, and `blender_models.py` builds each item from its catalog `model` (a core model or a household builder from `builders/`). Lights are physical (`photometry.py`): ceiling lights (recessed downlights and items on the ceiling layer: pendants, flush lights, panels, tubes, fan lights), lamps, accents, fires and screens in lumens, kelvin and cd/m² with their dimmer curves, daylight from a sky model through portals in the openings, and a camera that exposes and white-balances like a phone (or like the matched photo); a light without data uses a stated default, printed as ASSUMED.
6. **Report:** `build_report.py` copies renders into `report/img/` per `build.json`; the HTML is built from COOKBOOK's report blocks for the person's purpose (or the household's own outline). `export_pdf.sh` prints it to PDF.

Every Python tool declares its dependencies inline (PEP 723) and runs with `uv run`; the `roomwright` CLI (`roomwright/cli.py`) runs them by name from a room folder when the engine is installed as a package. `tools/doctor.py` checks a machine, `tools/smoke_rooms.py` runs the pipeline on every room, `tools/fake_scan.py` makes a stand-in scan from a room's model (the made-up sample household in `examples/` uses one, so `roomwright demo` shows every tool), and `tests/` (pytest, in CI) checks tool headers, builder pairs, the schemas against every room, the modelling kit, and that engine code never names a room.

Textures recovered from the scan (e.g. a rug, via `rug_from_scan.py`) or generated (`rug_texture.py`) live in `rooms/<room>/textures/`, and catalog items point at them with `texture`.

## Why these choices

- **GLB in, Blender as a library:** no GUI, scriptable, reproducible, and Cycles gives physically based light, which matters because lighting is usually the main design lever.
- **Modelled from the spec, not from a library:** the possible furniture is too varied for any library, so the engine ships a modelling kit instead. Any product, or an antique described only by a spec, is mocked at its real dimensions in minutes as `parts` (a dozen primitives in the catalog entry), or from a model file when one exists (`glb`, prepared by `model_import.py`). A household writes code builders only for families it reuses with options, in its own `builders/`.
- **Two renderers of the same data:** three.js for fast interactive layout, Cycles for the photoreal check. Both read the same `room.json`, catalogs and layouts. `parts` and `glb` are data, so both draw them the same; a builder is a pair (`<name>.py` for Blender, `<name>.js` for the editor) kept in step.
- **Scenes in data, lights in real units:** the ways a household lights a room (day, dinner, cleaning, a power cut, a festival) are just `room.json` entries that switch and dim its real fixtures by layer or one by one, so a new room's lighting plan is configuration, not code, and a render can be checked against a photo of the room lit the same way.
- **Data checked by schemas, docs generated from code:** `schema/*.schema.json` define every file; `docs/DATA.md` and `docs/TOOLS.md` are generated (`tools/make_docs.py`), so the reference can't drift.
- **An installable engine, households as data:** the engine ships as a package with its tools, editor and shared assets; a household's folder holds `HOUSEHOLD.md`, `AGENTS.md`, its catalog, models and any builders, and `rooms/`.

See [docs/QUICKSTART.md](docs/QUICKSTART.md) to start, and [COOKBOOK.md](COOKBOOK.md) for the step-by-step how-to and best practices; the steps still done by hand are in [docs/ROADMAP.md](docs/ROADMAP.md). Design questions: [docs/DESIGN_GUIDE.md](docs/DESIGN_GUIDE.md).
