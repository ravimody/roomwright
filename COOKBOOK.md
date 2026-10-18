# Cookbook: from a room to a measured model, layouts and photoreal renders

How a room goes from a scan (or a tape measure) to a verified model, layouts and renders, with best practices for each step. The person's `HOUSEHOLD.md` and the room's `style` and README decide what to design; this page is about using the tools well. Commands: [docs/QUICKSTART.md](docs/QUICKSTART.md); every tool's options: [docs/TOOLS.md](docs/TOOLS.md); every data key: [docs/DATA.md](docs/DATA.md); design questions (clearances, light levels, colour, sizes): [docs/DESIGN_GUIDE.md](docs/DESIGN_GUIDE.md), which is guidance, not rules.

## 1. Before starting a room

### How much to do
Ask how much time the person wants to spend and what's at stake, pick a depth, and say in the report which one was used.

| Depth | When | Includes | Skips |
|---|---|---|---|
| **Quick** (about 30 minutes, plus a one-time ~400 MB download for the first render) | Ideas, a first look, a small budget | Rough measurements or a scan; `box` models; `check-layout` and `flow-plan`; a plan image and one or two quick renders | Scan checks, photo matching, colour and light fits. Labelled "quick, not scan-verified". |
| **Standard** (an evening to a few days) | Most rooms | A scan or careful site measurements; `parts` or model files at real sizes; with a scan, the geometry check before showing renders; the scenes the household uses; a report | Photo-matched colour and light fits, unless colour matters |
| **Verified** | Anything that must fit to the centimetre: built-ins, joinery, drawings for trades | Standard, plus clean ceiling and geometry checks, photo-matched cameras, and every dimension that must fit stated with its source and tolerance and confirmed on site | — |

### How to work with the person
- **Chat only.** Many people never open a terminal. The agent installs and runs everything; the person sends a scan or measurements and photos, answers questions, and gets results in the format they chose. git, Git LFS and pull requests are optional for one household (useful for history and backup); without them, keep a dated change log in the room's README.
- **Hands on.** Every step below is a command anyone can run.
- **Language and units.** Talk and write reports in the person's language and units (`HOUSEHOLD.md`); keep file names and data keys in English, and data in metres.

### The household (once)
`roomwright init` writes `HOUSEHOLD.md`, a questionnaire. Go through it with the person first; it overrides this page and the design guide.

### What to give the agent for a new room
`roomwright new-room <room-name> [scan.glb]` (from the household folder; lowercase and dashes) creates `rooms/<room-name>/` from the template. Then add:

- **Scan** (`scan/scan_raw.glb`; GLB, which most scanning apps export). Best: a phone or tablet with LiDAR and a scanning app; walk slowly and get the ceiling and every corner. Without LiDAR: a photo-mode (photogrammetry) scan, slower and looser, with holes on plain walls. No scan: see below.
- **Photos** (`photos/originals/`). 10–20 from the corners and doorways, close-ups of anything odd (soffits, panels, doors), and a few at night with the lights as they're used. Glass, mirrors and fine detail don't scan, so photograph them. HEIC is fine.
- **Notes** (the room's `README.md`):
  - what the room is for and who uses it, by day and at night, and how it's lit now;
  - wall finish (paint brand and code if known, else a daylight photo with white paper against the wall; wallpaper, plaster, tile);
  - floor (wood, tile, stone, laminate, vinyl, tatami, carpet…);
  - fixed things, doors and which way they swing, sockets and switches, heating and cooling (radiators, AC units, fans), backup power;
  - what each piece of furniture is (product links are best);
  - what can't change (a rental's rules), and the goal.
- **Style** (README and `room.json` `style`). Ask per room: one home can mix styles. A name in the person's words, what to avoid, 2–3 reference photos in `photos/reference/`. Every pick follows it.
- **Sourcing** (README and `room.json` `sourcing`): `new`, `secondhand`, `vintage-antique`, `custom` (a local maker), `existing` (rearrange what they own) or `mix`, for furniture and for practical items.
- **Needs and rules** (README): accessibility (wheelchair, walker, low vision), children and pets, and any placement rules the person follows (Vastu, feng shui, a prayer direction, a shrine), recorded as their own constraints and against true north ([Accuracy and directions](#accuracy-and-directions)). Zones to keep clear go in `room.json` `rules` as `keepClear` (rules are `keepClear`, `maxDistance` and `minDistance`).

The more of this is known up front, the fewer correction rounds. A scan can't tell which way a door swings, a mirror from an opening, the model of a piece or the real paint colour, so ask.

### Without a scan
Measure with a tape or laser: each wall, both diagonals (is the room square?), door and window positions, sill and head heights, the ceiling height and any beams or slopes; take photos. `roomwright new-room <room-name>` without a scan creates the folder from the template; type the measurements into `room.json`. Layouts, `check-layout`, `flow-plan` and renders all work; the scan checks (`map-room`, `geometry-check`, `ceiling-compare`, `scan-compare`, the editor's scan overlay) don't, and the report says "not scan-verified". `fake-scan` can turn the hand model into a stand-in scan for demos and tests, but it only repeats what was typed: it verifies nothing.

## 2. The pipeline

Commands are shown as `roomwright <tool> …`, run from inside `rooms/<room>/` (the agent runs them in chat-only use). In an engine checkout, run `uv run ../../tools/<tool_with_underscores>.py` with the same arguments (`.mjs` tools with node, `.sh` with bash). `new-room`, `init`, `demo`, `serve`, `list` and `docs` are commands of the CLI itself; `new-room` and `serve` run from the household folder. Every Python tool declares its own dependencies (PEP 723): uv fetches Python 3.11 and Blender as a Python module (`bpy`) for the render tools, or the trimesh stack for the measurement tools, on first use. No Blender install needed.

**One command for the first pass:** `roomwright new-room <room-name> <scan.glb>` creates `rooms/<room>/` from the template and runs 2a, 2b and the furniture detector below, seeding `room.json` from the draft. About a minute. Then fill in doors, windows, fixtures, cameras and style by hand.

### 2a. Align the scan
`roomwright align-and-render scan/scan_raw.glb renders`, then move `renders/scan_aligned.glb` and `renders/alignment.json` into `scan/`.

Rotates the scan so walls run along the axes and puts the floor at z = 0. Writes `alignment.json` (the transform, used for loading the raw scan in the editor) and plan and elevation renders.

### 2b. Auto-map the room (first pass, ~10 s)
`roomwright map-room`, then `roomwright room-views`.

`map-room` writes `renders/map/room_draft.json` (outline, ceiling levels, scan transform, candidate openings) and review images (`--out` for another folder). How it stays robust to clutter:
- **The outline comes from the ceiling, not the floor.** It ray-casts up from 1.6 m and flood-fills the ceiling area, so furniture never enters into it.
- **Neighbouring rooms seen through openings are cut off** by the strip of wall between door-head height and the ceiling (the "header band", ceiling minus 0.25 m).
- **Walls are fitted as profiles just under the ceiling** (ceiling minus 0.33 to minus 0.13 m, below any crown moulding or cornice). Real walls reach that band; bookcases and cabinets don't. Each wall is walked in 10 cm steps and split into runs, which also picks up window bays.
- **Openings are gaps in a door band** (1.2–1.85 m) along each wall, with the head height read inside the wall thickness. Closed doors and glass don't show; read those off the elevations.

If the ceiling scan is patchy (dark or glossy ceilings, a light fitting), the flood fill misses part of the room; `map-room` then falls back to the ring of walls (header band plus mid-height walls), closing gaps up to ~1.6 m, and prints `ceiling had gaps: added … m2`.

`room-views` renders a gridded plan (with the outline on top) and four elevations in **room coordinates**. Read door, window, niche and fixture positions straight off these, then confirm tricky spots with `region-sections`, or with `wall-profile <wall>`, which casts rays outward along one wall every 5 cm at ten heights and prints the depth past the wall line. Doorways show as deep or `inf` runs that stop at the header height; closed doors, shades and pictures sit a few cm proud of the wall.

Copy the draft to `room.json` and finish it by hand: doors and openings (with swing), windows (sill and head heights), fixtures, rules, cameras. Treat built-ins as part of the outline when they run floor to ceiling. Use fixtures for shelving niches and mantels; they go on any wall (north and south walls take `x0`, `x1` and `y`; east and west walls take `y0`, `y1` and `x`).

### 2c. Measure and verify the room → `room.json`
`room.json` is the source of truth: outline (counter-clockwise, metres, origin at the plan-south-west interior corner), wall height, ceiling with downstands (flat, polygon or sloped), doors (and swing), windows, fixed fixtures, rules, scan alignment and named render cameras. Axes and wall names are plan labels, not compass directions ([Accuracy and directions](#accuracy-and-directions)).

Measurement tools, roughly in order:
- `sections [--heights …]`: horizontal cuts at several heights, giving wall lines and footprints.
- `region-sections x0 y0 x1 y1 out.png [xcut] [ycut]`: zoomed horizontal and vertical cuts of one area (heights follow the room's ceiling).
- `wall-profile <wall> [from to]`: depth past the wall line at ten heights every 5 cm; stepped walls are measured from their own face.
- `ceiling-compare`: ray-casts the scan's ceiling on a grid from just below the modelled ceiling (so **slopes are measured**, which face-normal filters miss), leaves out cells under tall or ceiling-hung items and along the walls, and prints the share within 3 and 5 cm plus CHECK regions (`renders/ceiling_check.{png,json}`). Target: > 90% within 3 cm.
- `corner-views "<camera>;name:ex,ey,ez:tx,ty,tz" [--lens 18]`: perspective close-ups of the textured scan from room cameras or ad-hoc shots. `ceiling-views [--cut 1.45]`: a north-up reflected ceiling plan with a grid (find downlights and soffits).
- `fake-scan <layout>`: a stand-in scan generated from the model (only surfaces visible from inside, holes at glass, noise, drift, an arbitrary pose), for demos, tests and rooms whose scan can't be shared. The sample household (`examples/`) uses one.
- `blender-scene compare`: side-by-side scan vs. model renders with labelled ceiling heights (colours are relative to the room's own range). Views come from `room.json` `compareViews`, else `cameras`, else four corner views. **The best way to have a person confirm the geometry.**

### 2d. Furniture and equipment
`roomwright detect-furniture` finds the pieces in the scan: everything 0.12–1.9 m above the floor inside the outline (minus a thin wall band) is rasterised, and each connected blob gets its minimum rotated rectangle and height (`renders/map/furniture_draft.json`, `furniture.png`). Tables come out with their chairs attached, so split or merge a few by eye, then map each blob to a catalog type in a layout.

Then model each piece at its real size (the spec sheet or a tape; the scan places it): a `box` first, then `parts` (a dozen primitives listed in the catalog entry) or a model file (`glb`, prepared with `model-import`). The engine has no furniture library; [docs/MODELING.md](docs/MODELING.md) has the workflow, copyable examples and where to find model files. Item types live in the household's `catalog.json` (next to `rooms/`) and each room's `catalog.json`.

### 2e. Layouts and the editor
`roomwright serve` (from the household folder) → http://localhost:8765/editor/, pick a room. Drag, rotate, add from the catalog, and save; Save as… never silently replaces another layout. Layouts are saved to `rooms/<room>/layouts/*.json` with every top-level key kept (e.g. `listening`). Checks run live: overlaps, clearance zones, doors, ceiling height, keep-clear zones and rules. The server answers only to localhost and serves `editor/`, `shared/`, `rooms/` and, under `/household/`, the household's `catalog.json`, `builders/`, `models/` and `textures/`; `--root DIR` serves another household.
From the command line: `roomwright check-layout layouts/<name>.json` (issues name the item ids; exit 1 only on errors).

Catalog items wider at the top than at the floor (a floor lamp whose shade overhangs a sofa arm) take `baseW`/`baseD` for the collision footprint. `keepClear` rules take `maxZ` (default 2.0 m) so a floor-level zone like a hearth ignores things on the mantel. Things that legitimately overlap: an item on another (`on: <id>`, or a `z` at the other's top: a vase on a shelf), chairs tucked under a table (a seat height below the apron, or catalog `kneeSpace`), and pieces of one unit (a sectional's runs, a chair and its ottoman) that share a catalog or layout `group`.

### 2f. Photoreal renders
`roomwright render-photoreal <layout> --lighting <day|night|evening|standard|scene> --views a,b [--samples 48] [--res 1400x875] [--tag folder]`

Cameras come from `room.json` `cameras`; output goes to `renders/photoreal/<tag or layout>/`. Unknown scenes or views are errors that list the valid ones. Quick tests: `--samples 16 --res 700x440`. Batches: list sets in `render_sets/<name>.json` (`[{"layout", "lighting": "day,night", "views", "tag", "meterLayout", "samples", "res"}]`) and run `roomwright render-batch render_sets/<name>.json [--show]`; the same file works with `render-modal --batch`.

Locally, `CYCLES_DEVICE=GPU` uses a GPU when present (OptiX, CUDA, Metal, HIP or oneAPI), else the CPU. On Apple silicon, Metal's first render compiles kernels (tens of seconds); after that it beats the CPU. Local renders cost nothing.

#### Cloud renders on Modal (optional)
`roomwright render-modal --layout <layout> --lighting day,night [--views a,b] [--samples 48] [--res 1400x875] [--tag name]` from a room folder (the room defaults to it), or `--batch render_sets/<name>.json`. It runs `modal run tools/render_modal.py`; it needs a Modal account and login (`modal setup`, stored in `~/.modal.toml`; never commit tokens).

- Every (lighting × view) renders on its own NVIDIA L4 GPU in parallel; the PNGs land in `renders/photoreal/`, named like `render-batch`: `<tag>` for one lighting, else `<tag or layout>-<lighting>`. Output matches local CPU renders within a fraction of a level per pixel at 48 samples. OptiX can draw coplanar faces differently from the CPU and Metal, so a dark strip that shows only locally is a coplanar face to fix.
- About 10 s per view at 48 samples and 1400×875 (1–2 min on a laptop CPU), plus 15–30 s of container start-up: about $0.005–0.01 per view, billed in USD. A 40-view report costs about $0.30–0.40.
- It uploads the engine, the household's catalog, builders, models and textures, and the room data (not scans, photos, renders or reports). **Privacy:** that room data goes to Modal's servers; nothing else leaves the machine unless it's pushed to a remote. Keep household and client repos private, and strip photo location data before sharing anything.
- Batch many sets into one run: separate `modal run` processes started at once tend to hang. Modal's GPU queue can occasionally wait 10+ minutes, so render small A/B checks locally.
- `--probe-gpu` lists the GPU/Cycles devices; `--gpu T4` is cheaper and slower; `--gpu CPU` is for debugging.

### 2g. Report
Each room has `report/index.html`, a local page with side-by-sides, product tables and notes. `roomwright build-report` copies the latest renders into `report/img/` (plus any `copy` entries in `report/build.json`, e.g. flow plans or textures; the file maps `{"images": {name: "<render folder>/<view>"}, "copy": {name: path}}`). For a PDF, `roomwright export-pdf rooms/<room>/report/index.html` (from the household folder) prints it with headless Chrome next to the report, or into `PDF_DIR` (`CHROME=` picks the browser); reports carry an `@media print` block (light theme, cards and figures kept whole), so copy that block into new reports. Write for the person reading: a plain-language summary first, readable type, alt text on every image, larger type and higher contrast for low vision. What goes in a report: [Reports](#reports).

## 3. Best practices (read before starting a room)

Contents: [Scan and geometry](#scan-and-geometry) · [Accuracy and directions](#accuracy-and-directions) · [Reports](#reports) · [Lighting](#lighting) · [Flow](#flow) · [Geometry check](#geometry-check) · [Photos vs. renders](#photos-vs-renders) · [Speakers](#speakers) · [Same-camera check](#same-camera-check) · [Renders and options](#renders-and-options) · [Rugs](#rugs) · [Modelling furniture](#modelling-furniture) · [Room data for rendering](#room-data-for-rendering) · [Blender](#blender) · [Colour and light](#colour-and-light) · [Working with the person](#working-with-the-person) · [Products, sourcing and makers](#products-sourcing-and-makers) · [Plants](#plants) · [Style](#style) · [Outdoor and in-between spaces](#outdoor-and-in-between-spaces)

### Scan and geometry
- Expect the scan to spill into neighbouring rooms through openings. That helps find openings (the floor continues beyond the wall), but keep those areas out of the outline.
- Tall freestanding furniture (bookcases ~2.2 m) looks like a wall at mid-height. Fit walls in the band just under the ceiling.
- Avoid coplanar faces in Blender models (a fixture front exactly on the wall line, sofa arms flush with the base): they render black. Offset by a few mm, or inset parts between their neighbours.
- Wall prisms are extended only at convex (outside) corners. At reflex corners (a chimney breast, a stepped wall) an extension would poke into the room, so the prism stops 3 mm short; flush ends would leave a black coplanar strip.
- Read doors and windows from the textured elevation, not from memory: panel counts, mullions and handles tell a slider from hinged doors and fixed glass. Check them against the `room-views` elevations and a vertical section just inside the wall.
- Glass doesn't scan: a hole in the ceiling scan is often a glass or crystal light fitting; ask for photos. Read openings from a same-camera textured view: sections merge neighbouring openings into one.
- Mirrors show up as holes, with "phantom" geometry behind the wall. Ask before assuming they're openings.
- When filtering by face normals, slanted ceilings get dropped. Use ray-casting or vertical cuts.
- Ceiling edges straddle grid cells, so compare at cell centres. Expect mismatches where objects (tall racks, a sauna or other enclosure, wall-mounted TVs) reach close to the ceiling.
- Read every position from two independent sources (an elevation and `wall-profile` or a section). Two sources also catch a mirrored axis, which a symmetric room hides.
- **Check the origin and the walls.** Find each wall face in the scan (the peak of scan points across the wall, between the skirting and the cornice). `map-room` can put a wall line a few cm off: outside the room where the scan reaches behind a knee wall or a wall-mounted TV, or a few cm outside the real face where a wall is mostly windows with casings and sills. A wall 10 cm off stays inside the geometry check's 12 cm tolerance, but the whole scan then sits a few cm off: small items near the walls get flagged, and strips of wall are listed as unexplained scan geometry. Along a wall that is mostly openings, the mapper can pick the far face. To move the origin by (dx, dy): add (dx, dy) to `scan.alignedOrigin`, add (−dx, 0, +dy) to `scan.position`, and subtract (dx, dy) from every coordinate in `room.json` and the layouts (doors, mullions, fixtures, cameras, flow paths, items), so nothing moves physically.
- Rooms under a roof: ray-cast the ceiling on a grid (the flat part, the slope's knee-wall height and where it meets the flat, dormers) and model each as a `rect` downstand with a `slope`; a dormer is a flat downstand plus a short slope above it.
- Closed shutters, blinds and curtains hide sills, heads and grilles. Ask for photos with them open, or scan with them raised.
- Measure doors from the scan, then **ask which way they swing and what's behind them**. A scan can't tell a cupboard or closet from a solid box or a column.

### Accuracy and directions
- Phone LiDAR scans are good to a few centimetres and drift over a room, most near walls and in long rooms; photo-mode scans are looser. That's enough for layouts, clearances and renders, not for anything cut to fit (built-ins, joinery, worktops, curtain tracks): measure those on site with a tape or laser.
- Give each dimension a source (scan, site measurement, spec sheet) and, for trades, a tolerance. When asked for a real distance, measure the scan, not your own layout placement.
- **True north.** The room's axes and wall names ("north wall") are plan labels. When the sun, daylight or a placement tradition matters, measure true north with a compass app set to true north (or corrected for the local magnetic declination, which can exceed 10°), set `site.northDeg`, and convert before applying any rule tied to real directions. Record such rules in `HOUSEHOLD.md` or the room's README.

### Reports
Assemble the report for its purpose; a household can set its own outline in `HOUSEHOLD.md`.

Common blocks:
1. **Decisions:** the few choices the person needs to make, each with a recommendation and its reasons.
2. **Today vs. the proposal** in the main views, under the scenes the household actually uses, by day and at night.
3. **Lighting:** today's lighting vs. the proposal, built to the person's goal (brighter and more even, softer, sleep-friendly, cheaper to run, working through power cuts); a fixture table (type, where, lumens, colour temperature, how it's controlled in this home) and a scenes table.
4. **Flow and function:** `flow-plan` diagrams (today vs. proposal) and a table of path widths and seating distances against targets agreed with the person (typical values: DESIGN_GUIDE §3).
5. **Options:** as many as the person wants (by default a recommendation and one alternative), each rendered in the main view, with a close camera where details matter.
6. **Buying and making:** for `new`, links, sizes, prices with currency and the date checked; for `secondhand` and `vintage-antique`, spec cards (target size with tolerance, materials, finish, key details, red flags, search terms); for `custom`, a maker's spec (dimensions from the model, materials, finish, hardware) that a local carpenter, joiner or upholsterer can build from; for `existing`, what moves where.
7. **Safety:** anything that affects safety (tip-over, cords, windows, heat, trip hazards), listed even when it was raised in chat.

Add for the purpose:
- **Selling or staging:** what to remove, store or neutralise, listing-photo cameras in daylight, cost against impact, the deadline.
- **Short-lets or many similar units:** one kit adapted per unit, totals across units, durable and easy-to-clean specs, simple controls for guests.
- **Ageing in place or accessibility:** the safety and access list first, fixes in priority order, light levels on routes and at tasks, seated-height views.
- **Renovation:** plans and elevations with the key dimensions marked (the `room-views` grids, `flow-plan` widths), each with its source and tolerance, and what to measure on site. Drawings for trades (DXF, schedules) aren't generated yet: [ROADMAP](docs/ROADMAP.md).

### Lighting
- **Ask how each room is lit today, by day and at night, and how the person wants it.** Bright, even ceiling light; lamps at different heights; candlelight; warm or cool white: each is normal somewhere. Habits differ between rooms of one home too, so record them per room (README) and the household's usual ones in `HOUSEHOLD.md`. Don't add fixture types the household doesn't have or want.
- **Model the real lights, not made-up ones**, in real units (`tools/photometry.py`), in layers:
  - **Ceiling lights** (everything switched with the overheads): recessed downlights (positions in `lights.recessed`; the fixture in `lights.downlights` `{lumens, kelvin, beam, dimCurve, dimToWarm}`, also accepted as `cans`, the US word; one that differs is an object in `lights.recessed`), and any catalog or layout item with `"layer": "ceiling"`: pendants, chandeliers, flush or surface lights, LED panels, tube or batten lights, fan lights.
  - **Lamps:** every other lit item (floor and table lamps, candles), with `light` `{lumens (the whole item), kelvin, dimToWarm: [kFull, kMin], dimCurve, beam}`.
  - **Accents:** lit fixtures (`niche` with `lights`, `art` with `pictureLight` `{lumens, kelvin}`).
  - **Fire, screens and lit enclosures:** a fireplace's `fire` `{lumens, kelvin}` (`insert`: `none` by default, so no fire even when a scene sets `fire`; `wood` or `gas`), a fixture's `screen` `{luminance, hex}`, a sauna's or other lit enclosure's `interiorLight` `{lumens, kelvin, z, size}`.

  Read values off the packaging or spec sheet (a 60 W-equivalent LED bulb gives about 800 lm). `lights.kelvin` is the colour temperature of the room's usual bulbs, for any light that doesn't give its own; give candles and flames their own `light.kelvin` (about 1850 K). Anything still missing uses a stated default (800 lm per bulb, 700 lm per downlight, 2700 K; a fire 1900 K, 300 lm for gas and 1000 lm for wood), and every render prints an `ASSUMED:` line for it: ask the person, or fit it to photos with `light-match`.
- **Scenes** switch and dim the real lights, as the person does: `{"base", "downlights", "ceiling", "lamps", "accents", "fire", "lampsOff", "lampDim", "lampKelvin", "screens", "exposure", "exposureBias", "whiteBalance", "sky", "time"}`, passed as `--lighting <scene>` (an unknown name is an error listing the room's scenes).
  - Bases: `day` (daylight only, lights off), `night` (no daylight; downlights, ceiling items, lamps and accents on), `evening` (no daylight; downlights and ceiling items off, lamps and accents on: one common setup) and `standard` (daylight, downlights, ceiling items and lamps; accents off). In every base the fire and screens stay off unless the scene sets `fire` or `screens`. Night bases use a higher-contrast tone curve.
  - `downlights` (also `cans`) and `ceiling` are dimmer settings, 0–1; `ceiling` defaults to the downlights' setting, so set it on its own when the two are switched apart. `lampsOff`, `lampDim` and `lampKelvin` switch, dim or tune single items by id, ceiling items included (a `lampDim` above 0 switches one on). A scene never sets a light's colour, which comes from the bulb; `lampKelvin` is for tunable bulbs.
  - Name scenes after how the household lives (`today-night`, `dinner`, `homework`, `guests`, `summer-afternoon`, `power-cut`) and keep one for today's lighting as the baseline. Where the power is unreliable, a `power-cut` scene shows what still works on backup (an inverter, a UPS, rechargeable lamps): `downlights: 0`, `ceiling: 0` and `accents: false` for circuits not on backup, and `lampsOff` for the lamps that aren't.
- Shades and diffusers shape light: a fabric shade (a `parts` lamp's `role: "shade"`, or `linen_shade()` in builders) blocks it sideways and casts pools up and down. A shade that lets all light through makes every night render look floodlit.
- Set tunable and smart lights to the colour temperature the household chose, not the factory default.
- After installation, look at the person's own photos for dark zones before suggesting more fixtures, and say "don't buy more yet" when that's the honest answer.
- Dimmers only where the home has them; many homes have plain switches, remotes or app control. A scene gives the setting as on the dimmer (0–1); the default `dimCurve` (`square`: 20% gives about 4%) approximates common phase-cut dimmers; use `linear` or `log` for drivers that behave differently. Bulbs, bases and dimmer compatibility: DESIGN_GUIDE §5.
- The camera behaves like a phone. `exposure` is `"auto"` by default (each view is metered: dim scenes stay darker than bright ones instead of being lifted to the same grey), `"photo"` for a camera matched to a photo (its shutter, aperture and ISO from EXIF), or a number of stops; `exposureBias` adds compensation. `whiteBalance` is `"auto"` (the lights' colour, about 75% neutralised, so warm light still reads warm and cool light cool, as in phone photos; an engine setting fitted to phone photos, not a standard) or kelvin. Each render prints the exposure and white balance it used.
- Keep exposure fixed when comparing levels of one light: copy the printed value into the scene, or pass `--exposure`. For today vs. proposal pairs, `--meter-layout <today>` (render sets: `meterLayout`) meters both on today's layout, so a new light shows as brighter instead of being metered away.
- Daylight is a light source too: a sky outside the windows and glazed doors, with Cycles light portals in every opening. The default is a CIE overcast sky at 10,000 lux (a mid-latitude daytime figure; a far-northern winter afternoon has a tenth of that); in sunny climates use `daylight.sky: "clear"` with `site` `{latitude (whole degrees), northDeg}` and a `time`. Nothing lights the room but what comes through the openings, so a room with small or shaded windows renders dim, as it is. `daylight.scale` is the share that reaches the windows (trees, balconies above, facing buildings, shutters, awnings); fit it from daylight photos.
- Check the night look against a real photo of the room at night if the person has one, and correct the lights' data, not the render.

### Flow
- `flow` (in `room.json` or a layout): `paths` are named polylines with a `min` width; `distances` are item pairs (sofa to sofa, sofa to coffee table). `flow-plan` measures the clear width perpendicular to each path every 5 cm and draws the narrowest point as a dimension line in metres and inches, with the seating distances and door swings, on a plan image (`renders/flow/<layout>.png`, `--scale` for a bigger one). Widths are measured to where furniture meets the floor (`baseW`/`baseD`), ceiling-hung items (`hang: "ceiling"`) are ignored, and a path that runs through furniture is reported `blocked`.
- Check access needs with the same tools: give a path's `min` the wheelchair or walker width agreed with the person, and add `keepClear` rectangles (e.g. 1.5 × 1.5 m) where someone needs to turn.

### Geometry check
For the Standard and Verified depths, with a scan: after geometry or layout changes, before showing renders as the room.
- `roomwright geometry-check <layout>` (about a minute, no Cycles) builds the shell plus the layout's furniture and loads the scan into the same scene. Per `room.json` camera, it casts depth rays through both and saves scan | model | diff in `renders/geometry_check/<layout>/view_*.jpg`: red = the model has something in front of the real surface (extra, too big, misplaced), blue = the room has something the model lacks, grey = scan hole, not judged. It also builds a 4 cm top-down height map (`plan.png`), the most direct footprint and height check. `report.txt` ranks every item and shell part by mismatch, flags `CHECK` at 25%, and lists scan blobs no item explains.
- Targets: about 90% agreement in views of furnished rooms (soft clutter and people's things make up most of the rest); a large piece above about 25% is wrong until shown otherwise. Fix it from a fine height map of that spot, not by eye. Small and thin pieces (lamp poles, table lamps, pedestal tables) often sit just over the flag: say so rather than chase them.
- Not judged: the shell's `beyond_*` stand-ins for neighbouring rooms, and catalog items with `"scanVisible": false` (crystal chandeliers, glass, wire crates; the scan sees the wall or floor behind them). Fan blades, thin poles and live-edge tops always disagree a little.
- Glass parts of items (a glass door, a glass table top; any material with transmission) are see-through for the check, as for the scanner, so views through or from inside a glass-fronted enclosure are judged on what's behind the glass.
- Phone LiDAR misses or distorts black and glossy surfaces, mirrors and glass, and fine detail like foliage or thin legs. When one item didn't scan, put `"scanVisible": false` on that item in the as-scanned layout, not the catalog, place it from whatever did scan plus photos, and say so in the layout's description. Mirrors are always holes or phantoms: mark their catalog entries.
- Measure thin frames (racks, shelving uprights) with horizontal ray probes at several heights: a member that shows at every height is a post; one that shows at one height is an arm, bar or plate. Thin members stay flagged in plan (they're narrower than the 4 cm grid and partly missing in the scan) even once the posts and rails line up.
- A tall box a few cm under the ceiling (a wardrobe, an enclosure) has an unscanned top: the plan rays see inside it, so judge it in the views. Wall-mounted TVs on tilt mounts stand 15–20 cm off the wall; give the fixture that depth.
- Clutter boxes in an as-scanned layout go stale fast; refit them from the height map. Floor clutter under ~0.15 m sits inside the tolerance and can be left out.
- Photoreal side-by-sides hide shape errors the check finds. Model multi-piece furniture (sectionals, modular seating) piece by piece, each with its own arms, back depth and cushion height; one block per sofa rarely matches.
- Read heights, not just footprints: a plan shows where things stand, not how tall they are or which way they face. Fix each flagged piece from a 2–3 cm top-down height map of its spot (ray-cast down with `roomframe.scan_mesh()`, fit a rotated rectangle to the cells in the piece's height band) plus a few height profiles across it (seat, arm, back), and horizontal rays for anything against a wall.
- Measure built-ins with horizontal rays too: niches, arches and recesses are easy to misplace from elevations alone.
- Expected flags: glass fronts the scan sees through (fireplace inserts, display cabinets), upholstery that scans with holes, and soft clutter (throws, pillows). The plan check casts from 2 m, so its score for anything taller (bookcases, wardrobes) is meaningless: judge those in the views.
- Match open and closed: a closed or filled piece modelled as an open frame (or the reverse) is wrong in every view.
- Furniture the plan can't see (chairs pushed under a table, things under a desk): cut the scan points at seat height (0.38–0.5 m) under the top and find the seat blobs; the chair backs show as arcs just outside the table edge. Spindle and ladder backs scan as solid blobs, so those chairs stay well off in the views even when they're placed right.
- Check `rot` against the scan footprint: a wide photoreal view hides a piece turned the wrong way. Identify items from the scan's texture and the photos, not their silhouette.
- A piece with a set-back upper part (secretary, step-back cupboard, hutch) is two catalog items: the base, and the top with `z` = the base height.
- To see what's under a table top, render the textured scan top-down (orthographic) with the camera at the cut height and a tiny clip start: everything above the cut disappears.

### Photos vs. renders
After installation, or to check a model against the room as it is now.
- Recover each photo's camera with `roomwright photo-match <photo> --eye .. --target .. --points landmarks.json`, then add it to `room.json` `cameras` (`eye`, `target`, `lens`, `roll`) and render as usual. `--f35` (the 35 mm-equivalent focal length: 24 for a phone's main camera, 13–14 ultra-wide) is read from the photo's EXIF (HEIC works on any OS); pass it only if that's missing. The tool converts it to a Blender lens. Every tool (renders, scan compare, geometry check, photo match) uses one camera convention including `roll`; `compareViews` take `lens` and `roll` too.
- Landmarks beat edge matching. Pick 8–10 points you can name in both the photo and the model (pixel coordinates in the photo scaled to 1200 px on the long side): door and window corners, soffit and wall corners, ceiling downlights, fixture corners (electrical boxes), the corners of big fixed furniture (a wardrobe, a built-in), pot bases. Mirrors, TVs and anything moved since the scan mislead edge matching. Aim for an RMS reprojection error of about 1% of the frame (10–16 px of 1200); 50+ px means a mislabelled point.
- Let the focal length float (`--fit-lens`) only for ultra-wide shots and only as a check; with few points it can run away to a telephoto. Check every camera with the overlay image (photo | scan | blend) before rendering.
- Build a "today" layout that matches the photos (what's actually installed), and a night scene with the lights as they were. Photos taken later than the scan show what changed; place a new piece by projecting its outline from a photo onto the wall or floor.
- Give each photo camera a `"photo"` key (the photo's path from the room folder) so other tools can find the photo. `roomwright photo-compare renders/photoreal/<folder>` (a path) then builds PHOTO | MODEL sheets for every such camera (`renders/photo_compare/`).
- **Colour from the photos:** `roomwright color-match <layout> <camera> [...] --lighting <scene>` renders each camera at low resolution with a label pass (wall, ceiling, floor, trim, skirting, each item's materials) and an albedo pass, and compares every part's median colour with the photo's. It fits the scene's exposure and white balance to the trusted parts (painted walls, ceiling, doors, skirting; `--trust`), then gives each part the albedo that would reproduce the photo under the model's lighting, as a suggested hex. Sheets and JSON go to `renders/color_match/`; with several cameras, `summary.json` adds the median exposure and white balance and marks a part CONSISTENT when the photos agree on its new colour.
- A part's colour in a photo is albedo × light, so a suggestion is only as good as the model's lighting there. Change a material only when it is CONSISTENT across photos, and prefer daylight photos. When a wall's suggested colours scatter only a few dE around its painted colour, the paint is right: leave it. Light the model doesn't have (a TV left on, a lamp set to a colour) shows up as a big spread and a high dE after the fit; that's the lighting, not the paint. Phones set exposure and white balance per shot, so expect the fitted exposure to vary by a stop or more between photos.
- **Lights from the photos:** `roomwright light-match <layout> <camera> [...] --lighting <scene>` renders every light as its own Cycles light group (daylight, the downlights, each lamp or ceiling-light type, the fire, a lit screen), takes the exposure from each photo's EXIF, and fits each group's brightness, colour temperature and the white balance to the painted surfaces, tile by tile across each wall (how light falls off a wall is what tells two lamps apart). Model the lights as the photos had them first: which lamps were on, a TV left on (`screens`), the scene's dimmer settings. It reports each light relative to an anchor whose lumens come from a spec sheet, plus the "camera offset" (the anchor's own scale: the phone's processing, or every light being dimmer than modelled), and marks a result CONSISTENT when two thirds of the photos agree; `--write` puts those into the data. A light with only one photo, or one the photos disagree on, stays as it is: ask the person instead.
- Phone photos are not light meters. Night photos can come out several stops darker or brighter than their EXIF exposure implies (HDR and night modes, a bright screen in the frame, the ultra-wide camera). Trust the fits for colour temperatures, for brightness relative to an anchor light whose lumens are known, and for white balance (phones neutralise most but not all of a light's colour; the engine assumes about 75%, `photometry.WB_ADAPTATION`), not for absolute brightness. Photos can't tell a dimmed lamp from a darkened picture: ask the person what the lamps are set to.

### Speakers
For home theatre rooms.
- Put `channel` (FL FR C SL SR SBL SBR SW1 SW2) on each speaker item and a `listening` block (`x`, `y`, `ear`, `facing`) on the layout. Then `roomwright speaker-plan <layout>` prints each speaker's angle, distance, height against ear and aim from the main seat, and draws them on the plan against the Dolby/ITU wedges: fronts 22–30°, surrounds 90–120°, backs 135–150°. Catalog `channelHeight` is the driver centre above the speaker's base. Use spec-sheet sizes.
- Find the main seat from the receiver's calibration: the room-calibration distances (Audyssey, Dirac, YPAO and others) to each speaker pin it down, and checking them against the scanned speaker positions also checks the scan.
- Check every speaker move against flow: add the paths people use (door to the wardrobe, to the desk) to `flow`, give stands their base plate as `baseW`/`baseD`, and run `flow-plan` on both layouts. When the ideal angle conflicts with a door or a path, a position still inside the recommended range usually beats the ideal.
- First reflections: mirror the seat across a side wall; where the line to that image crosses the wall is where a panel goes (it often lands right where art hangs). Hang it at the height between the tweeter and the ears, which is lower than art usually goes.

### Same-camera check
Before a final render set, when there's a scan.
- `roomwright scan-compare <render folder name> [views]` (a folder name under `renders/photoreal/`, e.g. `today-day`, not a path) renders the textured scan from the same `room.json` cameras and saves side-by-sides in `renders/scan_compare/`. A view with no model render yet still gets its scan image (handy for placing new cameras). Compare floor, wall and trim colours, the daylight's colour and level, doors and windows, built-ins and furniture positions.
- Elevation renders (`room-views`, `align-and-render`) are orthographic from the room centre, so objects and side walls in front of a wall get projected onto it. Confirm any suspected built-in or opening with a same-camera scan view (`corner-views "name:ex,ey,ez:tx,ty,tz"`) before modelling it.

### Renders and options
- Build every option layout from the **current** plan, not an older one; dropped items reappear otherwise. Say what is in each render.
- Look at each render up close before showing it: props must fit what they sit on, and nothing floats or clips.
- Frame comparisons tight on the item and its real neighbours, and add cameras where people use the room (seated, at a desk or counter, on exercise equipment, in bed). A wide room view hides the difference.
- Put cameras at the eye height of the people who use the room: about 1.5–1.7 m standing, 1.1–1.3 m seated or in a wheelchair, lower for children and floor seating. Steep downward angles feel "from above".
- Quick A/B product checks go in a small side-by-side image opened for the person, not in the main report.
- Tall or glowing pieces can dominate a room in a way the plan doesn't show. Render them at true size from where people sit and stand, and compare with real customer photos before recommending.
- Design with things the person can get: products they can buy, secondhand finds, pieces a local maker can build from a spec, or what they already own. A rendered piece nobody can buy or build is a dead end.

### Rugs
- Recover an existing rug from the scan: `roomwright rug-from-scan snap x0 x1 y0 y1` gives a top-down view with everything above 3 cm cut away (magenta = hidden). Find the corners, then `… rug x0 x1 y0 y1 --corners "TL TR BR BL" --size W,H --center u,v --bad "u0,v0,u1,v1 ..." --out textures/rug-x.jpg` rectifies the drifted quad, fills the hidden parts from the rug's mirror symmetry (about the medallion centre), and borrows offset field texture where every mirror is hidden too. Check `renders/rug/rectified.png` for the medallion centre and smeared areas (pass those as `--bad`).
- Measure the rug from the borders, not the outline: phone scans drift most near walls and hearths. Border widths are equal on all sides, which is a good cross-check.
- Use it with catalog `texture: "textures/<file>.jpg"` on a `mat` item (renders and editor). `textureGain`/`textureSat` lift the scan's dull colours (renders only); verify with `scan-compare`.
- Rug options: `roomwright rug-texture <oushak|serapi|sultanabad|kazak|heriz> W H out.jpg` makes a procedural mock-up of the type (not a copy of any rug). These are classic Persian and Anatolian types; for anything else use a photo texture or a plain `mat` colour.
- Rug sizing conventions: DESIGN_GUIDE §7. Keep hearths and main walkways clear with `keepClear` rules and `flow-plan`.

### Modelling furniture
- The engine draws items from catalog data (`box`, `parts`, `glb`, `mat`) and a household's own builders; it ships no furniture library. Model from the spec sheet, check against the scan (`geometry-check`), and look at a close render. How-to and examples: [docs/MODELING.md](docs/MODELING.md).
- Write a code builder (`builders/<name>.py` + `<name>.js` next to `rooms/`) only for a family of pieces you'll reuse with options. Add both halves together; the editor half can be cheap (right footprint, height, silhouette and colour); JS `x, y, z` = Python `x, z, -y` (front is +Z in the editor, −Y in Blender). `tests/test_engine.py` checks the pairs.
- Match the model's detailing to the room's `style`: a generic slab-and-post table reads modern in any colour.
- Catalogs merge in order: the engine's `shared/catalog.json` (generic entries only), the household's `catalog.json`, the room's `catalog.json`; later wins, and a layout item can override any key. The editor, `check-layout` and the render tools all read them the same way. Each room's actual furniture (exact sizes, colours, product notes) goes in its own catalog.
- Lit items are lamps unless they say otherwise: give pendants, chandeliers, flush lights, panels, tube lights and fan lights `"layer": "ceiling"`, so scenes switch them with the ceiling lights. Model what the household actually uses, floor cushions and low tables as readily as sofas (MODELING has examples).
- Data keys replace special cases: `hang: "ceiling"` hangs an item (a pendant, a fan, a flush light) from the room's ceiling at its spot, `kneeSpace` (or `"apron"`) lets chairs tuck under a table, `seatH` marks a seat.

### Room data for rendering
Set in `room.json`, not code.
- `materials`: wall, trim, skirting (`baseboard`) and ceiling colours, the floor, optional `chairRail` (dado rail) and `crown` (cornice). Defaults are placeholders, so set every room's own. Any material can take `hex` (sRGB from a paint chip or sampled from the scan). The engine ships one wood-laminate floor texture (`shared/pbr/`), whose `hex` is the target average colour (the grain is kept); other floors (tile, stone, terrazzo, tatami, carpet) take `"texture": "none"` and a plain `hex`. Push a little more saturation than the scan sample, because AgX washes out bright colours.
- `daylight` (`sky`, `illuminance`, `scale`, `time`) and `site` (`latitude`, `northDeg`); lights in real units ([Lighting](#lighting)). Exposure and white balance belong to scenes, `"auto"` unless a photo or a comparison calls for numbers.
- `casings: true` adds door and window casings and sills in the trim colour. Window `grid: [cols, rows]` adds glazing bars. Door `style`: `door` (slab), `opening` (cased opening with a hint of the next room), `glass`, or `sliding` (with `mullions` and `handlesAt`, plus a `keepClear` rule for the walk path).
- Wallpaper: `materials.wall.texture` (an image from `wallpaper-from-scan`), `width` (metres per repeat) and `wainscot: {height, hex}`. It's box-projected in world space at true scale above the wainscot. Capture it from a clear, square-on stretch of wall: `roomwright wallpaper-from-scan <north|south|east|west> <from> <to> <z0> <z1>`.
- Architectural fixtures: `kind: fireplace | niche | panel | art | shelves`, on any wall (north/south take `x0`, `x1`, `y`; east/west take `y0`, `y1`, `x`).
- `lights.recessed` (find the downlights in the looking-up ceiling render), `lights.downlights` (their lumens, kelvin and beam from the spec) and `lights.kelvin` (the room's usual bulbs).

### Blender
For code that uses the `bpy` module.
- `import bpy` before `import bmesh`.
- glTF imports use quaternion rotation, so set `rotation_mode = "XYZ"` before using `rotation_euler`.
- Area lights are visible to the camera unless you set `visible_camera = False` (they show up as white rectangles). Don't use fake fill lights.
- Point lights inside glass objects show as glowing spheres. Turn off camera, transmission and glossy visibility.
- Re-exporting a GLB from Blender roughly doubles its size. Load the raw scan and apply the alignment transform instead.

### Colour and light
- **Enable white balance** (`view_settings.use_white_balance`; on in every render). Without it, warm bulbs turn blue-green paint olive. Verify by sampling the wall hue in a photo vs. the render, or fit it with `color-match` / `light-match`.
- Use the exact wall colour: the hex for the paint's brand code, or a sample from a daylight photo with white paper beside it. Roughness about 0.6 for eggshell, higher for matt, lower for gloss.
- Match signature materials (stained wood, stone, a statement fabric) by sampling the person's photos and comparing a render side by side. Colours tuned under one lighting setup drift after white-balance changes.
- Windows and glazed doors (`glass` and `sliding`) show the sky by day and are dark at night. Flat glass lets light straight through (shadow rays pass it; it still reflects), so daylight and a lamp behind a glass door reach the room without noisy caustics.
- Never fix a dark or off-colour render with a fill light, an ambient boost or a colour tweak on a light: find the light the model lacks or has wrong (a TV left on, a dimmer setting, a bulb's real colour) and model it.

### Working with the person
- Deliver the way the household chose (a local web page, a PDF, images in chat), say where the file is, and open it for them where you can.
- Give a recommendation with reasons, adopt the person's edits as the new baseline, and don't relitigate. On taste, raise a concern once and then follow their call; safety concerns also go in the report's safety list.
- When someone else drives the agent (a relative, a designer, a host), confirm whose wishes each decision follows, and keep a designer's own taste out of a client's rooms.
- Keep the room README, report and plan in sync in the same pass whenever a decision changes; stale reports cause repeat corrections.
- Show visuals as plain, labelled side-by-sides, not plots. Show work in progress as you go (`roomframe.show()` opens files in the system viewer).
- Open reports from a checkout with the LFS content; a clone without it shows broken images.
- Keep each door's swing and path clear, and keep proposals inside the room unless an outdoor space is in scope.
- Check every piece's depth and height against the room's clearances (soffits, door swings, the clearances the local electrical code requires around panels and meters) before recommending it.

### Products, sourcing and makers
Buying advice (spec sheets, delivery paths, fit, reviews and deals): DESIGN_GUIDE §13; bulbs, bases, voltage and dimmers: DESIGN_GUIDE §5. For the agent:
- Use the household's markets, currency and budget (`HOUSEHOLD.md`): shops, marketplaces, secondhand, local makers. Compare sellers and delivery costs for the same item, and give direct product links, never search results.
- Big retailers and marketplaces block automated fetching: read specs and prices in a browser session the person controls.
- Who uses the room (children, pets, older people, guests, short-let tenants) changes what's worth buying: precious, cheap, washable or durable.
- Match finishes by sampling photos, not by colour names.
- Reuse what the household owns. Propose smart, dimming or other control hardware only if they want it; for older people and guests, simple switches, timers and motion night lights often work best. Where they want local control, prefer devices that work without a vendor's cloud.

### Plants
- Ask real vs. faux per room. Pick plants for each spot's light and the indoor climate through the year (dry heating, air conditioning, humidity), and check toxicity for the household's pets.
- Count the canopy, not the pot, in flow checks (`baseW`/`baseD` = the pot): a large palm can spread about 0.9 m (3 ft).
- Match plant mock-ups to photos (leaf size, angle and density) before showing options. Corners away from windows render dark by day; use a slightly brighter day scene for plant comparisons and say so.

### Style
- Ask for the room's style and sourcing before proposing anything; picks in the wrong style, or new products for people who buy secondhand, get redone from scratch.
- Style is per room, in the person's words: record it in `room.json` `style` and the README. Calm or maximal, neutral or saturated, floor-level or sofa-centred: all are valid. Never steer every room towards one look (DESIGN_GUIDE, "How to use it").

### Outdoor and in-between spaces
- A balcony, veranda or patio can be designed as a room of its own. `map-room` needs a ceiling, so outline an open space by hand from the floor edge or railings; model the door between it and the house as a shared opening, and render with `daylight.sky: "clear"`, `site` and a `time`.

What still needs a person or hand-tuning, and the tooling planned for it: [docs/ROADMAP.md](docs/ROADMAP.md).
