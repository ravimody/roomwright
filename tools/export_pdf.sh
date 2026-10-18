#!/bin/sh
# Print a room report to PDF with headless Chrome (uses the report's @media print CSS).
# Usage: tools/export_pdf.sh rooms/<room>/report/index.html [out.pdf]
# Default output: "<Room> Report (<YYYY-MM-DD>).pdf" in $PDF_DIR if set, else next to the report.
# Chrome: $CHROME if set, else Google Chrome / Chromium found on macOS or on the PATH (Linux).
set -e
HTML="$1"
[ -f "$HTML" ] || { echo "usage: $0 rooms/<room>/report/index.html [out.pdf]"; exit 1; }

find_chrome() {
  if [ -n "${CHROME:-}" ]; then echo "$CHROME"; return; fi
  for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
  for c in google-chrome google-chrome-stable chromium chromium-browser; do
    command -v "$c" >/dev/null 2>&1 && { command -v "$c"; return; }
  done
}
BROWSER=$(find_chrome)
[ -n "$BROWSER" ] || { echo "Chrome or Chromium not found; set CHROME=/path/to/chrome"; exit 1; }

ABS="$(cd "$(dirname "$HTML")" && pwd)/$(basename "$HTML")"  # absolute, so `report/index.html` from a room folder works
ROOM=$(basename "$(dirname "$(dirname "$ABS")")")
NAME=$(echo "$ROOM" | sed 's/-/ /g' | awk '{for (i = 1; i <= NF; i++) $i = toupper(substr($i, 1, 1)) substr($i, 2)} 1')
DIR="${PDF_DIR:-$(dirname "$HTML")}"
OUT="${2:-$DIR/$NAME Report ($(date +%F)).pdf}"
mkdir -p "$(dirname "$OUT")"
PROF=$(mktemp -d "${TMPDIR:-/tmp}/export_pdf.XXXXXX")
TMP="$PROF/out.pdf"
# headless Chrome sometimes writes the PDF and then never exits: run it in the background, wait for a stable file, kill it
"$BROWSER" --headless=new --disable-gpu --user-data-dir="$PROF" \
  --no-pdf-header-footer --virtual-time-budget=15000 --run-all-compositor-stages-before-draw \
  --print-to-pdf="$TMP" "file://$ABS" >/dev/null 2>&1 &
last=-1
for i in $(seq 1 120); do
  sleep 1
  [ -f "$TMP" ] || continue
  size=$(wc -c < "$TMP" | tr -d ' ')
  [ "$size" -gt 0 ] && [ "$size" = "$last" ] && break
  last=$size
done
pkill -f "$PROF" 2>/dev/null || true
if [ -s "$TMP" ]; then mv "$TMP" "$OUT"; echo "wrote $OUT"; else echo "PDF export failed"; rm -rf "$PROF"; exit 1; fi
rm -rf "$PROF" 2>/dev/null || true
