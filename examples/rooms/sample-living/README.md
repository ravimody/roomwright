# Sample living room (made up)

A fictional 5.4 × 4.2 m living room for trying every tool without a scan of your own: a chimney breast with a wood
fireplace between two alcoves, a cased beam across the ceiling at 2.38 m (ceiling 2.60 m), two south windows and one
east, a hall door (swings in) and a cased opening to the dining room. Nothing here is a real home or a real product.

## What's here

| | |
|---|---|
| `room.json` | the room as designed: outline, ceiling and beam, doors, windows, fireplace, downlights, scenes, cameras, flow |
| `scan/` | a stand-in phone scan, generated from the room's model (see `scan/README.md`), and its aligned copy |
| `layouts/as-scanned.json` | the furniture as in the scan |
| `layouts/draft-with-mistakes.json` | a first draft with three planted mistakes for the geometry check to find |
| `layouts/proposal.json` | a bigger rug, armchairs angled to the fire, the plant out of the walkway, a second floor lamp, a flush ceiling light on the ceiling layer, and styling: books and objects on the shelves, art over the mantel, cushions, a throw and a vase |
| `layouts/floor-seating.json` | the same room set up for floor seating: floor cushions around a low table on a large rug, with the styled shelves and the art |
| `render_sets/report.json` | today and the proposal, by day and evening (`roomwright render-batch` or `render-modal --batch`) |
| `render_sets/readme.json` | the pictures in the project README: today, the proposal and floor seating on a sunny morning and in the evening |

The furniture is modelled from simple shapes (`parts`, in `../../catalog.json`) plus one CC0 model file (the plant):
no code builders. See docs/MODELING.md.

## Things to try (from this folder)

| Command | What you get |
|---|---|
| `roomwright validate-room` | the data checks |
| `roomwright ceiling-compare` | the ceiling and beam against the scan: 99.6% within 3 cm |
| `roomwright geometry-check as-scanned` | model vs. scan from every camera (97–99% agreement) and a plan height map. A few thin or small pieces (the floor lamp's pole, a table lamp, the pedestal side table) sit just over the CHECK line, as thin parts usually do; a storage basket and a toy box in the scan are listed as unexplained, as real clutter would be |
| `roomwright geometry-check draft-with-mistakes` | flags the three planted mistakes: the sofa (30 cm off), the coffee table (drawn too big) and the east armchair (turned the wrong way), with views down to 83–88% agreement. The same small pieces are flagged again, and so is the plant, partly hidden by the moved sofa |
| `roomwright flow-plan as-scanned` then `proposal` | the walkway behind the sofa: 0.64 m, then 0.78 m once the plant moves |
| `roomwright render-photoreal proposal --lighting evening --views fireplace --samples 16` | a night render: lamps and the fire, downlights and the ceiling light off (other scenes: `day`, `sunny-morning` with the sun through the windows, `night`, `downlights-only`) |
| `roomwright scan-compare proposal` | the scan and the render from the same camera (takes a folder name under `renders/photoreal/`, not a path) |
| `roomwright serve` (from the household folder) | the 3D editor; tick "Original scan" to overlay the scan |

## How it was set up (the same steps as a real room)

1. `align_and_render.py` straightened the scan: floor at −1.152 m (generated at −1.15), turn 12.05° (generated at 12.5°: the noise and drift move the dominant wall angle a little).
2. `map_room.py` drafted the outline (about 5.43 × 4.25–4.29 m against 5.40 × 4.20), the ceiling at 2.61 m and the beam at 2.39 m.
3. The geometry check then showed the scan sitting a few cm north-east of the model: the window casings and sills had
   put the mapper's south wall a few cm outside the real face. The west and south wall faces, measured in the scan,
   moved the origin by (+2, +5.8 cm) (`scan.alignedOrigin` and `scan.position`, as COOKBOOK describes). Views went to
   97–99% agreement.
