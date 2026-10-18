# /// script
# requires-python = ">=3.11"
# ///
"""Local dev server: serves the layout editor and reads/writes rooms/<room>/layouts/*.json.

Run: uv run server.py [port] [--root DIR]   (default port 8765), then open http://localhost:8765/editor/
--root is the folder that holds rooms/ (default: this checkout), so the engine can serve a household's rooms kept
in a separate repo.

Serves only editor/ and shared/ (from the engine), rooms/ (from --root) and, under /household/, the household's
catalog.json, builders/, models/ and textures/ (also from --root), to localhost only: requests whose Host header
isn't localhost/127.0.0.1 are refused (DNS rebinding), and hidden paths (.git, .env) are never served.
GET /api/builders?room=<room> lists the editor builder modules to load (household builders/*.js, then the room's).
"""

import argparse
import json
import os
import re
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ENGINE = Path(__file__).resolve().parent
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_BODY = 5 * 1024 * 1024  # a layout is a few kB; refuse anything silly
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
HOUSEHOLD_DIRS = ("builders", "models", "textures")  # served under /household/ from the folder holding rooms/


class Handler(SimpleHTTPRequestHandler):
    rooms_root = ENGINE  # folder holding rooms/; set by serve()

    @property
    def rooms(self):
        return self.rooms_root / "rooms"

    def room_dir(self, name):
        """rooms/<name> if it is a real room folder (not _template), else None."""
        if not SLUG.match(name):
            return None
        d = self.rooms / name
        return d if (d / "room.json").exists() else None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_request(self, code="-", size="-"):  # quiet: log failed requests only
        if str(getattr(code, "value", code))[:1] in "45":
            super().log_request(code, size)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if name in LOCAL_HOSTS:
            return True
        self._json(403, {"error": "this server only answers to localhost"})
        return False

    def translate_path(self, path):
        """Map /editor/* and /shared/* to the engine, /rooms/* to --root, /household/{catalog.json, builders/*,
        models/*, textures/*} to the household files next to rooms/; anything else (or hidden) to nothing."""
        parts = [p for p in unquote(urlsplit(path).path).split("/") if p]
        if not parts or any(p.startswith(".") or p in ("..",) for p in parts):
            return ""
        if parts[0] == "household":  # only the household's catalog and its builders/, models/, textures/ folders
            if parts[1:] != ["catalog.json"] and (len(parts) < 3 or parts[1] not in HOUSEHOLD_DIRS):
                return ""
            base = self.rooms_root
        else:
            base = {"editor": ENGINE / "editor", "shared": ENGINE / "shared", "rooms": self.rooms}.get(parts[0])
        if base is None:
            return ""
        base = base.resolve()
        target = (base / Path(*parts[1:])).resolve()
        return str(target) if target == base or base in target.parents else ""

    def send_head(self):
        if not self.translate_path(self.path):
            self.send_error(404)
            return None
        return super().send_head()

    def do_HEAD(self):
        if self._host_ok():
            super().do_HEAD()

    def do_GET(self):
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        if path in ("", "/", "/editor"):
            self.send_response(302)
            self.send_header("Location", "/editor/")
            self.end_headers()
            return
        if path == "/api/rooms":
            rooms = []
            if self.rooms.is_dir():
                for d in sorted(self.rooms.iterdir()):
                    if not self.room_dir(d.name):
                        continue
                    try:
                        name = json.loads((d / "room.json").read_text()).get("name", d.name)
                    except (OSError, json.JSONDecodeError) as e:
                        rooms.append({"id": d.name, "name": d.name, "error": f"room.json: {e}"})
                        continue
                    rooms.append({"id": d.name, "name": name})
            return self._json(200, rooms)
        if path == "/api/builders":  # editor builder modules: the household's builders/*.js, then the room's own
            urls = [f"/household/builders/{f.name}" for f in sorted((self.rooms_root / "builders").glob("*.js")) if not f.name.startswith(("_", "."))]
            d = self.room_dir((parse_qs(urlsplit(self.path).query).get("room") or [""])[0])
            if d:
                urls += [f"/rooms/{d.name}/builders/{f.name}" for f in sorted((d / "builders").glob("*.js")) if not f.name.startswith(("_", "."))]
            return self._json(200, urls)
        m = re.fullmatch(r"/api/rooms/([^/]+)/layouts", path)
        if m:
            d = self.room_dir(m.group(1))
            if not d:
                return self._json(404, {"error": "unknown room"})
            out = []
            for f in sorted((d / "layouts").glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                except json.JSONDecodeError:
                    continue
                out.append({"slug": f.stem, "name": data.get("name", f.stem), "description": data.get("description", "")})
            return self._json(200, out)
        return super().do_GET()

    def do_PUT(self):
        if not self._host_ok():
            return
        url = urlsplit(self.path)
        m = re.fullmatch(r"/api/rooms/([^/]+)/layouts/([^/]+)", url.path)
        d = self.room_dir(m.group(1)) if m else None
        if not m or not d or not SLUG.match(m.group(2)):
            return self._json(400, {"error": "bad room or layout name (use lowercase letters, digits, dashes)"})
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = -1
        if not 0 < n <= MAX_BODY:
            return self._json(413 if n > MAX_BODY else 400, {"error": f"body must be 1 byte to {MAX_BODY // 1024 // 1024} MB"})
        try:
            data = json.loads(self.rfile.read(n))
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid JSON"})
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return self._json(400, {"error": "layout needs an 'items' list"})
        target = d / "layouts" / f"{m.group(2)}.json"
        if target.exists() and parse_qs(url.query).get("overwrite") != ["1"]:
            return self._json(409, {"error": f"layouts/{target.name} exists; add ?overwrite=1 to replace it", "slug": m.group(2)})
        target.parent.mkdir(exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp")
        try:  # write then rename, so a crash never leaves half a layout
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps(data, indent=2) + "\n")
            os.replace(tmp, target)
        except OSError as e:
            Path(tmp).unlink(missing_ok=True)
            return self._json(500, {"error": f"write failed: {e}"})
        return self._json(200, {"ok": True, "room": m.group(1), "slug": m.group(2)})


def serve(root=None, port=8765):
    Handler.rooms_root = Path(root).resolve() if root else ENGINE
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return httpd


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Local layout editor server")
    ap.add_argument("port", nargs="?", type=int, default=8765)
    ap.add_argument("--root", help="folder that holds rooms/ (default: this checkout)")
    a = ap.parse_args()
    httpd = serve(a.root, a.port)
    if not (Handler.rooms_root / "rooms").is_dir():
        print(f"note: no rooms/ folder in {Handler.rooms_root}", file=sys.stderr)
    print(f"Layout editor: http://localhost:{httpd.server_address[1]}/editor/   (rooms from {Handler.rooms_root / 'rooms'})")
    httpd.serve_forever()
