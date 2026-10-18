# Roadmap: steps still done by hand

What still needs a person or hand-tuning, as candidates for the next round of tooling. Already automated: the one-command first pass (`roomwright new-room`), furniture detection, the patchy-ceiling fallback, fixtures on any wall, openings as gaps in a door band, the ray-cast ceiling check, photo-matched cameras, and colour and light fitting from photos.

1. **Door and window types.** The mapper finds openings, but not whether one is a cased opening, a hinged door (and its swing), French doors or a sliding unit. Idea: classify from the textured elevation (mullions, handle positions) and confirm with a same-camera view.
2. **Window sizes and glazing bars.** Sill and head heights and `grid` are read by eye from elevations.
3. **Fixtures.** Fireplaces, niches and panelling are placed and parameterised by hand from sections; orthographic elevations can suggest built-ins that aren't there.
4. **Recessed lights.** Located by eye in the looking-up ceiling render; they could be auto-detected as bright blobs.
5. **Materials.** Wall, trim and floor colours are sampled from the scan, then hand-tuned against `scan-compare` (often several rounds for a wood floor). Paint codes still come from the person.
6. **Lighting calibration** (mostly automated). Lights are physical data (lumens, kelvin, dimmer curves, a sky model), unknowns are listed as ASSUMED, `color-match` fits paint colours and `light-match` each light's brightness and colour from photos with known cameras. Still by hand: telling dimmed lamps from phone processing (ask the person), recovering cameras for daylight photos, and lights whose colour changes (a TV's picture).
7. **Furniture inventory** (partly automated). `detect-furniture` finds footprints, sizes and heights; mapping each blob to a catalog type is still by hand. Product research at big retailers is manual browsing in a real browser.
8. **Layout design.** Zones and clearances are iterated by hand with `check-layout`, and cameras are placed by hand.
9. **Render artefacts.** Coplanar faces (black), wall extensions at reflex corners and visible light spheres are found by looking at renders. A lint pass for coplanar or overlapping boxes would catch most of them.
10. **Report writing.** The HTML is hand-written per room; `build-report` only copies images.
11. **Rug recovery.** `rug-from-scan` needs its corners, symmetry centre and smeared regions picked by eye from the top-down view. Edge and border detection could find the corners and borders, and a symmetry search the centre; a plain mirror-correlation search is not robust enough on real, worn rugs.
12. **Scenic wallpapers.** `wallpaper-from-scan` tiles one captured stretch, so a scenic paper repeats where the real one doesn't. Capturing each wall separately would fix that.
13. **Ceiling light types.** Pendants, panels and tube lights are modelled by hand as items (`layer: "ceiling"`); only recessed downlights come from `room.json` data.
14. **Window coverings.** Shutters, blinds and curtains aren't data yet, so their state per scene (half-closed against summer sun) can only be approximated with `daylight.scale`.
15. **Floor textures.** One wood-laminate texture ships; tile, stone, tatami and carpet floors are a plain colour (`"texture": "none"`).
16. **Access checks.** Turning space, door clear widths and reach ranges are checked by hand with `flow` paths and `keepClear` rectangles.
17. **Trade outputs.** No dimensioned drawing export (PDF, DXF) and no bill of materials totalled across rooms or units.
18. **Outdoor spaces.** The mapper needs a ceiling, so balconies and verandas are outlined by hand.
19. **Rooms without a scan.** The model is typed in by hand from a full set of tape measurements (COOKBOOK, "Without a scan"). Idea: draft `room.json` from about 20 photos plus the room's length, width and ceiling height (a photo-mode reconstruction scaled by one measured length, or landmarks fitted with `photo-match`), state the expected accuracy, and test it against a room that also has a scan.
