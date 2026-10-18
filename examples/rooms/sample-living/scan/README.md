# Stand-in scan

Not a real scan: `scan_raw.glb` was generated from this room's model by `tools/fake_scan.py`, so the sample room can
show every scan tool without publishing anyone's home.

```sh
uv run ../../../tools/fake_scan.py scan/source-layout.json     # seed 7, defaults below
uv run ../../../tools/align_and_render.py -- scan/scan_raw.glb renders && mv renders/scan_aligned.glb renders/alignment.json scan/
```

- Source: `room.json` plus `source-layout.json` (the as-scanned furniture, a storage basket and a toy box).
- Like a phone scan: one mesh with flat colours; only surfaces visible from walk-through viewpoints (no wall backs, no
  floor under the sofa, no tops of the bookcases); holes at the windows and a 0.6 × 0.5 m ceiling patch; 6 mm noise
  and a 1.5 cm drift across the room; turned 12.5° and offset, with the floor 1.15 m below the origin.
