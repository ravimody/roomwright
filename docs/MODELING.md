# Modelling furniture and objects

roomwright ships no furniture library: the things people own are too varied for one. Instead, an agent models each piece
from its real dimensions, in one of three ways, and checks it against the scan. This page is the how-to.

| Way | Use it for | Where it lives |
|---|---|---|
| **`box`** | blocking in: a piece's footprint and height, before anything else | the catalog entry: `"model": "box"` |
| **`parts`** | most furniture: a table, a chair, a sofa, a lamp, a bookcase, a bed, built from a dozen primitives | the catalog entry: `"model": "parts"` plus a `parts` list |
| **`glb`** | a specific product or an organic shape (a plant, a carved chair) when a good model file exists | `"model": "glb"`, `"file": "models/<name>.glb"` |
| a **builder** | a family of pieces you'll reuse with options (sofas with any number of seats, tables with leg styles) | code: `builders/<name>.py` + `.js` next to `rooms/` (see `builders/README.md` in a household made with `roomwright init`) |

Most pieces need only `box` then `parts`. Write a builder only when the same family keeps coming back with options.
Catalogs merge in order: the engine's `shared/catalog.json` (generic entries only), the household's `catalog.json`
(next to `rooms/`), then the room's `catalog.json`; later entries win, and a layout item can override any key.

## The workflow

1. **Get the real size** from the spec sheet, the maker's drawing, or a tape measure (for secondhand, antique and
   built-in pieces). The scan places a piece in the room; sizes that matter come from a tape. Width is left to right as
   you face the piece's front, depth front to back.
2. **Block it in as a `box`** with that `w`, `d`, `h` and a `color`, place it in a layout, and run
   `geometry_check.py <layout>`. If the box is in the wrong place or the wrong size, no amount of detail will help.
3. **Draw it with `parts`**: the few shapes that make its silhouette (top, legs, apron; seat, back, arms; shade, pole,
   base). Detail that won't show at room scale (hardware, stitching) can wait. Match the room's style: a slab-and-post
   table reads modern in any colour.
4. **Check it**: `geometry_check.py <layout>` again (the item's mismatch should drop; red = the model has something the
   room doesn't), then a close camera with `render_photoreal.py ... --samples 16` and the editor (`roomwright serve`).
5. **Or use a model file** when the exact product matters and a file exists: `tools/model_import.py` (below).

## `parts` reference

Positions are in metres in the item's own frame: **x** to the right as you face the item's front, **y** toward its
back, **z** up, with the origin at the centre of its footprint on the floor. At `rot: 0` the front faces plan south (−y in
the room; plan labels, not compass directions: [COOKBOOK](../COOKBOOK.md#accuracy-and-directions)); the layout's `x`, `y`, `rot` place the whole item.

| `shape` | Keys | `at` is |
|---|---|---|
| `box` (default) | `size: [w, d, h]`, `bevel` (edge round-over, m, default 0.004) | the centre |
| `cylinder` | `r`, `h`, `axis` (`z` upright, `x` or `y` lying), `open` | the centre |
| `cone` | `r0` (bottom), `r1` (top), `h`, `axis`, `open` (a lampshade) | the centre |
| `sphere` | `r`, `scale: [sx, sy, sz]` (an ellipsoid: a pillow, a pouf, a canopy) | the centre |
| `lathe` | `profile: [[radius, height], ...]` from the bottom up, turned about the vertical axis (turned legs, vases, lamp bases, shades); `open` | the base |
| `extrude` | `points: [[x, y], ...]` (a plan outline around `at`), `h` (shaped tops, a kidney desk, a D-shaped seat) | the base |

Every part also takes:

- `rot: [rx, ry, rz]`: degrees about x, then y, then z (a back post leaning back is `rx` negative).
- `mirror: "x" | "y" | "xy"`: draw it again mirrored across the item's centre line(s), so one leg entry makes four.
- `material`: a name from the entry's `materials`, or a `"#rrggbb"` colour; without it, the item's `color`.
- `seg`: segments around round shapes (default 32). A `cone` with `seg: 4` and `rot: [0, 0, 45]` is a square tapered leg.
- `name` and `role`. `role: "shade"` makes the item a light: a bulb goes in the middle of that part, its output set by the entry's `light` (`lumens`, `kelvin`, dimmer; without it the room's usual bulb or a default is used and reported as ASSUMED). Fixtures without a shade work the same way: make the visible diffuser the `shade` part (a dome, a flat panel, a tube, or a small sphere for a bare bulb) with a `shade` material, so it glows and the bulb inside lights the room.

`materials` maps a name to `{"hex", "kind", "rough", "metal", "coat"}`. `kind`: `paint` (default), `wood` (with grain),
`fabric`, `metal`, `glass`, `shade` (a translucent fabric lampshade: it glows when lit and throws light up and down,
not sideways) or `glow` (lit paper). `rough` runs from 0 (mirror) to 1 (matte); `coat` (0–1) is a clear coat
(polished or lacquered wood).

Never let two parts share a face (an arm's front flush with the base's front, a side's top flush with the top's):
coplanar faces render as black patches. Inset one part a centimetre or let it overhang, as the examples do.

Parts are drawn at the entry's `w`, `d`, `h` (or `partsSize`). A layout item that changes `w`, `d` or `h` stretches the
whole piece to its new size, so model at the catalog size and let one entry serve a few sizes.

Things that keep their usual meaning on a `parts` entry: `seatH` (seats that tuck under a table, or floor cushions),
`kneeSpace` (a table: a number, or `"apron"` to compute it from `apron` and `top`), `clearance`, `baseW`/`baseD`
(footprint at the floor when the top overhangs), `group`, `scanVisible`, and `layer: "ceiling"` for a ceiling light
(pendant, chandelier, flush light, panel, tube, fan light): scenes switch it with the room's ceiling lights rather than
its lamps. `hang: "ceiling"` hangs any item (parts, a model file or a box) from the room's ceiling at its spot, `h`
below it; a layout item's `z` places it by hand instead.

## Examples

Copy one into a catalog and change the numbers. They're starting points, not a library: real pieces differ.

A dining table, 180 × 90 × 75 cm (71 × 35 × 30 in), with square tapered legs:

```json
{
  "dining_table": {
    "name": "Dining table, 180 x 90 cm", "category": "Tables", "model": "parts",
    "w": 1.8, "d": 0.9, "h": 0.75, "color": "#8a5a35", "apron": 0.1, "top": 0.025, "kneeSpace": "apron",
    "materials": {"wood": {"hex": "#8a5a35", "kind": "wood", "coat": 0.3}},
    "parts": [
      {"name": "top", "size": [1.8, 0.9, 0.025], "at": [0, 0, 0.7375], "material": "wood"},
      {"name": "apron", "size": [1.57, 0.02, 0.1], "at": [0, 0.365, 0.675], "mirror": "y", "material": "wood"},
      {"name": "apron", "size": [0.02, 0.71, 0.1], "at": [0.785, 0, 0.675], "mirror": "x", "material": "wood"},
      {"name": "leg", "shape": "cone", "r0": 0.022, "r1": 0.04, "h": 0.725, "seg": 4, "rot": [0, 0, 45],
       "at": [0.785, 0.365, 0.3625], "mirror": "xy", "material": "wood"}
    ]
  }
}
```

A side chair with a leaning back (`seatH` lets it tuck under a table):

```json
{
  "side_chair": {
    "name": "Side chair", "category": "Seating", "model": "parts",
    "w": 0.46, "d": 0.5, "h": 0.9, "color": "#5b3a24", "seatH": 0.46,
    "materials": {"wood": {"hex": "#5b3a24", "kind": "wood", "coat": 0.2}},
    "parts": [
      {"name": "seat", "size": [0.46, 0.44, 0.04], "at": [0, -0.03, 0.44], "bevel": 0.008, "material": "wood"},
      {"name": "leg", "shape": "cylinder", "r": 0.016, "h": 0.42, "at": [0.19, 0.16, 0.21], "mirror": "xy", "material": "wood"},
      {"name": "post", "size": [0.03, 0.03, 0.48], "at": [0.2, 0.2, 0.66], "rot": [-8, 0, 0], "mirror": "x", "material": "wood"},
      {"name": "rail", "size": [0.4, 0.025, 0.08], "at": [0, 0.225, 0.85], "rot": [-8, 0, 0], "material": "wood"},
      {"name": "rail", "size": [0.4, 0.02, 0.05], "at": [0, 0.21, 0.66], "rot": [-8, 0, 0], "material": "wood"}
    ]
  }
}
```

A three-seat sofa, 210 cm (83 in) wide, with seat and back cushions:

```json
{
  "sofa_3seat": {
    "name": "Three-seat sofa, 210 cm", "category": "Seating", "model": "parts",
    "w": 2.1, "d": 0.94, "h": 0.84, "color": "#7d8a8f", "seatH": 0.46,
    "materials": {"fabric": {"hex": "#7d8a8f", "kind": "fabric"}, "legs": {"hex": "#3b2a1e", "kind": "wood"}},
    "parts": [
      {"name": "leg", "shape": "cylinder", "r": 0.02, "h": 0.06, "at": [0.985, 0.4, 0.03], "mirror": "xy", "material": "legs"},
      {"name": "base", "size": [2.06, 0.9, 0.3], "at": [0, 0.01, 0.21], "bevel": 0.02, "material": "fabric"},
      {"name": "arm", "size": [0.2, 0.94, 0.58], "at": [0.95, 0, 0.35], "bevel": 0.04, "mirror": "x", "material": "fabric"},
      {"name": "back", "size": [1.7, 0.22, 0.48], "at": [0, 0.36, 0.6], "bevel": 0.03, "material": "fabric"},
      {"name": "seat cushion", "size": [0.56, 0.7, 0.12], "at": [0.57, -0.1, 0.42], "bevel": 0.03, "mirror": "x", "material": "fabric"},
      {"name": "seat cushion", "size": [0.56, 0.7, 0.12], "at": [0, -0.1, 0.42], "bevel": 0.03, "material": "fabric"},
      {"name": "back cushion", "size": [0.56, 0.16, 0.36], "at": [0.57, 0.17, 0.66], "rot": [-10, 0, 0], "bevel": 0.04, "mirror": "x", "material": "fabric"},
      {"name": "back cushion", "size": [0.56, 0.16, 0.36], "at": [0, 0.17, 0.66], "rot": [-10, 0, 0], "bevel": 0.04, "material": "fabric"}
    ]
  }
}
```

A floor lamp, 160 cm (63 in), with an open fabric drum shade. `role: "shade"` makes it a lamp: a bulb sits in the middle of that part, and `light` sets its real output:

```json
{
  "floor_lamp": {
    "name": "Floor lamp, drum shade", "category": "Lighting", "model": "parts",
    "w": 0.4, "d": 0.4, "h": 1.6, "baseW": 0.3, "baseD": 0.3, "color": "#2b2b2b", "light": {"lumens": 800, "kelvin": 2700},
    "materials": {"metal": {"hex": "#2b2b2b", "kind": "metal", "rough": 0.4}, "linen": {"hex": "#efe8da", "kind": "shade"}},
    "parts": [
      {"name": "base", "shape": "cylinder", "r": 0.15, "h": 0.025, "at": [0, 0, 0.0125], "material": "metal"},
      {"name": "pole", "shape": "cylinder", "r": 0.012, "h": 1.3, "at": [0, 0, 0.675], "material": "metal"},
      {"name": "shade", "shape": "cone", "r0": 0.2, "r1": 0.17, "h": 0.3, "at": [0, 0, 1.45], "open": true,
       "material": "linen", "role": "shade"}
    ]
  }
}
```

A bookcase, 90 × 30 × 180 cm (35 × 12 × 71 in), with four shelves:

```json
{
  "bookcase": {
    "name": "Bookcase, 90 x 30 x 180 cm", "category": "Storage", "model": "parts",
    "w": 0.9, "d": 0.3, "h": 1.8, "color": "#efece4",
    "parts": [
      {"name": "side", "size": [0.02, 0.3, 1.78], "at": [0.44, 0, 0.89], "mirror": "x"},
      {"name": "top", "size": [0.92, 0.31, 0.02], "at": [0, -0.005, 1.79]},
      {"name": "back", "size": [0.86, 0.01, 1.78], "at": [0, 0.145, 0.89]},
      {"name": "plinth", "size": [0.86, 0.02, 0.08], "at": [0, -0.14, 0.04]},
      {"name": "shelf", "size": [0.86, 0.28, 0.02], "at": [0, 0, 0.09]},
      {"name": "shelf", "size": [0.86, 0.28, 0.02], "at": [0, 0, 0.52]},
      {"name": "shelf", "size": [0.86, 0.28, 0.02], "at": [0, 0, 0.95]},
      {"name": "shelf", "size": [0.86, 0.28, 0.02], "at": [0, 0, 1.38]}
    ]
  }
}
```

A bed with an upholstered headboard for a 160 × 200 cm mattress (63 × 79 in; the head is at the back, +y). Mattress sizes and their names differ by country (140 × 200 and 160 × 200 cm are common doubles in Europe; the same name can mean different sizes elsewhere): use the person's mattress size.

```json
{
  "bed_160x200": {
    "name": "Bed for a 160 x 200 cm mattress, upholstered headboard", "category": "Beds", "model": "parts",
    "w": 1.73, "d": 2.15, "h": 1.2, "color": "#8c8577",
    "materials": {"upholstery": {"hex": "#8c8577", "kind": "fabric"}, "sheet": {"hex": "#f2f0ea", "kind": "fabric"},
                  "duvet": {"hex": "#d9d4c7", "kind": "fabric"}, "wood": {"hex": "#4a3626", "kind": "wood"}},
    "parts": [
      {"name": "leg", "shape": "cylinder", "r": 0.03, "h": 0.1, "at": [0.8, 0.95, 0.05], "mirror": "xy", "material": "wood"},
      {"name": "frame", "size": [1.73, 2.07, 0.25], "at": [0, -0.04, 0.225], "bevel": 0.02, "material": "upholstery"},
      {"name": "headboard", "size": [1.73, 0.08, 1.2], "at": [0, 1.035, 0.6], "bevel": 0.03, "material": "upholstery"},
      {"name": "mattress", "size": [1.6, 2.0, 0.28], "at": [0, -0.04, 0.49], "bevel": 0.04, "material": "sheet"},
      {"name": "duvet", "size": [1.68, 1.5, 0.06], "at": [0, -0.32, 0.66], "bevel": 0.03, "material": "duvet"},
      {"name": "pillow", "shape": "sphere", "r": 0.33, "scale": [1, 0.75, 0.25], "at": [0.4, 0.72, 0.71], "mirror": "x", "material": "sheet"}
    ]
  }
}
```

Floor seating: a cushion and a low table (`seatH` marks the cushion as a seat, so it can tuck under the table's edge):

```json
{
  "floor_cushion": {
    "name": "Floor cushion, 55 x 60 cm", "category": "Seating", "model": "parts",
    "w": 0.55, "d": 0.6, "h": 0.08, "color": "#8a6d4f", "seatH": 0.08,
    "materials": {"fabric": {"hex": "#8a6d4f", "kind": "fabric"}},
    "parts": [{"name": "cushion", "size": [0.55, 0.6, 0.08], "at": [0, 0, 0.04], "bevel": 0.025, "material": "fabric"}]
  },
  "low_table": {
    "name": "Low table, 120 x 75 cm, 33 cm high", "category": "Tables", "model": "parts",
    "w": 1.2, "d": 0.75, "h": 0.33, "color": "#6b4a32", "kneeSpace": 0.25,
    "materials": {"wood": {"hex": "#6b4a32", "kind": "wood", "coat": 0.2}},
    "parts": [
      {"name": "top", "size": [1.2, 0.75, 0.03], "at": [0, 0, 0.315], "material": "wood"},
      {"name": "leg", "size": [0.06, 0.06, 0.3], "at": [0.55, 0.32, 0.15], "mirror": "xy", "material": "wood"}
    ]
  }
}
```

A flush ceiling light, 45 cm across, on the ceiling layer. The dome is the `shade` part, so it glows and its bulb lights
the room; `hang: "ceiling"` puts it on the ceiling wherever it's placed. A pendant is the same idea with a cord (a thin cylinder) above
the shade, an LED panel a thin `box` diffuser, a tube or batten light a lying `cylinder`:

```json
{
  "ceiling_light_flush": {
    "name": "Flush ceiling light, 45 cm", "category": "Lighting", "model": "parts", "layer": "ceiling", "hang": "ceiling",
    "w": 0.45, "d": 0.45, "h": 0.12, "color": "#f2f2f0", "light": {"lumens": 2500, "kelvin": 4000},
    "materials": {"base": {"hex": "#e8e8e6", "kind": "metal", "rough": 0.5}, "diffuser": {"hex": "#f4f4f2", "kind": "shade"}},
    "parts": [
      {"name": "base", "shape": "cylinder", "r": 0.2, "h": 0.02, "at": [0, 0, 0.11], "material": "base"},
      {"name": "diffuser", "shape": "sphere", "r": 0.225, "scale": [1, 1, 0.4], "at": [0, 0, 0.1], "material": "diffuser", "role": "shade"}
    ]
  }
}
```

## Model files (`glb`)

A model file is worth it for a specific product whose shape matters (a sculptural chair, a chandelier) or for organic
things (plants). Prepare it with `tools/model_import.py`, which imports GLB/glTF, OBJ, FBX, USD/USDZ, STL, PLY or DAE,
keeps only the meshes, fixes units (cm and mm files are detected), turns the front to −y, puts it on the floor centred
on its footprint, cuts it to a triangle budget, shrinks textures, and writes one GLB:

```sh
uv run tools/model_import.py ~/Downloads/armchair.fbx --out models/armchair.glb --spec 0.78,0.84,0.79
uv run tools/model_import.py ~/Downloads/chair.obj --units cm --front +x --fit 0.55,0.6,0.82
```

It prints the model's size against the spec sheet (`--spec`), or scales it to the spec (`--fit`, uniform; `--stretch`
for each axis). Then add the entry; the renderer and the editor fit the model to `w × d × h` again (`fit`: `scale`,
`stretch` or `none`), so a slightly-off file still lands at the right size. `rotate: [rx, ry, rz]` (degrees, applied
before fitting) turns a file whose front isn't −y or that lies on its side:

```text
"armchair": {"name": "Armchair", "model": "glb", "file": "models/armchair.glb", "w": 0.78, "d": 0.84, "h": 0.79}
```

`file` is looked up in the room folder, then the household folder; keep shared models in `<household>/models/` and
record each one's source and licence in `models/README.md`. Glass and other transparent materials come through the
glTF material; the colour can't be overridden per item (use `parts` if it needs to change).

## Where to find model files

Check the licence of every file before you download it, and again before you commit it anywhere public. A licence that
lets you render a model often doesn't let you redistribute the file: keep such files in the household's own (private)
repo, not in a public one. Last checked October 2026.

| Source | What's there | Licence (summary: read the real terms) |
|---|---|---|
| **Manufacturers' design resources** | Many furniture makers publish models of their products for architects and designers. Herman Miller, for example, offers SketchUp, Revit and AutoCAD files of its products. Search "<brand> 3D models" or "<brand> CAD downloads". | The maker's terms; usually free for designing with their products, not for redistribution. |
| **BIMobject** (bimobject.com) | Manufacturers' product models; formats the maker chose (Revit, ArchiCAD, SketchUp, IFC, 3DS, ...). Free account. | The service's terms plus each manufacturer's licence. |
| **SketchUp 3D Warehouse** (3dwarehouse.sketchup.com) | A very large free library, including manufacturer-uploaded products. Download as `.skp` or `.dae`; SketchUp can export OBJ, and Blender add-ons read `.skp`. | 3D Warehouse Terms of Use: you may use models in your designs and renders; you may not sell or transfer them as stand-alone files. |
| **Sketchfab** (sketchfab.com) | Huge range; filter **Downloadable** and by licence. Downloads come as glTF/GLB. | Per model: most free downloads are CC BY (credit the author), some CC0; store models are paid with their own licence. |
| **Poly Haven** (polyhaven.com/models) | About 85 furniture models plus plants and props, photoscanned and high quality, glTF downloads. | CC0: no conditions. |
| **Kenney Furniture Kit** (kenney.nl) | A low-poly set of chairs, sofas, tables, kitchen and bathroom pieces: good placeholders. | CC0. |
| **CGTrader, TurboSquid / Free3D** | Free and paid models of real products. | Royalty-free licences allow renders but forbid redistributing the files; free uploads can carry their own terms, and "editorial" models can't be used commercially. Check each listing. |
| **Objaverse** | A research dataset of ~800k models collected from Sketchfab. | The dataset is ODC-By, but each object keeps its own CC licence (including non-commercial and share-alike ones); check per object. |

Don't extract models from retailers' "view in your room" or AR viewers, or scrape them from product pages: those files
are licensed to the retailer. If no file exists, `parts` at the spec-sheet size is the honest answer.

## Checking a model against the room

- `geometry_check.py <layout>` scores every item against the scan from every camera and from above; a piece over about
  25% mismatch is wrong until shown otherwise. Fix its size and position from a fine height map of its spot, not by eye.
- Glass and wire (a glass table top, a wire crate) don't scan: set `"scanVisible": false` so the check ignores them.
- Render a close camera at `--samples 16` and look at it before showing anyone: legs on the floor, nothing floating or
  clipping, the front facing the right way (a model turned 180° is the most common mistake: fix the entry's `rotate` for a model
  file, or the layout's `rot`).
