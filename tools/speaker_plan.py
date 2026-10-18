# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10.1"]
# ///
"""Surround speaker placement check for a layout: angles, distances, heights and toe-in from the main seat, drawn on
the plan against the Dolby / ITU-R BS.775 targets.

The layout needs `"listening": {"x", "y", "ear", "facing": [dx, dy]}` (main seat, ear height, the direction the
listener faces) and `"channel"` on each speaker item: FL FR C SL SR SBL SBR SW1 SW2. A speaker's catalog entry may give
`channelHeight` (driver/tweeter centre above the speaker's base); otherwise the box centre is used.

  uv run ../../tools/speaker_plan.py <layout> [--out renders/speakers/<layout>.png]     (from inside rooms/<room>/)

Prints a table and writes the plan image plus <out>.json.
"""

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roomframe import font, load_catalog

REPO = Path(__file__).resolve().parent.parent
# horizontal angle targets (degrees off the listener's facing direction; + = to the right). Fronts: Dolby 22-30 deg.
# Surrounds: Dolby 5.1 says 90-110 deg, ITU-R BS.775 100-120 deg; either is fine, so 90-120. Back surrounds 135-150.
TARGET = {"C": (0, 0), "FL": (-30, -22), "FR": (22, 30), "SL": (-120, -90), "SR": (90, 120), "SBL": (-150, -135), "SBR": (135, 150)}
COL = {"C": (60, 60, 60), "FL": (40, 90, 200), "FR": (40, 90, 200), "SL": (200, 90, 40), "SR": (200, 90, 40), "SBL": (130, 60, 160), "SBR": (130, 60, 160)}


def catalog():
    return load_catalog(".")


def analyse(layout, cat):
    lp = layout["listening"]
    fx, fy = lp["facing"]
    face = math.atan2(fy, fx)
    rows = []
    for it in layout["items"]:
        ch = it.get("channel")
        if not ch:
            continue
        s = {**cat.get(it["type"], {}), **it}
        dx, dy = s["x"] - lp["x"], s["y"] - lp["y"]
        dist = math.hypot(dx, dy)
        # angle of the speaker seen from the seat, + to the listener's right
        ang = -math.degrees(math.atan2(math.sin(math.atan2(dy, dx) - face), math.cos(math.atan2(dy, dx) - face)))
        z = (s.get("z") or 0) + s.get("channelHeight", s["h"] / 2)
        r = math.radians(s.get("rot", 0))
        front = (math.sin(r), -math.cos(r))  # plan rotation: 0 = front faces south (-y), 90 = east
        to_seat = (-dx / dist, -dy / dist) if dist else (0, 0)
        off_axis = math.degrees(math.acos(max(-1, min(1, front[0] * to_seat[0] + front[1] * to_seat[1]))))
        lo, hi = TARGET.get(ch, (None, None))
        ok = None if lo is None else lo - 2 <= ang <= hi + 2
        rows.append({"id": it["id"], "channel": ch, "x": s["x"], "y": s["y"], "distance": round(math.hypot(dist, z - lp["ear"]), 2),
                     "angle": round(ang, 1), "target": None if lo is None else [lo, hi], "in_target": ok,
                     "height": round(z, 2), "above_ear": round(z - lp["ear"], 2), "aimed_off_axis": round(off_axis, 0), "name": s.get("name", it["type"])})
    return rows


def draw(room, layout, cat, rows, path):
    xs, ys = [p[0] for p in room["outline"]], [p[1] for p in room["outline"]]
    px, pad = 160, 60
    W, H = int((max(xs) - min(xs)) * px) + 2 * pad, int((max(ys) - min(ys)) * px) + 2 * pad + 40
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im, "RGBA")
    f, fb = font(15), font(18)
    P = lambda x, y: (pad + (x - min(xs)) * px, pad + 40 + (max(ys) - y) * px)
    lp = layout["listening"]
    face = math.atan2(lp["facing"][1], lp["facing"][0])
    for ch, (lo, hi) in TARGET.items():  # target wedges
        if not any(r["channel"] == ch for r in rows) or lo == hi:
            continue
        a0, a1 = face - math.radians(hi), face - math.radians(lo)
        pts = [P(lp["x"], lp["y"])] + [P(lp["x"] + 3.2 * math.cos(a0 + (a1 - a0) * k / 20), lp["y"] + 3.2 * math.sin(a0 + (a1 - a0) * k / 20)) for k in range(21)]
        d.polygon(pts, fill=(*COL[ch], 28))
    d.line([P(*p) for p in room["outline"] + room["outline"][:1]], fill="black", width=3)
    for it in layout["items"]:  # furniture footprints
        s = {**cat.get(it["type"], {}), **it}
        if s.get("ceiling") is not None or s.get("floorLayer") or it.get("channel"):
            continue
        c, sn = math.cos(math.radians(s.get("rot", 0))), math.sin(math.radians(s.get("rot", 0)))
        q = [(s["x"] + ax * c - ay * sn, s["y"] + ax * sn + ay * c) for ax, ay in ((-s["w"] / 2, -s["d"] / 2), (s["w"] / 2, -s["d"] / 2), (s["w"] / 2, s["d"] / 2), (-s["w"] / 2, s["d"] / 2))]
        d.polygon([P(*p) for p in q], fill=(225, 222, 215, 255), outline=(170, 165, 155))
    for r in rows:
        s = {**cat.get(next(i for i in layout["items"] if i["id"] == r["id"])["type"], {}), **next(i for i in layout["items"] if i["id"] == r["id"])}
        col = COL.get(r["channel"], (90, 90, 90))
        if not r["channel"].startswith("SW"):
            d.line([P(lp["x"], lp["y"]), P(r["x"], r["y"])], fill=(*col, 200), width=2)
        c, sn = math.cos(math.radians(s.get("rot", 0))), math.sin(math.radians(s.get("rot", 0)))
        q = [(s["x"] + ax * c - ay * sn, s["y"] + ax * sn + ay * c) for ax, ay in ((-s["w"] / 2, -s["d"] / 2), (s["w"] / 2, -s["d"] / 2), (s["w"] / 2, s["d"] / 2), (-s["w"] / 2, s["d"] / 2))]
        d.polygon([P(*p) for p in q], fill=(*col, 255) if not r["channel"].startswith("SW") else (40, 40, 40, 255))
        fr = (s["x"] + math.sin(math.radians(s.get("rot", 0))) * 0.35, s["y"] - math.cos(math.radians(s.get("rot", 0))) * 0.35)
        if not r["channel"].startswith("SW"):
            d.line([P(r["x"], r["y"]), P(*fr)], fill=(*col, 255), width=3)  # which way it points
        if r["channel"].startswith("SW"):
            continue  # subs: position only, no angle target
        mark = "" if r["in_target"] is None else ("  ok" if r["in_target"] else "  OUT")
        lab = f"{r['channel']} {abs(r['angle']):.0f} deg{mark}  {r['distance']:.2f} m"
        tx, ty = P(r["x"], r["y"])
        d.text((tx + 14, ty - 28), lab, fill=col if r["in_target"] is not False else (200, 30, 30), font=f)
    cx, cy = P(lp["x"], lp["y"])
    d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=(20, 20, 20))
    d.text((cx + 12, cy + 4), "main seat", fill="black", font=f)
    d.text((pad, 10), f"{layout.get('name', '')}: angle from the main seat (target wedges shaded), distance, and which way each speaker points", fill="black", font=fb)
    im.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("--out")
    a = ap.parse_args()
    room = json.loads(Path("room.json").read_text())
    layout = json.loads(Path(f"layouts/{a.layout}.json").read_text())
    cat = catalog()
    rows = analyse(layout, cat)
    out = Path(a.out or f"renders/speakers/{a.layout}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    draw(room, layout, cat, rows, out)
    out.with_suffix(".json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"{'ch':4s} {'angle':>6s} {'target':>12s} {'dist m':>7s} {'height':>7s} {'vs ear':>7s} {'aimed off':>9s}")
    for r in rows:
        t = "-" if r["target"] is None else f"{r['target'][0]}..{r['target'][1]}"
        flag = "" if r["in_target"] is None else ("ok" if r["in_target"] else "OUT")
        print(f"{r['channel']:4s} {r['angle']:6.1f} {t:>12s} {r['distance']:7.2f} {r['height']:7.2f} {r['above_ear']:+7.2f} {r['aimed_off_axis']:8.0f}°  {flag}")
    print("wrote", out)


if __name__ == "__main__":
    main()
