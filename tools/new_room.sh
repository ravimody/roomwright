#!/bin/bash
# First pass for a new room, from a phone scan to a draft room.json, a draft furniture list and review images.
#
#   tools/new_room.sh <room-name> [path/to/scan.glb]
#
# Without a scan it only creates rooms/<room>/ from the template: fill room.json from tape measurements (COOKBOOK,
# "Without a scan"); the scan checks are skipped and reports say so.
#
# Steps (each is also runnable on its own; see COOKBOOK.md section 2):
#   1. rooms/<room>/ from rooms/_template/, scan copied to scan/scan_raw.glb
#   2. align_and_render.py   -> scan/scan_aligned.glb, scan/alignment.json, renders/plan_cut*.png, elev_*.png
#   3. map_room.py           -> renders/map/room_draft.json (+ review.png, ceiling.png)
#   4. room.json seeded from the draft (outline, ceiling, scan transform, candidate openings) if still the template
#   5. room_views.py         -> renders/views/plan.png + elev_*.png in room coordinates (read doors/windows here)
#   6. detect_furniture.py   -> renders/map/furniture_draft.json + furniture.png (one footprint per piece)
# Then by hand: doors/windows/fixtures in room.json, map furniture blobs to catalog types, cameras, style.
set -euo pipefail

ROOM_NAME="${1:?usage: tools/new_room.sh <room-name> [scan.glb]}"
SCAN="${2:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOMS_DIR="${ROOMS_DIR:-${ROOT}/rooms}"  # where rooms live (roomwright new-room points this at your own repo)
ROOM="${ROOMS_DIR}/${ROOM_NAME}"
[[ "${ROOM_NAME}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "room name must be lowercase letters, digits and dashes (e.g. family-room)" >&2; exit 1; }
LOG="$(mktemp "${TMPDIR:-/tmp}/new_room.XXXXXX")"
trap 'rm -f "${LOG}"' EXIT

# Run one step; on failure show the end of its log and stop. On success print the lines matching $1.
step() {
  local keep="$1"; shift
  if ! "$@" >"${LOG}" 2>&1; then tail -20 "${LOG}"; echo "FAILED: $*" >&2; exit 1; fi
  grep -E "${keep}" "${LOG}" || true
}

if [ ! -d "${ROOM}" ]; then
  cp -R "${ROOT}/rooms/_template" "${ROOM}"
  echo "created ${ROOM}/"
fi
if [ -z "${SCAN}" ]; then
  echo "no scan: fill ${ROOM}/room.json from tape measurements (outline, ceiling, doors, windows; COOKBOOK \"Without a scan\")."
  echo "Layouts, flow checks and renders work; the scan checks (geometry-check, ceiling-compare, scan-compare) are skipped."
  exit 0
fi
if [ -f "${ROOM}/scan/scan_raw.glb" ]; then
  cmp -s "${SCAN}" "${ROOM}/scan/scan_raw.glb" || echo "note: rooms/${ROOM_NAME}/scan/scan_raw.glb already exists and differs from ${SCAN}; keeping the existing scan"
else
  cp "${SCAN}" "${ROOM}/scan/scan_raw.glb"
fi
cd "${ROOM}"

echo "== align"
T="${ROOT}/tools"
step "Saved|rotat" uv run "${T}/align_and_render.py" -- scan/scan_raw.glb renders
mv -f renders/scan_aligned.glb renders/alignment.json scan/

echo "== map"
step "ceiling|room area|gaps|openings" uv run "${T}/map_room.py"

echo "== seed room.json"
python3 - <<'PY'
import json
from pathlib import Path
room = json.loads(Path("room.json").read_text())
draft = json.loads(Path("renders/map/room_draft.json").read_text())
if room.get("name", "").startswith("<") or room["outline"] == [[0, 0], [4, 0], [4, 3], [0, 3]]:
    for k in ("outline", "wallHeight", "ceiling", "scan"):
        room[k] = draft[k]
    room["candidateOpenings"] = draft.get("candidateOpenings", [])
    Path("room.json").write_text(json.dumps(room, indent=2, ensure_ascii=False) + "\n")
    print("room.json seeded from renders/map/room_draft.json")
else:
    print("room.json already filled in; left alone")
PY

echo "== views"
step "wrote" uv run "${T}/room_views.py"

echo "== furniture"
step "." uv run "${T}/detect_furniture.py"

cat <<EOF

Done. Review:
  rooms/${ROOM_NAME}/renders/map/review.png        outline, walls, openings
  rooms/${ROOM_NAME}/renders/views/plan.png + elev_*  doors, windows, fixtures (room coordinates)
  rooms/${ROOM_NAME}/renders/map/furniture.png     detected pieces
Next: fill doors/windows/fixtures/cameras/style in room.json, map furniture blobs to a layout (COOKBOOK 2c-2e).
EOF
