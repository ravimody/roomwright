"""The layout checker's rules (tools/check_layout.mjs, shared with the editor) and the local server's safety."""

import http.client
import importlib.util
import json
import shutil
import subprocess
import threading

import pytest
from conftest import REPO

NODE = shutil.which("node")

ROOM = {
    "name": "Test room",
    "outline": [[0, 0], [5, 0], [5, 4], [0, 4]],
    "wallHeight": 2.5,
    "wallThickness": 0.12,
    "ceiling": {"top": 2.5, "downstands": [{"name": "beam", "z": 2.2, "rect": [0, 0, 5, 1]}]},
    "doors": [],
    "windows": [],
    "fixtures": [],
}
CATALOG = {"items": {
    "shelf": {"name": "Shelf", "model": "box", "w": 0.9, "d": 0.2, "h": 0.04, "mount": "wall"},
    "vase": {"name": "Vase", "model": "box", "w": 0.15, "d": 0.15, "h": 0.25},
    "basket": {"name": "Basket", "model": "box", "w": 0.4, "d": 0.3, "h": 0.2},
    "towels": {"name": "Towels", "model": "box", "w": 0.36, "d": 0.26, "h": 0.05},
    "table": {"name": "Table", "model": "parts", "w": 1.0, "d": 2.0, "h": 0.76, "apron": 0.11, "kneeSpace": "apron"},
    "chair": {"name": "Chair", "model": "box", "w": 0.46, "d": 0.48, "h": 0.95, "seatH": 0.45},
    "stool": {"name": "Bar stool", "model": "box", "w": 0.4, "d": 0.4, "h": 0.75},
    "seat": {"name": "Sectional piece", "model": "box", "w": 1.0, "d": 0.9, "h": 0.8, "clearance": {"front": 0.6}},
    "fan": {"name": "Fan", "model": "box", "w": 1.3, "d": 1.3, "h": 0.4, "hang": "ceiling"},
}}


def item(i, t, x, y, **kw):
    return {"id": i, "type": t, "x": x, "y": y, "rot": 0, **kw}


def check(tmp_path, items, room=None, extra=None):
    """Run check_layout.mjs on one layout in a throwaway room; returns (exit code, stdout)."""
    (tmp_path / "room.json").write_text(json.dumps(room or ROOM))
    (tmp_path / "catalog.json").write_text(json.dumps(CATALOG))
    (tmp_path / "layouts").mkdir(exist_ok=True)
    (tmp_path / "layouts/t.json").write_text(json.dumps({"name": "t", "items": items, **(extra or {})}))
    r = subprocess.run(["node", str(REPO / "tools/check_layout.mjs"), "layouts/t.json"], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert "Error:" not in r.stderr, r.stderr
    return r.returncode, r.stdout


needs_node = pytest.mark.skipif(not NODE, reason="node not installed")


@needs_node
def test_stacked_items_are_not_overlaps(tmp_path):
    # vase whose base sits 2 cm into the shelf top (as fitted from a scan), towels inside a basket, and an explicit `on`
    code, out = check(tmp_path, [
        item("shelf", "shelf", 2.5, 3.9, z=1.5), item("vase", "vase", 2.5, 3.9, z=1.52),
        item("basket", "basket", 1.0, 3.0, z=0.7), item("towels", "towels", 1.0, 3.0, z=0.8),
        item("box-a", "basket", 4.0, 3.0), item("box-b", "basket", 4.0, 3.0, z=0.05, on="box-a"),
    ])
    assert code == 0, out
    assert "overlaps" not in out, out


@needs_node
def test_overlap_still_caught(tmp_path):
    code, out = check(tmp_path, [item("a", "basket", 2.0, 2.0), item("b", "basket", 2.1, 2.0)])
    assert code == 1 and "overlaps" in out and "[a, b]" in out, out


@needs_node
def test_chairs_tuck_under_tables_but_tall_stools_do_not(tmp_path):
    code, out = check(tmp_path, [item("table", "table", 2.5, 2.5), item("chair", "chair", 2.5, 1.6, rot=180)])
    assert code == 0, out
    code, out = check(tmp_path, [item("table", "table", 2.5, 2.5), item("stool", "stool", 2.5, 1.6)])
    assert code == 1, out


@needs_node
def test_group_skips_mutual_clearance(tmp_path):
    pieces = [item("s1", "seat", 2.0, 2.5, rot=0), item("s2", "seat", 2.0, 1.75, rot=0)]
    _, out = check(tmp_path, pieces)
    assert "clearance" in out, out
    _, out = check(tmp_path, [{**p, "group": "sectional"} for p in pieces])
    assert "clearance" not in out, out


@needs_node
def test_unknown_type_and_missing_keys_do_not_crash(tmp_path):
    bare = {k: v for k, v in ROOM.items() if k not in ("doors", "windows", "fixtures")}
    bare["rules"] = [{"kind": "minDistance", "itemType": "vase", "fixture": "nope", "min": 1, "message": "keep away"},
                     {"kind": "teleport", "message": "?"}]
    code, out = check(tmp_path, [item("x", "no_such_type", 2, 2), item("vase", "vase", 3, 3)], room=bare)
    assert 'unknown type "no_such_type"' in out and 'no fixture with id "nope"' in out and 'unknown kind "teleport"' in out, out
    assert code == 1, out  # the broken rule is an error


@needs_node
def test_rule_level_is_honoured(tmp_path):
    room = {**ROOM, "rules": [{"kind": "maxDistance", "itemType": "vase", "to": [0, 0], "max": 0.5, "level": "warn", "message": "near the outlet"}]}
    code, out = check(tmp_path, [item("vase", "vase", 3, 3)], room=room)
    assert code == 0 and "warn  near the outlet" in out, out


@needs_node
def test_ceiling_hung_item_takes_room_ceiling(tmp_path):
    # a 0.4 m fan hangs from the ceiling over it: under the 2.2 m beam its blades (1.8 m) clash with a 1.9 m cabinet,
    # under the 2.5 m ceiling (2.1 m) they don't. No fixed default height.
    code, out = check(tmp_path, [item("fan", "fan", 2.5, 0.7, h=0.4), item("tall", "basket", 2.5, 0.7, h=1.9)])
    assert code == 1 and "overlaps" in out, out
    code, out = check(tmp_path, [item("fan", "fan", 2.5, 2.8, h=0.4), item("tall", "basket", 2.5, 2.8, h=1.9)])
    assert code == 0, out


@needs_node
def test_clockwise_outline_warns(tmp_path):
    room = {**ROOM, "outline": list(reversed(ROOM["outline"]))}
    _, out = check(tmp_path, [], room=room)
    assert "clockwise" in out, out


# ---------- server ----------

def load_server():
    spec = importlib.util.spec_from_file_location("server", REPO / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def server(tmp_path):
    rooms = tmp_path / "rooms"
    (rooms / "demo/layouts").mkdir(parents=True)
    (rooms / "demo/room.json").write_text(json.dumps(ROOM))
    (rooms / "_template").mkdir()
    (rooms / "_template/room.json").write_text("{}")
    (rooms / "broken").mkdir()
    (rooms / "broken/room.json").write_text("{not json")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/config").write_text("secret")
    httpd = load_server().serve(tmp_path, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], rooms
    httpd.shutdown()
    httpd.server_close()


def req(port, method, path, body=None, host="localhost"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers={"Host": f"{host}:{port}", "Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def test_server_lists_rooms_and_hides_template(server):
    port, _ = server
    code, data = req(port, "GET", "/api/rooms")
    rooms = {r["id"]: r for r in json.loads(data)}
    assert code == 200 and set(rooms) == {"demo", "broken"} and "error" in rooms["broken"]


def test_server_refuses_foreign_host_and_private_paths(server):
    port, _ = server
    assert req(port, "GET", "/api/rooms", host="evil.example")[0] == 403
    for path in ("/.git/config", "/rooms/../.git/config", "/server.py", "/rooms/demo/.hidden", "/tools/check_layout.mjs"):
        assert req(port, "GET", path)[0] == 404, path
    assert req(port, "GET", "/rooms/demo/room.json")[0] == 200
    assert req(port, "GET", "/shared/catalog.json")[0] == 200
    assert req(port, "GET", "/editor/index.html")[0] == 200


def test_server_save_conflicts_and_keeps_keys(server):
    port, rooms = server
    layout = {"name": "A", "items": [], "listening": {"x": 1, "y": 2}}
    assert req(port, "PUT", "/api/rooms/demo/layouts/a", json.dumps(layout))[0] == 200
    assert req(port, "PUT", "/api/rooms/demo/layouts/a", json.dumps(layout))[0] == 409
    assert req(port, "PUT", "/api/rooms/demo/layouts/a?overwrite=1", json.dumps({**layout, "name": "B"}))[0] == 200
    saved = json.loads((rooms / "demo/layouts/a.json").read_text())
    assert saved["name"] == "B" and saved["listening"] == {"x": 1, "y": 2}
    assert not list((rooms / "demo/layouts").glob(".*"))  # no temp files left behind
    assert req(port, "PUT", "/api/rooms/demo/layouts/Bad_Name", json.dumps(layout))[0] == 400
    assert req(port, "PUT", "/api/rooms/_template/layouts/a", json.dumps(layout))[0] == 400
    assert req(port, "PUT", "/api/rooms/demo/layouts/b", "{nope")[0] == 400
    assert req(port, "PUT", "/api/rooms/demo/layouts/b", json.dumps({"name": "no items"}))[0] == 400


def test_server_creates_missing_layouts_folder(server):
    port, rooms = server
    (rooms / "solo").mkdir()
    (rooms / "solo/room.json").write_text(json.dumps(ROOM))
    assert req(port, "PUT", "/api/rooms/solo/layouts/first", json.dumps({"name": "x", "items": []}))[0] == 200
    assert (rooms / "solo/layouts/first.json").exists()


def test_server_serves_household_builders_and_models_only(server):
    port, rooms = server
    home = rooms.parent
    for rel, text in (("builders/chair.js", "export const BUILDERS = {};"), ("builders/_helpers.js", ""), ("models/x.glb", "glb"),
                      ("catalog.json", '{"items": {}}'), ("HOUSEHOLD.md", "private"), ("rooms/demo/builders/lamp.js", "")):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(text)
    code, data = req(port, "GET", "/api/builders?room=demo")
    assert code == 200 and json.loads(data) == ["/household/builders/chair.js", "/rooms/demo/builders/lamp.js"]
    for path in ("/household/builders/chair.js", "/household/models/x.glb", "/household/catalog.json"):
        assert req(port, "GET", path)[0] == 200, path
    for path in ("/household/HOUSEHOLD.md", "/household/rooms/demo/room.json", "/household/builders/../HOUSEHOLD.md", "/household/builders"):
        assert req(port, "GET", path)[0] == 404, path


@needs_node
def test_household_catalog_between_shared_and_room(tmp_path):
    # rooms/<room>/catalog.json wins over <household>/catalog.json, which adds types the room doesn't define
    room = tmp_path / "rooms/r"
    room.mkdir(parents=True)
    (tmp_path / "catalog.json").write_text(json.dumps({"items": {"bench": {"model": "box", "w": 1.2, "d": 0.4, "h": 0.45},
                                                                 "vase": {"model": "box", "w": 3, "d": 3, "h": 3}}}))
    _, out = check(room, [item("b", "bench", 2.5, 2.0), item("v", "vase", 1.0, 2.0)])
    assert "unknown type" not in out and "sticks out" not in out and "tall here" not in out, out
