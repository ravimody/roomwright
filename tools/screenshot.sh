#!/bin/sh
# Headless screenshot of the editor. Usage: tools/screenshot.sh <out.png> [url-suffix]   e.g. "?room=<room>&view=plan#<layout>"
# Requires the server running on :${PORT:-8765} (uv run server.py 8765). CHROME= overrides the browser; WAIT_MS= the
# render wait (3D rooms with many items can need 25000+ under software WebGL).
OUT="$1"; URL="http://localhost:${PORT:-8765}/editor/${2:-}"
if [ -z "$CHROME" ]; then
  for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" google-chrome google-chrome-stable chromium chromium-browser; do
    if [ -x "$c" ] || command -v "$c" >/dev/null 2>&1; then CHROME="$c"; break; fi
  done
fi
[ -n "$CHROME" ] || { echo "no Chrome/Chromium found; set CHROME=/path/to/chrome" >&2; exit 1; }
PROF=$(mktemp -d "${TMPDIR:-/tmp}/shot.XXXXXX")
rm -f "$OUT"
"$CHROME" --headless=new --use-angle=swiftshader --enable-unsafe-swiftshader \
  --window-size=1600,1000 --timeout=${WAIT_MS:-12000} --user-data-dir="$PROF" --screenshot="$OUT" "$URL" >/dev/null 2>&1 &
for i in $(seq 1 120); do [ -f "$OUT" ] && break; sleep 1; done
pkill -f "$PROF"; sleep 1; rm -rf "$PROF" 2>/dev/null
[ -f "$OUT" ] && echo "saved $OUT" || echo "screenshot failed (try WAIT_MS=30000)"
