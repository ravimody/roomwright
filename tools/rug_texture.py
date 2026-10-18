# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Procedural traditional-rug textures (whole rug, not a tile): borders with guard stripes, an optional medallion with
corner spandrels, an allover field motif, abrash (colour banding) and wool grain. For mock-ups of rug *types*, not
copies of any particular rug.

  uv run ../../tools/rug_texture.py <style> <W_m> <H_m> <out.jpg> [--ppm 300] [--seed 1]

Styles (palette + layout presets, tweak in STYLES): oushak, serapi, sultanabad, kazak, heriz.
The image's long side is the rug's length; W is the image width (x), H the height (y).
"""

import argparse
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

STYLES = {
    # soft, low-contrast, large-scale: camel/ivory field, faded terracotta medallion, sage and pale blue accents
    "oushak": dict(field="#d8c19b", border="#b9714f", guard="#e9dcc3", med="#c07a5a", med2="#9eb2b9", accent="#8d9b7c",
                   dark="#6f5a48", medallion="floral", allover="vine", spandrels=True, scale=1.3, contrast=0.55, detail=0.5),
    # Heriz-district, older and softer: apricot field, ivory/pale-blue angular medallion, navy drawing
    "serapi": dict(field="#c4805c", border="#2c3651", guard="#e5d8bf", med="#e6dac2", med2="#86a3b8", accent="#3a4a66",
                   dark="#2a2f45", medallion="geometric", allover="angular", spandrels=True, scale=1.15, contrast=0.8),
    # Sultanabad/Mahal: allover large palmettes on madder red, navy border; no medallion, hides wear
    "sultanabad": dict(field="#8f3227", border="#24314a", guard="#c9a35f", med="#c9a35f", med2="#7c98ad", accent="#24314a",
                       dark="#1d2638", medallion=None, allover="palmette", spandrels=False, scale=1.0, contrast=0.85),
    # Caucasian Kazak-style: brick red field, stacked stepped medallions in ivory/indigo/green, bold
    "kazak": dict(field="#9a3a2b", border="#e4d6b8", guard="#2a3352", med="#e4d6b8", med2="#4f7a52", accent="#2a3352",
                  dark="#1f2438", medallion="stacked", allover="tribal", spandrels=False, scale=1.0, contrast=1.0),
    # Heriz: brick-red field, big angular navy/ivory medallion with blue spandrels
    "heriz": dict(field="#a2402e", border="#22304c", guard="#e2d3b5", med="#22304c", med2="#7f9fb7", accent="#e2d3b5",
                  dark="#1c2236", medallion="geometric", allover="angular", spandrels=True, scale=1.1, contrast=0.9),
}


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def stepped_lozenge(cx, cy, rx, ry, steps=7):
    """Stepped (stair-edged) diamond, the look of knotted geometric medallions."""
    corners = [(cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry)]
    pts = []
    for i in range(4):
        (x0, y0), (x1, y1) = corners[i], corners[(i + 1) % 4]
        for k in range(steps):
            xa, ya = x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps
            xb, yb = x0 + (x1 - x0) * (k + 1) / steps, y0 + (y1 - y0) * (k + 1) / steps
            pts += [(xa, ya), (xa, yb) if i % 2 == 0 else (xb, ya)]
    return pts


def scalloped(cx, cy, rx, ry, lobes=12, depth=0.08, n=240):
    return [(cx + rx * math.cos(t) * (1 + depth * math.cos(lobes * t)), cy + ry * math.sin(t) * (1 + depth * math.cos(lobes * t)))
            for t in (2 * math.pi * k / n for k in range(n))]


def rosette(d, cx, cy, r, c1, c2):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c1)
    for k in range(8):
        a = k * math.pi / 4
        d.ellipse([cx + r * 0.75 * math.cos(a) - r * 0.28, cy + r * 0.75 * math.sin(a) - r * 0.28,
                   cx + r * 0.75 * math.cos(a) + r * 0.28, cy + r * 0.75 * math.sin(a) + r * 0.28], fill=c2)
    d.ellipse([cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3], fill=c2)


def palmette(d, cx, cy, r, c1, c2, c3):
    d.polygon([(cx, cy - r * 1.3), (cx + r, cy - r * 0.2), (cx + r * 0.6, cy + r), (cx - r * 0.6, cy + r), (cx - r, cy - r * 0.2)], fill=c1)
    d.polygon([(cx, cy - r * 0.8), (cx + r * 0.55, cy), (cx, cy + r * 0.7), (cx - r * 0.55, cy)], fill=c2)
    d.ellipse([cx - r * 0.2, cy - r * 0.2, cx + r * 0.2, cy + r * 0.2], fill=c3)


def make(style, W, H, ppm=300, seed=1):
    st = STYLES[style]
    rnd = random.Random(seed)
    w, h = round(W * ppm), round(H * ppm)
    C = {k: rgb(v) for k, v in st.items() if isinstance(v, str) and v.startswith("#")}
    con = st["contrast"]
    soft = lambda c: mix(C["field"], c, con)  # pull motif colours toward the field for low-contrast styles
    img = Image.new("RGB", (w, h), C["field"])
    d = ImageDraw.Draw(img)
    s = min(w, h)
    bw = round(s * 0.13)  # main border width
    g1, g2 = round(s * 0.012), round(s * 0.018)
    fx0, fy0, fx1, fy1 = bw + g1 + g2, bw + g1 + g2, w - bw - g1 - g2, h - bw - g1 - g2
    cx, cy = w / 2, h / 2
    unit = s * 0.06 * st["scale"]

    # allover field motifs
    if st["allover"] == "palmette":
        step = unit * 3.2
        for j, y in enumerate(np.arange(fy0 + step / 2, fy1, step)):
            for x in np.arange(fx0 + step / 2 + (step / 2 if j % 2 else 0), fx1, step):
                palmette(d, x, y, unit * 1.2, soft(C["dark"]), soft(C["med"]), soft(C["med2"]))
                for a in (0.8, 2.4, 3.9, 5.5):
                    d.line([(x, y), (x + math.cos(a) * step * 0.55, y + math.sin(a) * step * 0.55)], fill=soft(C["med"]), width=max(2, round(unit * 0.08)))
    elif st["allover"] in ("angular", "tribal"):
        step = unit * 2.2
        for j, y in enumerate(np.arange(fy0 + step / 2, fy1, step)):
            for x in np.arange(fx0 + step / 2 + (step / 2 if j % 2 else 0), fx1, step):
                c = soft(rnd.choice([C["dark"], C["accent"], C["med2"], C["guard"]]))
                r = unit * rnd.uniform(0.35, 0.6)
                d.polygon(stepped_lozenge(x, y, r, r * 1.2, 3), fill=c)
                if rnd.random() < 0.5:
                    d.line([(x - r * 1.6, y), (x + r * 1.6, y)], fill=soft(C["dark"]), width=max(2, round(unit * 0.07)))
    elif st["allover"] == "vine":
        for _ in range(int((fx1 - fx0) * (fy1 - fy0) / (unit * unit) * 0.35)):
            x, y = rnd.uniform(fx0, fx1), rnd.uniform(fy0, fy1)
            a = rnd.uniform(0, math.pi * 2)
            L = unit * rnd.uniform(0.8, 1.8)
            d.line([(x, y), (x + math.cos(a) * L, y + math.sin(a) * L)], fill=soft(C["accent"]), width=max(2, round(unit * 0.07)))
            if rnd.random() < 0.35:
                rosette(d, x, y, unit * 0.4, soft(C["med"]), soft(C["guard"]))

    # corner spandrels (quarter medallions)
    if st["spandrels"]:
        for qx, qy in ((fx0, fy0), (fx1, fy0), (fx0, fy1), (fx1, fy1)):
            poly = stepped_lozenge(qx, qy, (fx1 - fx0) * 0.22, (fy1 - fy0) * 0.26, 6) if st["medallion"] == "geometric" else \
                scalloped(qx, qy, (fx1 - fx0) * 0.2, (fy1 - fy0) * 0.24)
            d.polygon(poly, fill=soft(C["med2"]), outline=soft(C["dark"]))
        d.rectangle([0, 0, fx0, h], fill=C["field"])  # trim spandrels to the field
        d.rectangle([fx1, 0, w, h], fill=C["field"])
        d.rectangle([0, 0, w, fy0], fill=C["field"])
        d.rectangle([0, fy1, w, h], fill=C["field"])

    # medallion
    long_y = h >= w
    mrx, mry = (fx1 - fx0) * 0.36, (fy1 - fy0) * 0.36
    if st["medallion"] == "geometric":
        pr = (mrx, mry * 1.25) if long_y else (mrx * 1.25, mry)
        d.polygon(stepped_lozenge(cx, cy, *pr, 8), fill=soft(C["dark"]))
        d.polygon(stepped_lozenge(cx, cy, pr[0] * 0.86, pr[1] * 0.86, 7), fill=soft(C["med2"]))
        d.polygon(stepped_lozenge(cx, cy, pr[0] * 0.62, pr[1] * 0.62, 6), fill=soft(C["med"]))
        d.polygon(stepped_lozenge(cx, cy, pr[0] * 0.3, pr[1] * 0.3, 4), fill=soft(C["dark"]))
        rosette(d, cx, cy, unit * 0.6, soft(C["field"]), soft(C["guard"]))
        for sgn in (-1, 1):  # pendants
            px, py = (cx, cy + sgn * pr[1] * 1.08) if long_y else (cx + sgn * pr[0] * 1.08, cy)
            d.polygon(stepped_lozenge(px, py, unit * 0.7, unit * 0.7, 3), fill=soft(C["med2"]), outline=soft(C["dark"]))
    elif st["medallion"] == "floral":
        d.polygon(scalloped(cx, cy, mrx * 0.95, mry * 1.15 if long_y else mry, 14, 0.07), fill=soft(C["med"]))
        d.polygon(scalloped(cx, cy, mrx * 0.7, (mry * 1.15 if long_y else mry) * 0.74, 10, 0.08), fill=soft(C["guard"]))
        d.polygon(scalloped(cx, cy, mrx * 0.42, (mry * 1.15 if long_y else mry) * 0.45, 8, 0.1), fill=soft(C["med2"]))
        rosette(d, cx, cy, unit * 0.9, soft(C["med"]), soft(C["field"]))
    elif st["medallion"] == "stacked":
        n = 3
        span = (fy1 - fy0) if long_y else (fx1 - fx0)
        for k in range(n):
            t = (k + 0.5) / n
            px, py = (cx, fy0 + span * t) if long_y else (fx0 + span * t, cy)
            r = span / n * 0.42
            cols = [C["med"], C["med2"], C["accent"]]
            d.polygon(stepped_lozenge(px, py, r * (0.75 if long_y else 1), r * (1 if long_y else 0.75), 6), fill=soft(cols[k % 3]), outline=soft(C["dark"]))
            d.polygon(stepped_lozenge(px, py, r * 0.4, r * 0.4, 3), fill=soft(C["dark"]))
            rosette(d, px, py, r * 0.18, soft(C["guard"]), soft(C["field"]))

    # borders: outer guard, main border with repeating rosettes/lozenges, inner guards
    d.rectangle([0, 0, w - 1, h - 1], outline=C["guard"], width=g1)
    d.rectangle([g1, g1, w - 1 - g1, h - 1 - g1], outline=C["border"], width=bw)
    d.rectangle([g1 + bw, g1 + bw, w - 1 - g1 - bw, h - 1 - g1 - bw], outline=C["guard"], width=g2)
    k = 0
    stepb = bw * 1.25
    for edge in range(4):
        L = w if edge % 2 == 0 else h
        for t in np.arange(bw, L - bw, stepb):
            if edge == 0:
                x, y = t, g1 + bw / 2
            elif edge == 1:
                x, y = w - g1 - bw / 2, t
            elif edge == 2:
                x, y = t, h - g1 - bw / 2
            else:
                x, y = g1 + bw / 2, t
            if k % 2:
                rosette(d, x, y, bw * 0.3, soft(C["med"]) if style != "sultanabad" else C["guard"], C["border"])
            else:
                d.polygon(stepped_lozenge(x, y, bw * 0.3, bw * 0.3, 3), fill=mix(C["border"], C["med2"], con))
            k += 1
        for x, y in ((g1 + bw / 2, g1 + bw / 2), (w - g1 - bw / 2, g1 + bw / 2), (g1 + bw / 2, h - g1 - bw / 2), (w - g1 - bw / 2, h - g1 - bw / 2)):
            rosette(d, x, y, bw * 0.34, C["guard"], C["border"])

    # dense small-scale drawing over everything (flowers, hooks, crosses): what makes it read as a knotted rug
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    base = img.load()
    n = int(w * h / (unit * unit) * 14 * st.get("detail", 1.0))
    alpha = round(90 + 120 * con)
    for _ in range(n):
        x, y = rnd.uniform(0, w - 1), rnd.uniform(0, h - 1)
        r = unit * rnd.uniform(0.04, 0.11)
        under = base[int(x), int(y)]  # draw in a darker or lighter shade of what's underneath: keeps the design legible
        c = (*mix(under, C["dark"] if rnd.random() < 0.6 else C["guard"], rnd.uniform(0.35, 0.7)), alpha)
        kind = rnd.random()
        if kind < 0.35:
            ld.ellipse([x - r, y - r, x + r, y + r], fill=c)
        elif kind < 0.6:
            ld.polygon([(x, y - r * 1.4), (x + r, y), (x, y + r * 1.4), (x - r, y)], fill=c)
        elif kind < 0.8:
            lw = max(1, round(r * 0.35))
            ld.line([(x - r * 1.5, y), (x + r * 1.5, y)], fill=c, width=lw)
            ld.line([(x, y - r * 1.5), (x, y + r * 1.5)], fill=c, width=lw)
        else:
            a0 = rnd.uniform(0, 6.28)
            ld.line([(x, y), (x + math.cos(a0) * r * 3, y + math.sin(a0) * r * 3), (x + math.cos(a0 + 1.6) * r * 1.5 + math.cos(a0) * r * 3,
                     y + math.sin(a0 + 1.6) * r * 1.5 + math.sin(a0) * r * 3)], fill=c, width=max(1, round(r * 0.4)))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    a = np.asarray(img).astype(np.float32)
    # abrash: soft horizontal (along the weft) colour banding
    rows = np.cumsum(np.random.default_rng(seed).normal(0, 0.6, h))
    rows = (rows - rows.mean()) / (np.abs(rows).max() + 1e-6)
    a *= (1 + 0.05 * rows)[:, None, None]
    # wool grain and slight softness
    a += np.random.default_rng(seed + 1).normal(0, 6, a.shape)
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("style", choices=sorted(STYLES))
    ap.add_argument("W", type=float)
    ap.add_argument("H", type=float)
    ap.add_argument("out")
    ap.add_argument("--ppm", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    make(a.style, a.W, a.H, a.ppm, a.seed).save(a.out, quality=90)
    print("wrote", a.out)
