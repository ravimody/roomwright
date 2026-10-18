# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1", "pillow-heif"]
# ///
"""Calibrate colour and light against real photos whose cameras are known (room.json `cameras`, e.g. recovered with
tools/photo_match.py).

For each camera it renders the layout from that camera exactly as render_photoreal.py would (low resolution), plus
passes that label every pixel by part (wall, ceiling, floor, trim, baseboard, or a layout item and its material) and
give each part's albedo. It then compares each part's median colour with the photo's (masks eroded to skip edges;
pixels that disagree wildly, e.g. moved furniture, a TV picture or a person, are dropped), and:

1. fits the scene's exposure, white balance and tint (Blender's own colour management) to the parts whose colour is
   trusted (paint: walls, ceiling, doors and trim, baseboards by default), and
2. for every part, finds the albedo that would reproduce the photo under the model's lighting, as a suggested hex for
   room.json `materials` or the item's catalog colour.

A part's colour in a photo is albedo x light, so a suggestion is only as good as the model's lighting there: trust
suggestions that agree across several photos and daylight photos more than night ones. Emitters (lamp shades, sky
panels) are reported but get no suggestion; their difference says the lamp is brighter, dimmer, warmer or cooler.

Usage, from inside rooms/<room>/:
  uv run ../../tools/color_match.py <layout> <camera>[=<photo>] [...] [--lighting <scene>] [--samples 32] [--width 480]
      [--trust wall,ceiling,door,baseboard] [--out renders/color_match]

The photo comes from `camera=path` or the camera's "photo" key in room.json. HEIC photos are read with pillow-heif
(or macOS `sips`). Writes <out>/<camera>.json and <camera>.jpg (photo | render as set up |
render with the fitted exposure and white balance | per-part swatches) and, for several cameras, <out>/summary.json
with the median exposure and white balance and, per part, whether the photos agree (CONSISTENT) on a new colour.
"""

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

import render_photoreal as rp

import roomframe

# shell material name -> room.json materials key
SHELL_KEYS = {"wall": "wall", "ceiling": "ceiling", "floor": "floor", "door": "trim", "baseboard": "baseboard",
              "chair_rail": "baseboard", "crown": "baseboard"}

# ---------------------------------------------------------------- colour maths (sRGB / D65)


def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def srgb_to_lab(c):
    lin = srgb_to_lin(c)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def de2000(lab1, lab2):
    """CIEDE2000 colour difference (about 1 = just noticeable, 2-3 = noticeable side by side, 10+ = a different colour)."""
    L1, a1, b1 = np.moveaxis(np.asarray(lab1, float), -1, 0)
    L2, a2, b2 = np.moveaxis(np.asarray(lab2, float), -1, 0)
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25.0 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p, h2p = np.degrees(np.arctan2(b1, a1p)) % 360, np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lpm, Cpm = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hpm = np.where(C1p * C2p == 0, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    T = 1 - 0.17 * np.cos(np.radians(hpm - 30)) + 0.24 * np.cos(np.radians(2 * hpm)) + 0.32 * np.cos(np.radians(3 * hpm + 6)) - 0.20 * np.cos(np.radians(4 * hpm - 63))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cpm, 1 + 0.015 * Cpm * T
    Rt = -2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25.0 ** 7)) * np.sin(np.radians(60 * np.exp(-(((hpm - 275) / 25) ** 2))))
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def to_hex(srgb):
    return "#" + "".join(f"{int(v * 255 + 0.5):02X}" for v in np.clip(srgb, 0, 1))


# ---------------------------------------------------------------- Blender colour management as a function


class Display:
    """Scene-linear colours -> display sRGB through the scene's own view transform, look, exposure and white balance."""

    def __init__(self, tmp):
        self.sc = bpy.context.scene
        self.path = str(Path(tmp) / "_swatch.png")
        self.img = None

    def __call__(self, lin, exposure, temperature, tint):
        lin = np.asarray(lin, dtype=np.float32).reshape(-1, 3)
        n = len(lin)
        w = min(n, 1024)
        h = -(-n // w)
        if self.img is None or tuple(self.img.size) != (w, h):
            if self.img is not None:
                bpy.data.images.remove(self.img)
            self.img = bpy.data.images.new("_swatch", w, h, alpha=False, float_buffer=True)
        px = np.zeros((h * w, 4), np.float32)
        px[:n, :3], px[:, 3] = lin, 1
        self.img.pixels.foreach_set(px.ravel())
        vs = self.sc.view_settings
        vs.exposure, vs.white_balance_temperature, vs.white_balance_tint = exposure, temperature, tint
        self.img.save_render(self.path, scene=self.sc)
        out = np.asarray(Image.open(self.path).convert("RGB"), dtype=np.float64) / 255
        return out[::-1].reshape(-1, 3)[:n]  # Blender images are stored bottom row first


# ---------------------------------------------------------------- render passes


def setup_passes(tmp):
    """Index every mesh by owner (shell or layout item) and material, and write combined, index and albedo passes."""
    roots = {}  # top-level empties are layout items (blender_models.Builder)
    owners, mats = ["", "shell"], [""]
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        top = ob
        while top.parent:
            top = top.parent
        owner = top.name if top is not ob else "shell"
        if owner not in roots:
            roots[owner] = len(owners) if owner != "shell" else 1
            if owner != "shell":
                owners.append(owner)
        ob.pass_index = roots[owner]
    for m in bpy.data.materials:
        m.pass_index = len(mats)
        mats.append(m.name)
    vl = bpy.context.scene.view_layers[0]
    vl.use_pass_object_index = vl.use_pass_material_index = vl.use_pass_diffuse_color = True
    sc = bpy.context.scene
    sc.use_nodes = True
    tree = sc.node_tree
    for n in list(tree.nodes):
        tree.nodes.remove(n)
    rl = tree.nodes.new("CompositorNodeRLayers")
    comp = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(rl.outputs["Image"], comp.inputs["Image"])
    fo = tree.nodes.new("CompositorNodeOutputFile")
    fo.base_path = str(tmp)
    fo.format.file_format, fo.format.color_depth, fo.format.color_mode = "OPEN_EXR", "32", "RGB"
    fo.file_slots.clear()
    for slot, out in [("combined", "Image"), ("obj", "IndexOB"), ("mat", "IndexMA"), ("albedo", "DiffCol")]:
        fo.file_slots.new(slot)
        tree.links.new(rl.outputs[out], fo.inputs[slot])
    return owners, mats


def read_exr(path):
    im = bpy.data.images.load(str(path))
    w, h = im.size
    a = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(a)
    bpy.data.images.remove(im)
    return a.reshape(h, w, 4)[::-1, :, :3].astype(np.float64)


def render_passes(tmp, slug):
    d = Path(tmp) / slug
    shutil.rmtree(d, ignore_errors=True)
    bpy.context.scene.node_tree.nodes["File Output"].base_path = str(d)
    bpy.ops.render.render(write_still=False)
    get = {re.sub(r"\d*\.exr$", "", p.name): p for p in d.glob("*.exr")}
    return {k: read_exr(get[k]) for k in ("combined", "obj", "mat", "albedo")}


# ---------------------------------------------------------------- photos


def load_photo(path, tmp=None):
    """Upright RGB photo; HEIC via pillow-heif (any OS) or macOS sips (roomframe.load_photo)."""
    return roomframe.load_photo(path)


def label_name(owner, mat):
    m = re.sub(r"\.\d{3}$", "", mat)
    if owner == "shell":
        return "ceiling" if m.startswith("ceil_") else m
    return f"{owner}:{m}"


def material_kind(mat):
    """emitter / glass / metal / plain, from the material's Principled BSDF."""
    m = bpy.data.materials.get(mat)
    b = m.node_tree.nodes.get("Principled BSDF") if (m and m.use_nodes) else None
    if b is None:
        return "plain"
    if b.inputs["Emission Strength"].default_value > 0 and max(b.inputs["Emission Color"].default_value[:3]) > 0:
        return "emitter"
    if b.inputs["Transmission Weight"].default_value > 0.5:
        return "glass"
    if b.inputs["Metallic"].default_value > 0.5:
        return "metal"
    return "plain"


def erode(mask, r):
    if r <= 0:
        return mask
    im = Image.fromarray(np.uint8(mask) * 255).filter(ImageFilter.MinFilter(2 * r + 1))
    return np.asarray(im) > 0


def label_stats(labels, keep, photo_lin, comb, albedo):
    out = {}
    for key, m in labels.items():
        k = m & keep
        if k.sum() < 20:
            continue
        out[key] = {"n": int(k.sum()), "total": int(m.sum()), "photo": np.median(photo_lin[k], 0),
                    "render": np.median(comb[k], 0), "albedo": np.median(albedo[k], 0)}
    return out


def fit_global(disp, stats, trusted, start, fit_tint=False):
    """Exposure and white balance temperature (and tint, if asked) that best match the trusted parts (pixel-weighted
    mean dE2000). Tint stays at the scene's value by default: with one or two trusted parts it soaks up lighting errors."""
    keys = [k for k in stats if stats[k]["name"] in trusted]
    if not keys:
        return start, []
    ren = np.array([stats[k]["render"] for k in keys])
    ph = srgb_to_lab(lin_to_srgb(np.array([stats[k]["photo"] for k in keys])))
    wts = np.array([stats[k]["n"] for k in keys], float)

    def best_over(exps, temps, tints):
        best = (1e9, None)
        for t in temps:
            for ti in tints:
                # exposure is a plain gain in scene-linear light, so all exposures go through one transform call
                lab = srgb_to_lab(disp(np.concatenate([ren * 2.0 ** e for e in exps]), 0.0, t, ti)).reshape(len(exps), len(keys), 3)
                d = de2000(lab, ph[None])
                cost = (d * wts).sum(1) / wts.sum()
                i = int(np.argmin(cost))
                if cost[i] < best[0]:
                    best = (float(cost[i]), (float(exps[i]), float(t), float(ti)))
        return best

    tints = np.arange(-40, 61, 10) if fit_tint else [start[2]]
    _, (e, t, ti) = best_over(np.arange(start[0] - 4, start[0] + 4.01, 0.1), np.arange(2000, 12001, 250), tints)
    tints = np.arange(ti - 8, ti + 8.1, 2) if fit_tint else [start[2]]
    _, (e, t, ti) = best_over(np.arange(e - 0.12, e + 0.121, 0.02), np.arange(max(1500, t - 250), t + 251, 50), tints)
    return (e, t, ti), keys


def solve_albedo(disp, stats, settings, keys):
    """Per part, the per-channel albedo gain that makes the model's colour match the photo's under the model's lighting."""
    ren = np.array([stats[k]["render"] for k in keys])
    target = np.array([stats[k]["photo"] for k in keys])
    gain = np.ones_like(ren)
    e, t, ti = settings
    for _ in range(10):
        got = srgb_to_lin(disp(ren * gain * 2.0 ** e, 0.0, t, ti))
        gain *= np.clip((target + 1e-4) / (got + 1e-4), 0.5, 2.0) ** 0.8
        gain = np.clip(gain, 0.05, 20)
    return gain


# ---------------------------------------------------------------- sheet


def sheet(path, photo, before, after, rows):
    w = photo.width
    h = photo.height
    pad, head, rh = 10, 34, 34
    im = Image.new("RGB", (3 * w + 4 * pad, head + h + pad + rh * len(rows) + 2 * pad), "white")
    d = ImageDraw.Draw(im)
    for i, (t, p) in enumerate([("PHOTO", photo), ("MODEL, scene as set up", before), ("MODEL, fitted exposure + white balance", after)]):
        x = pad + i * (w + pad)
        d.text((x, 10), t, fill="black")
        im.paste(p, (x, head))
    y = head + h + 2 * pad
    d.text((pad, y - 14), "part | photo | model (fitted) | suggested albedo        dE2000 before -> after fit", fill="black")
    for r in rows:
        d.text((pad, y + 10), r["label"][:42], fill="black")
        x = pad + 300
        for c in (r["photo_hex"], r["model_hex"], r.get("suggested_hex")):
            if c:
                d.rectangle([x, y + 2, x + 70, y + rh - 4], fill=c, outline="#888")
            x += 80
        note = f"{r['dE_before']:.1f} -> {r['dE_after']:.1f}   {r['pixels']} px"
        if r.get("suggested_hex"):
            note += f"   now {r['current_hex']} -> {r['suggested_hex']}"
        if r["kind"] != "plain":
            note += f"   ({r['kind']})"
        if r["trusted"]:
            note += "   [fit]"
        d.text((x + 10, y + 10), note, fill="black")
        y += rh
    im.save(path, quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("cameras", nargs="+", help="room.json camera names, each optionally =<photo path>")
    ap.add_argument("--lighting", default="standard")
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--width", type=int, default=480, help="long side of the comparison, px")
    ap.add_argument("--trust", default="wall,ceiling,door,baseboard", help="parts whose colour is known (paint) and drive the global fit")
    ap.add_argument("--fit-tint", action="store_true", help="also fit the white balance tint (needs several trusted parts)")
    ap.add_argument("--erode", type=int, default=0, help="px to erode each part's mask (default: 1%% of the long side)")
    ap.add_argument("--min-frac", type=float, default=0.004, help="smallest part reported, as a fraction of the frame")
    ap.add_argument("--max-spread", type=float, default=6.0, help="largest dE2000 between photos for a suggestion to count as consistent")
    ap.add_argument("--out", default="renders/color_match")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])

    room = roomframe.normalize_room(json.loads((rp.ROOM / "room.json").read_text()))
    out = rp.ROOM / a.out
    out.mkdir(parents=True, exist_ok=True)
    trusted = set(a.trust.split(","))
    tmp = Path(tempfile.mkdtemp(prefix="color_match_"))
    cam = rp.build(a.layout, a.samples, (a.width, a.width * 3 // 4), a.lighting)
    sc = bpy.context.scene
    owners, mats = setup_passes(tmp)
    disp = Display(tmp)
    erode_px = a.erode or max(2, round(a.width / 100))
    results = {}

    for spec in a.cameras:
        name, _, photo_path = spec.partition("=")
        photo_path = photo_path or room["cameras"][name].get("photo")
        if not photo_path:
            sys.exit(f"{name}: no photo (give {name}=<path> or a \"photo\" key on the camera)")
        photo = load_photo(rp.ROOM / photo_path, tmp)
        W = a.width if photo.width >= photo.height else round(a.width * photo.width / photo.height)
        H = round(W * photo.height / photo.width)
        sc.render.resolution_x, sc.render.resolution_y = W, H
        rp.aim(cam, name)
        e0, wb0, _ = rp.expose(cam, name)  # the scene's exposure and white balance for this view (auto, photo or fixed)
        start = (e0, wb0, sc.view_settings.white_balance_tint)
        P = render_passes(tmp, name)
        photo_s = photo.resize((W, H), Image.LANCZOS)
        photo_lin = srgb_to_lin(np.asarray(photo_s, np.float64) / 255)
        comb, albedo = P["combined"], P["albedo"]
        oi, mi = np.rint(P["obj"][..., 0]).astype(int), np.rint(P["mat"][..., 0]).astype(int)

        labels, meta = {}, {}
        min_px = a.min_frac * W * H
        for o, m in set(zip(oi[oi > 0].ravel(), mi[oi > 0].ravel())):
            key = (o, m)
            mask = (oi == o) & (mi == m)
            if mask.sum() < min_px:
                continue
            em = erode(mask, erode_px)
            if em.sum() < min_px / 4:
                continue
            labels[key] = em
            nm = label_name(owners[o], mats[m])
            meta[key] = {"name": nm, "kind": material_kind(mats[m])}
        # merge parts that share a name (e.g. every wall segment, or two ceiling levels)
        merged, mmeta = {}, {}
        for key, mask in labels.items():
            nm = meta[key]["name"]
            merged[nm] = merged.get(nm, False) | mask
            mmeta[nm] = meta[key]
        labels = merged
        photo_lab = srgb_to_lab(np.asarray(photo_s, np.float64) / 255)
        anylab = np.zeros((H, W), bool)
        for mask in labels.values():
            anylab |= mask

        # pass 1: all pixels; pass 2: drop pixels that disagree wildly with the fitted model, then refit
        keep = np.ones((H, W), bool)
        for _ in range(2):
            stats = label_stats(labels, keep, photo_lin, comb, albedo)
            for k in stats:
                stats[k].update(mmeta[k])
            settings, fit_keys = fit_global(disp, stats, trusted, start, a.fit_tint)
            e, t, ti = settings
            fitted = disp(comb.reshape(-1, 3) * 2.0 ** e, 0.0, t, ti).reshape(H, W, 3)
            dpx = de2000(srgb_to_lab(fitted), photo_lab)
            v = dpx[anylab & keep]
            med, mad = np.median(v), np.median(np.abs(v - np.median(v)))
            thr = max(med + 3 * 1.4826 * mad, 12.0)
            keep = keep & ~(anylab & (dpx > thr))
        stats = label_stats(labels, keep, photo_lin, comb, albedo)
        for k in stats:
            stats[k].update(mmeta[k])
        before = disp(comb.reshape(-1, 3), *start).reshape(H, W, 3)
        keys = sorted(stats, key=lambda k: -stats[k]["n"])
        ren = np.array([stats[k]["render"] for k in keys])
        ph_srgb = lin_to_srgb(np.array([stats[k]["photo"] for k in keys]))
        d_before = de2000(srgb_to_lab(disp(ren, *start)), srgb_to_lab(ph_srgb))
        model_after = disp(ren * 2.0 ** e, 0.0, t, ti)
        d_after = de2000(srgb_to_lab(model_after), srgb_to_lab(ph_srgb))
        gains = solve_albedo(disp, stats, settings, keys)
        rows = []
        for i, k in enumerate(keys):
            s = stats[k]
            r = {"label": k, "kind": s["kind"], "trusted": k in trusted, "pixels": s["n"], "coverage": round(s["n"] / s["total"], 2),
                 "photo_hex": to_hex(ph_srgb[i]), "model_hex": to_hex(model_after[i]),
                 "dE_before": round(float(d_before[i]), 1), "dE_after": round(float(d_after[i]), 1)}
            alb = s["albedo"]
            if s["kind"] == "plain" and alb.max() > 0.003:
                sug = np.clip(alb * gains[i], 0.003, 0.95)
                r.update({"current_hex": to_hex(lin_to_srgb(alb)), "suggested_hex": to_hex(lin_to_srgb(sug)),
                          "albedo_gain": [round(float(g), 3) for g in gains[i]]})
                if k in SHELL_KEYS:
                    r["room_json"] = f"materials.{SHELL_KEYS[k]}.hex"
            rows.append(r)
        cover = float(keep[anylab].mean()) if anylab.any() else 0.0
        res = {"camera": name, "photo": str(photo_path), "layout": a.layout, "lighting": a.lighting,
               "set_up": {"exposure": round(start[0], 3), "whiteBalance": round(start[1]), "tint": round(start[2], 1)},
               "fitted": {"exposure": round(e, 3), "whiteBalance": round(t), "tint": round(ti, 1)},
               "fit_parts": fit_keys, "kept_pixels": round(cover, 3), "parts": rows}
        (out / f"{name}.json").write_text(json.dumps(res, indent=2) + "\n")
        big = 640
        size = (big, round(big * H / W)) if W >= H else (round(big * W / H), big)

        def show(arr, size=size):
            return Image.fromarray(np.uint8(np.clip(arr, 0, 1) * 255)).resize(size, Image.LANCZOS)

        sheet(out / f"{name}.jpg", photo.resize(size, Image.LANCZOS), show(before), show(fitted), rows[:14])
        results[name] = res
        print(f"\n{name}: kept {cover:.0%} of labelled pixels; exposure {start[0]:.2f} -> {e:.2f}, white balance {start[1]:.0f} -> {t:.0f} K, tint {start[2]:.0f} -> {ti:.0f}")
        print(f"  {'part':34} {'px':>6} {'dE as set up':>12} {'dE fitted':>9}  {'photo':8} {'albedo now':10} {'suggested':10}")
        for r in rows:
            flag = "*" if r["trusted"] else (f"({r['kind']})" if r["kind"] != "plain" else "")
            print(f"  {r['label'][:34]:34} {r['pixels']:6d} {r['dE_before']:12.1f} {r['dE_after']:9.1f}  {r['photo_hex']:8} {r.get('current_hex', ''):10} {r.get('suggested_hex', ''):10} {flag}")

    if len(results) > 1:
        # across photos: a suggestion that holds in every photo is evidence; one that swings is the lighting
        fits = [r["fitted"] for r in results.values()]
        scene = {"exposure": round(float(np.median([f["exposure"] for f in fits])), 2),
                 "whiteBalance": int(round(float(np.median([f["whiteBalance"] for f in fits])), -1)),
                 "exposureRange": [min(f["exposure"] for f in fits), max(f["exposure"] for f in fits)],
                 "whiteBalanceRange": [min(f["whiteBalance"] for f in fits), max(f["whiteBalance"] for f in fits)]}
        summ = {"cameras": list(results), "fitted": {n: r["fitted"] for n, r in results.items()}, "scene": scene, "parts": {}}
        print(f"\nScene '{a.lighting}': exposure {start[0]:.2f} -> {scene['exposure']:.2f} (photos {scene['exposureRange'][0]:.2f} to {scene['exposureRange'][1]:.2f}), "
              f"white balance {start[1]:.0f} -> {scene['whiteBalance']} K (photos {scene['whiteBalanceRange'][0]} to {scene['whiteBalanceRange'][1]})."
              " Phones set exposure and white balance per shot, so use the median only if the photos agree.")
        names = sorted({p["label"] for r in results.values() for p in r["parts"] if p.get("suggested_hex")})
        print("\nAcross photos (suggested albedo; spread = largest dE2000 between two photos' suggestions):")
        for nm in names:
            sugg = [(n, p["suggested_hex"]) for n, r in results.items() for p in r["parts"] if p["label"] == nm and p.get("suggested_hex")]
            labs = srgb_to_lab(np.array([[int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)] for _, h in sugg]))
            spread = max((float(de2000(labs[i], labs[j])) for i in range(len(labs)) for j in range(i + 1, len(labs))), default=0.0)
            med = to_hex(lin_to_srgb(np.median(srgb_to_lin(np.array([[int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)] for _, h in sugg])), 0)))
            cur = next(p["current_hex"] for r in results.values() for p in r["parts"] if p["label"] == nm and p.get("current_hex"))
            consistent = len(sugg) >= 2 and spread <= a.max_spread
            summ["parts"][nm] = {"photos": len(sugg), "current_hex": cur, "median_suggested_hex": med, "spread_dE": round(spread, 1),
                                 "consistent": consistent, "per_photo": dict(sugg)}
            print(f"  {nm[:34]:34} photos {len(sugg)}  now {cur}  suggested {med}  spread {spread:5.1f}  {'CONSISTENT' if consistent else ''}")
        print(f"CONSISTENT = seen in 2+ photos with suggestions within dE {a.max_spread:g} of each other; the rest is lighting, not paint.")
        (out / "summary.json").write_text(json.dumps(summ, indent=2) + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
