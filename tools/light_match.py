# /// script
# requires-python = "==3.11.*"
# dependencies = ["bpy==4.5.*", "numpy<2", "pillow>=10.1", "pillow-heif", "scipy"]
# ///
"""Calibrate the lights against real photos whose cameras are known (room.json `cameras` with a `photo`, e.g. from
tools/photo_match.py): how bright and how warm each light really is.

It renders each camera as render_photoreal.py would, with every light in its own Cycles light group (daylight, the
cans, each lamp type, the fire, accents, an item's interior light, each lit screen), so the image is a sum of one
image per group. Light transport is linear and per channel, so any lumens and colour temperature per group can be
tried without rendering again. It then fits, on the parts whose colour is known (paint: walls, ceiling, doors and
trim, baseboards; --trust), each split into image tiles (--tiles) because how the light falls across a wall is what
tells two lights apart:

- one intensity scale per group (actual / modelled light),
- the colour temperature of each group, relative to the brightest one (with a single light, its colour and the
  camera's white balance can't be told apart, so it stays as in the data), and the colour of lit screens,
- the photo's white balance,

with the camera's exposure taken from the photo's EXIF (shutter, aperture, ISO -> EV100). Phones process photos
(tone curves, Night mode and HDR merges, a bright TV in the frame), so absolute levels are weak evidence: results
are reported relative to an anchor group whose lumens come from data (--anchor), and the anchor's own scale is the
"camera offset" (the phone, or every light dimmer than modelled: photos alone can't tell which). A value is
CONSISTENT when two thirds of the photos agree within --max-spread stops (or --max-kelvin-spread). --write puts
consistent results into the room's data: lumens and kelvin (catalog `light`, or the layout's items with
--to layout; room.json `lights.cans`; a fixture's `fire` or `screen`), `daylight.scale`, the scene's dimmer
settings for dimmed lamps, its white balance, and the camera offset as its `exposureBias` (for `exposure: photo`).
--absolute writes every group's own scale instead.

Usage, from inside rooms/<room>/:
  uv run ../../tools/light_match.py <layout> <camera>[=<photo>] [...] --lighting <scene> [--samples 32]
      [--width 400] [--tiles 4] [--trust wall,ceiling,door,baseboard] [--min-share 0.03] [--max-spread 0.6]
      [--anchor GROUP] [--absolute] [--resummarise] [--write [--to catalog|layout]]

Writes renders/light_match/<camera>.json and .jpg (photo | model as set up | model fitted) and summary.json.
"""

import argparse
import json
import math
import re
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sandbox_guard  # noqa: F401  (stops with advice where bpy would crash: Codex's macOS sandbox)

import bpy

import color_match as cm
import render_photoreal as rp

import blender_models
import photometry as ph
import roomframe


def setup_passes(tmp, groups):
    """color_match's passes (combined, object/material index, albedo) plus one image per light group."""
    vl = bpy.context.scene.view_layers[0]
    for g in groups:
        if g not in vl.lightgroups:
            vl.lightgroups.add(name=g)
    owners, mats = cm.setup_passes(tmp)
    tree = bpy.context.scene.node_tree
    rl, fo = tree.nodes["Render Layers"], tree.nodes["File Output"]
    for g in groups:
        fo.file_slots.new(f"lg_{g}")
        tree.links.new(rl.outputs[f"Combined_{g}"], fo.inputs[f"lg_{g}"])
    return owners, mats


def render_passes(tmp, slug, groups):
    d = Path(tmp) / slug
    shutil.rmtree(d, ignore_errors=True)
    bpy.context.scene.node_tree.nodes["File Output"].base_path = str(d)
    bpy.ops.render.render(write_still=False)
    get = {re.sub(r"\d*\.exr$", "", p.name): p for p in d.glob("*.exr")}
    out = {k: cm.read_exr(get[k]) for k in ("combined", "obj", "mat", "albedo")}
    out["groups"] = {g: cm.read_exr(get[f"lg_{g}"]) for g in groups}
    return out


def colour_gain(info, params):
    """Per-channel gain of a group's light for a fitted colour, relative to how it was rendered."""
    if info["kind"] == "screen":
        r, b = params
        g = np.array([2.0 ** r, 1.0, 2.0 ** b])
        return g / ph.luminance(g)
    k0 = info.get("kelvin")
    if not k0 or not params:  # a group of mixed colours (accent lights): colour as rendered
        return np.ones(3)
    return np.array(ph.kelvin_rgb(params)) / np.array(ph.kelvin_rgb(k0))


def mean_k(contrib, kelvins):
    """Colour temperature of a mix of lights (luminance-weighted in xy)."""
    rgb = sum(np.array(ph.kelvin_rgb(k)) * c for k, c in zip(kelvins, contrib) if c > 0)
    return ph.rgb_kelvin(rgb) if np.any(rgb) else ph.D65_K


def fit_camera(disp, parts, groups, info, e, start_wb, tint, min_share, fit_kelvin=True):
    """Fit group scales, colour temperatures (relative to the dominant group), screen colours and white balance to
    the trusted parts. parts: {name: {"photo": lin rgb, "groups": {g: lin rgb}, "n": px}}."""
    from scipy.optimize import minimize

    names = list(parts)
    ph_lab = cm.srgb_to_lab(cm.lin_to_srgb(np.array([parts[p]["photo"] for p in names])))
    wts = np.array([parts[p]["n"] for p in names], float)
    M = {g: np.array([parts[p]["groups"][g] for p in names]) for g in groups}
    lum = {g: float((ph.luminance(M[g].T) * wts).sum()) for g in groups}
    total = sum(lum.values()) or 1.0
    active = [g for g in groups if lum[g] / total >= min_share]
    if not active:
        return None
    dom = max(active, key=lambda g: lum[g])
    bb = [g for g in active if info[g]["kind"] != "screen" and info[g].get("kelvin")]
    kel = [g for g in bb if g != dom] if (fit_kelvin and len(bb) >= 2) else []
    scr = [g for g in active if info[g]["kind"] == "screen"]

    def unpack(x):
        i = 0
        s = dict.fromkeys(groups, 1.0)
        for g in active:
            s[g] = 2.0 ** float(np.clip(x[i], -7, 7))
            i += 1
        col = {g: (info[g]["kelvin"] if info[g]["kind"] != "screen" else (0.0, 0.0)) for g in groups}
        for g in kel:
            col[g] = float(np.clip(1e6 / max(x[i], 80), 1500, 12000))
            i += 1
        for g in scr:
            col[g] = (float(np.clip(x[i], -4, 4)), float(np.clip(x[i + 1], -4, 4)))
            i += 2
        wb = float(np.clip(1e6 / max(x[i], 80), 1500, 15000))
        return s, col, wb

    def model(s, col):
        return sum(M[g] * s[g] * colour_gain(info[g], col[g]) for g in groups)

    def cost(x):
        s, col, wb = unpack(x)
        lab = cm.srgb_to_lab(disp(model(s, col) * 2.0 ** e, 0.0, wb, tint))
        return float((cm.de2000(lab, ph_lab) * wts).sum() / wts.sum())

    # start: one common scale (the exposure anchor may be far off), then everything
    x0 = [0.0] * len(active) + [1e6 / info[g]["kelvin"] for g in kel] + [0.0, 0.0] * len(scr) + [1e6 / start_wb]
    best = (1e9, 0.0)
    for c in np.arange(-6, 6.01, 0.25):
        x = list(x0)
        x[: len(active)] = [c] * len(active)
        v = cost(x)
        if v < best[0]:
            best = (v, c)
    x0[: len(active)] = [best[1]] * len(active)
    for wbm in (1e6 / 2500, 1e6 / 3500, 1e6 / 5000, 1e6 / 6500):
        x = list(x0)
        x[-1] = wbm
        if cost(x) < cost(x0):
            x0 = x
    steps = [0.5] * len(active) + [40.0] * len(kel) + [0.5, 0.5] * len(scr) + [40.0]  # stops, mired, log2 gains, mired
    res = None
    for _ in range(2):  # restart once from the result: Nelder-Mead stalls on a collapsed simplex
        simplex = np.array([x0] + [np.array(x0) + np.eye(len(x0))[i] * steps[i] for i in range(len(x0))])
        res = minimize(cost, x0, method="Nelder-Mead", options={"maxiter": 3000, "xatol": 1e-3, "fatol": 1e-3, "adaptive": True,
                                                                "initial_simplex": simplex})
        x0 = list(res.x)
    s, col, wb = unpack(res.x)
    before = cost([0.0] * len(active) + [1e6 / info[g]["kelvin"] for g in kel] + [0.0, 0.0] * len(scr) + [1e6 / start_wb])
    return {"scale": s, "colour": col, "whiteBalance": wb, "dE_set_up": before, "dE_fitted": float(res.fun),
            "active": active, "dominant": dom, "kelvin_fitted": kel, "share": {g: lum[g] / total for g in groups},
            "model": model(s, col), "names": names}


def inverse_dimmer(output, curve):
    output = min(max(output, 0.0), 1.0)
    if curve == "linear":
        return output
    if curve == "log":
        return 0.0 if output <= 1e-3 else 1 + math.log10(output) / 3
    return math.sqrt(output)


def write_back(room_dir, scene_name, info, summ, wb, absolute=False, bias=None, layout=None):
    """Put consistent results into room.json / catalog.json; returns the list of changes. Relative (default): the
    anchor group stays, the others change by their scale relative to it, and the camera offset becomes the scene's
    exposureBias (for a scene exposed from the photos' EXIF). absolute: every group by its own scale. A colour
    temperature is written when the photos agree on it, even if the brightness isn't. layout ({"slug", "data"}):
    write lamps to that layout's items instead of their catalog type (when the type is shared with other lamps)."""
    room_p, cat_p = room_dir / "room.json", room_dir / "catalog.json"
    room_txt = room_p.read_text()
    room = json.loads(room_txt)
    cat_txt = cat_p.read_text() if cat_p.exists() else ""
    cat = json.loads(cat_txt) if cat_txt else {"items": {}}
    shared = blender_models.load_catalog(room_dir)
    scene = room.setdefault("scenes", {}).setdefault(scene_name, {"base": "evening"})
    changes = []

    def catalog_entry(t):
        return cat["items"].setdefault(t, json.loads(json.dumps(shared[t])))

    for g, r in summ.items():
        i = info[g]
        k = int(round(r["kelvin"], -1)) if r.get("kelvin_consistent") else None
        scale_ok = r["consistent"] and (absolute or (not r["anchor"] and r["relative_log2"] is not None))
        if i["kind"] in ("item", "cans", "fire", "interior") and not i.get("lumens"):
            scale_ok = False  # a glow without a lamp: nothing to write
        if not scale_ok and not k:
            continue
        s = 2.0 ** (r["log2_scale"] if absolute else r["relative_log2"]) if scale_ok else 1.0
        new_lm = int(round(i["lumens"] * s, -1)) if (scale_ok and i.get("lumens")) else None
        done = []
        if scale_ok and i["kind"] == "item" and i.get("dim", 1.0) < 1.0:  # a dimmed lamp: the dimmer setting is the unknown
            curve = i.get("dimCurve", "square")
            new = round(inverse_dimmer(ph.dimmer_output(i["dim"], curve) * s, curve), 2)
            for iid in i["ids"]:
                scene.setdefault("lampDim", {})[iid] = new
            done.append(f"lampDim {', '.join(i['ids'])} {i['dim']} -> {new}")
            new_lm = None
        if i["kind"] == "item":
            targets = [catalog_entry(i["type"])]
            if layout is not None:  # the layout's items carry it (a layout item's `light` replaces the catalog's)
                items = {it["id"]: it for it in layout["data"]["items"]}
                targets = []
                for iid in i["ids"]:
                    items[iid]["light"] = {**shared[i["type"]].get("light", {}), **items[iid].get("light", {})}
                    targets.append(items[iid])
            for entry in targets:
                if new_lm:
                    entry.setdefault("light", {})["lumens"] = new_lm
                if k:
                    entry.setdefault("light", {})["kelvin"] = k
                entry["light"]["note"] = f"fitted with light_match.py from {r['photos']} photos ({scene_name})" + ("" if absolute else f", relative to {next(n for n, x in summ.items() if x['anchor'])}")
        elif i["kind"] == "cans":
            lights = room.setdefault("lights", {})
            cans = lights.setdefault("downlights" if "downlights" in lights else "cans", {})
            if new_lm:
                cans["lumens"] = new_lm
            if k:
                cans["kelvin"] = k
        elif i["kind"] == "daylight" and scale_ok:
            d = room.setdefault("daylight", {})
            d["scale"] = round(d.get("scale", 1.0) * s, 2)
            done.append(f"daylight.scale -> {d['scale']}")
        elif i["kind"] == "fire":
            fire = next(f for f in room["fixtures"] if f["id"] == i["fixture"]).setdefault("fire", {})
            if new_lm:
                fire["lumens"] = new_lm
            if k:
                fire["kelvin"] = k
        elif i["kind"] == "screen" and scale_ok:
            sc = next(f for f in room["fixtures"] if f["id"] == i["fixture"]).setdefault("screen", {})
            sc["luminance"] = round(i["luminance"] * s)
            if r.get("hex"):
                sc["hex"] = r["hex"]
            done.append(f"screen {sc['luminance']} cd/m2 {sc.get('hex', '')}")
        elif i["kind"] == "interior":
            li = catalog_entry(i["type"]).setdefault("interiorLight", {})
            if new_lm:
                li["lumens"] = new_lm
            if k:
                li["kelvin"] = k
        if new_lm:
            done.append(f"x{s:.2f} -> {new_lm:.0f} lm")
        if k and i["kind"] in ("item", "cans", "fire", "interior"):
            done.append(f"{k} K")
        if done:
            changes.append(f"{g}: " + ", ".join(done))
    if wb:
        scene["whiteBalance"] = wb
        changes.append(f"scene {scene_name}: whiteBalance {wb}")
    if bias is not None:
        scene["exposureBias"] = bias
        changes.append(f"scene {scene_name}: exposureBias {bias} (camera offset)")
    room_p.write_text(json.dumps(room, indent=2, ensure_ascii="\\u" in room_txt) + "\n")
    if layout is not None:
        lp = room_dir / f"layouts/{layout['slug']}.json"
        lp.write_text(json.dumps(layout["data"], indent=2, ensure_ascii="\\u" in lp.read_text()) + "\n")
    if cat_txt or cat["items"]:
        cat_p.write_text(json.dumps(cat, indent=2, ensure_ascii="\\u" in cat_txt) + "\n")
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("cameras", nargs="+", help="room.json camera names, each optionally =<photo path>")
    ap.add_argument("--lighting", required=True, help="the scene the photos were taken in (lights on and dimmed as in them)")
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--width", type=int, default=400, help="long side of the comparison, px")
    ap.add_argument("--trust", default="wall,ceiling,door,baseboard", help="parts whose colour is known (paint)")
    ap.add_argument("--min-share", type=float, default=0.03, help="smallest share of the light on trusted parts for a group to be fitted")
    ap.add_argument("--max-spread", type=float, default=0.6, help="largest spread between photos, in stops, for CONSISTENT")
    ap.add_argument("--max-kelvin-spread", type=float, default=600, help="largest spread between photos, in K, for a colour temperature")
    ap.add_argument("--no-kelvin", action="store_true", help="fit intensities and white balance only")
    ap.add_argument("--tiles", type=int, default=4, help="split each trusted part into an N x N grid of image tiles (the light's fall-off)")
    ap.add_argument("--anchor", help="light group whose lumens are trusted (default: one with lumens from data, else the most seen)")
    ap.add_argument("--absolute", action="store_true", help="trust the photos' EXIF exposure: write absolute lumens, no exposure bias")
    ap.add_argument("--to", choices=("catalog", "layout"), default="catalog",
                    help="where --write puts a lamp's light: its catalog type (default) or the layout's items (a type shared with other lamps)")
    ap.add_argument("--resummarise", action="store_true", help="skip the renders: summarise (and --write) the last run's per-camera fits")
    ap.add_argument("--write", action="store_true", help="write CONSISTENT results into room.json / catalog.json")
    ap.add_argument("--out", default="renders/light_match")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])

    room = roomframe.normalize_room(json.loads((rp.ROOM / "room.json").read_text()))
    out = rp.ROOM / a.out
    out.mkdir(parents=True, exist_ok=True)
    trusted = set(a.trust.split(","))
    tmp = Path(tempfile.mkdtemp(prefix="light_match_"))
    cam = rp.build(a.layout, a.samples, (a.width, a.width * 3 // 4), a.lighting)
    info = blender_models.LIGHT_GROUPS
    groups = sorted(info)
    if not groups:
        sys.exit(f"scene {a.lighting!r} has no lights on")
    sc = bpy.context.scene
    tint = sc.view_settings.white_balance_tint
    owners, mats = setup_passes(tmp, groups)
    disp = cm.Display(tmp)
    results = {}
    print("light groups: " + ", ".join(f"{g} ({info[g]['what']})" for g in groups))

    for spec in a.cameras:
        name, _, photo_path = spec.partition("=")
        if a.resummarise:  # reuse this camera's fit from the last run
            results[name] = json.loads((out / f"{name}.json").read_text())
            continue
        photo_path = photo_path or room["cameras"][name].get("photo")
        if not photo_path:
            sys.exit(f"{name}: no photo (give {name}=<path> or a \"photo\" key on the camera)")
        photo = cm.load_photo(rp.ROOM / photo_path)
        W = a.width if photo.width >= photo.height else round(a.width * photo.width / photo.height)
        H = round(W * photo.height / photo.width)
        sc.render.resolution_x, sc.render.resolution_y = W, H
        rp.aim(cam, name)
        e_set, wb_set, how = rp.expose(cam, name, quiet=True)
        ev = roomframe.photo_ev100(rp.ROOM / photo_path)
        e = ph.exposure_for_ev(ev) if ev is not None else e_set
        P = render_passes(tmp, name, groups)
        photo_s = photo.resize((W, H), Image.LANCZOS)
        p_srgb = np.asarray(photo_s, np.float64) / 255
        photo_lin = cm.srgb_to_lin(p_srgb)
        oi, mi = np.rint(P["obj"][..., 0]).astype(int), np.rint(P["mat"][..., 0]).astype(int)
        erode_px = max(2, round(W / 100))
        # usable pixels: not clipped or black in the photo
        ok = (p_srgb.max(-1) < 0.97) & (p_srgb.max(-1) > 0.02)
        parts = {}
        for o, m in set(zip(oi[oi > 0].ravel(), mi[oi > 0].ravel())):
            nm = cm.label_name(owners[o], mats[m])
            if nm not in trusted:
                continue
            mask = cm.erode((oi == o) & (mi == m), erode_px) & ok
            if mask.sum() < 0.004 * W * H:
                continue
            p = parts.setdefault(nm, {"mask": np.zeros((H, W), bool)})
            p["mask"] |= mask
        # drop pixels that disagree wildly with the model's shading pattern (people, moved things, a TV picture):
        # per part, the photo/model luminance ratio's outliers
        comb_l = ph.luminance(np.moveaxis(P["combined"], -1, 0))
        phot_l = ph.luminance(np.moveaxis(photo_lin, -1, 0))
        # then split each part into image tiles: how the light falls across a wall (bright near a lamp, dim far from
        # it) is what tells the lights apart, and a part's average alone hides it
        cells = {}
        for nm, p in parts.items():
            r = np.log((phot_l[p["mask"]] + 1e-4) / (comb_l[p["mask"]] + 1e-4))
            med, mad = np.median(r), np.median(np.abs(r - np.median(r))) * 1.4826
            keep = np.abs(r - med) <= max(3 * mad, 0.4)
            idx = np.argwhere(p["mask"])[keep]
            tile = (idx[:, 0] * a.tiles // H) * a.tiles + idx[:, 1] * a.tiles // W
            for t in np.unique(tile):
                sub = idx[tile == t]
                if len(sub) < 20:
                    continue
                sel = (sub[:, 0], sub[:, 1])
                cells[f"{nm}#{t}"] = {"n": len(sub), "photo": photo_lin[sel].mean(0), "groups": {g: P["groups"][g][sel].mean(0) for g in groups}}
        parts = cells
        if not parts:
            print(f"{name}: no trusted parts in view; skipped")
            continue
        fit = fit_camera(disp, parts, groups, info, e, wb_set, tint, a.min_share, not a.no_kelvin)
        if fit is None:
            print(f"{name}: no light group reaches the trusted parts; skipped")
            continue
        s, col = fit["scale"], fit["colour"]
        contrib = [fit["share"][g] * s[g] for g in groups]
        k_mix = mean_k(contrib, [col[g] if info[g]["kind"] != "screen" else ph.D65_K for g in groups])
        alpha = (ph.mired(fit["whiteBalance"]) - ph.mired(ph.D65_K)) / (ph.mired(k_mix) - ph.mired(ph.D65_K)) if abs(k_mix - ph.D65_K) > 300 else None
        res = {"camera": name, "photo": str(photo_path), "layout": a.layout, "lighting": a.lighting,
               "exposure": {"set_up": round(e_set, 2), "set_up_from": how, "photo_ev100": None if ev is None else round(ev, 2), "used": round(e, 2)},
               "whiteBalance": {"set_up": round(wb_set), "fitted": round(fit["whiteBalance"]), "light_mix_kelvin": round(k_mix), "adaptation": None if alpha is None else round(alpha, 2)},
               "dE": {"set_up": round(fit["dE_set_up"], 1), "fitted": round(fit["dE_fitted"], 1)},
               "parts": {k: v["n"] for k, v in parts.items()}, "groups": {}}
        for g in groups:
            r = {"share": round(fit["share"][g], 3), "fitted": g in fit["active"]}
            if g in fit["active"]:
                r["log2_scale"] = round(math.log2(s[g]), 2)
            if g in fit["kelvin_fitted"]:
                r["kelvin"] = round(col[g])
            if info[g]["kind"] == "screen" and g in fit["active"]:
                gain = colour_gain(info[g], col[g])
                r["hex"] = cm.to_hex(cm.lin_to_srgb(np.array(info[g]["rgb"]) * gain / max(np.array(info[g]["rgb"]) * gain)))
            res["groups"][g] = r
        (out / f"{name}.json").write_text(json.dumps(res, indent=2) + "\n")
        # sheet: photo | as set up | fitted
        comb = P["combined"]
        # the light-group passes aren't denoised: show the denoised render times the (smoothed) change the fit makes
        raw = sum(P["groups"][g] for g in groups)
        refit = sum(P["groups"][g] * s[g] * colour_gain(info[g], col[g]) for g in groups)

        def smooth(x):
            from scipy.ndimage import gaussian_filter

            return gaussian_filter(x, sigma=(4, 4, 0))

        fitted_img = comb * smooth(refit) / np.maximum(smooth(raw), 1e-6)
        size = (480, round(480 * H / W))
        before = disp(comb.reshape(-1, 3) * 2.0 ** e_set, 0.0, wb_set, tint).reshape(H, W, 3)
        after = disp(fitted_img.reshape(-1, 3) * 2.0 ** e, 0.0, fit["whiteBalance"], tint).reshape(H, W, 3)
        im = Image.new("RGB", (3 * size[0] + 40, size[1] + 44), "white")
        d = ImageDraw.Draw(im)
        for i, (t, pic) in enumerate([("PHOTO", photo_s), (f"MODEL as set up (exposure {e_set:.1f}, WB {wb_set:.0f})", Image.fromarray(np.uint8(np.clip(before, 0, 1) * 255))),
                                      (f"MODEL fitted (EXIF exposure {e:.1f}, WB {fit['whiteBalance']:.0f})", Image.fromarray(np.uint8(np.clip(after, 0, 1) * 255)))]):
            d.text((10 + i * (size[0] + 10), 10), t, fill="black")
            im.paste(pic.resize(size, Image.LANCZOS), (10 + i * (size[0] + 10), 34))
        im.save(out / f"{name}.jpg", quality=88)
        results[name] = res
        print(f"\n{name}: EV100 {ev if ev is None else round(ev, 2)} -> exposure {e:.2f} (scene as set up: {e_set:.2f}, {how}); "
              f"white balance {wb_set:.0f} -> {fit['whiteBalance']:.0f} K (light mix {k_mix:.0f} K"
              + (f", adaptation {alpha:.2f}" if alpha is not None else "") + f"); trusted parts dE {fit['dE_set_up']:.1f} -> {fit['dE_fitted']:.1f}")
        for g in groups:
            r = res["groups"][g]
            txt = f"x{2 ** r['log2_scale']:.2f}" if r["fitted"] else "not fitted (too little light on the trusted parts)"
            print(f"  {g:28s} share {r['share']:5.1%}  {txt}" + (f"  {r['kelvin']} K" if "kelvin" in r else "") + (f"  {r['hex']}" if "hex" in r else ""))

    if not results:
        sys.exit("no camera could be fitted")
    # The anchor: the group whose lumens come from data (a spec sheet), else the one seen most. Its fitted scale per
    # photo is the camera's offset (phone processing, or every light being dimmer than modelled: one photo set can't
    # tell those apart); the other groups are reported relative to it, which is what the photos pin down best.
    # Phones process some shots very differently (a bright TV in the frame, Night mode, the ultra-wide camera), so a
    # value counts as CONSISTENT when at least two thirds of the photos agree on it (within --max-spread); the rest
    # are listed as outliers.
    def agree(vals, tol):
        """(consistent, median of the agreeing photos, names of the outliers) for {photo: value}."""
        if len(vals) < 2:
            return False, (float(np.median(list(vals.values()))) if vals else None), []
        med = float(np.median(list(vals.values())))
        inl = {n: v for n, v in vals.items() if abs(v - med) <= tol / 2}
        ok = len(inl) >= max(2, math.ceil(2 * len(vals) / 3))
        return ok, float(np.median(list(inl.values()))) if inl else med, sorted(set(vals) - set(inl))

    fitted_in = {g: {n: r for n, r in results.items() if r["groups"][g].get("fitted")} for g in groups}
    share = {g: float(np.median([r["groups"][g]["share"] for r in results.values()])) for g in groups}
    cands = [g for g in groups if fitted_in[g] and info[g].get("lumens")]
    anchor = a.anchor or max(cands or [g for g in groups if fitted_in[g]],
                             key=lambda g: (not info[g].get("assumed", True), len(fitted_in[g]), share[g]))
    offs = {n: r["groups"][anchor]["log2_scale"] for n, r in fitted_in[anchor].items()}
    off_ok, off_med, off_out = agree(offs, a.max_spread)
    summ, wb_all = {}, {n: r["whiteBalance"]["fitted"] for n, r in results.items()}
    print(f"\nAcross photos (CONSISTENT = two thirds of the photos within {a.max_spread} stops / {a.max_kelvin_spread:.0f} K). "
          f"Anchor: {anchor} ({'lumens from data' if not info[anchor].get('assumed', True) else 'lumens assumed'}).")
    print(f"  camera offset (the anchor's scale): {off_med:+.2f} stops{'  CONSISTENT' if off_ok else ''}"
          + (f" (outliers: {', '.join(off_out)})" if off_out else "")
          + " -- the phone's processing, or every light dimmer than modelled; photos alone can't tell which")
    for g in groups:
        if not fitted_in[g]:
            continue
        absl = {n: r["groups"][g]["log2_scale"] for n, r in fitted_in[g].items()}
        rel = {n: v - offs[n] for n, v in absl.items() if n in offs}
        ks = {n: r["groups"][g]["kelvin"] for n, r in fitted_in[g].items() if "kelvin" in r["groups"][g]}
        a_ok, a_med, a_out = agree(absl, a.max_spread)
        r_ok, r_med, r_out = agree(rel, a.max_spread) if g != anchor else (False, None, [])
        k_ok, k_med, _ = agree(ks, a.max_kelvin_spread)
        scale_ok = a_ok if (a.absolute or g == anchor) else r_ok
        summ[g] = {"photos": len(absl), "log2_scale": round(a_med, 2), "relative_log2": None if r_med is None else round(r_med, 2),
                   "consistent": scale_ok, "outliers": a_out if (a.absolute or g == anchor) else r_out, "anchor": g == anchor,
                   "per_photo": {n: round(v, 2) for n, v in absl.items()}}
        if ks:
            summ[g].update({"kelvin": round(k_med), "kelvin_consistent": k_ok, "kelvin_per_photo": ks})
        hexes = [r["groups"][g]["hex"] for r in fitted_in[g].values() if "hex" in r["groups"][g]]
        if hexes:
            summ[g]["hex"] = hexes[len(hexes) // 2]
        rel_txt = "" if g == anchor or r_med is None else f", relative to {anchor} x{2 ** r_med:.2f}"
        print(f"  {g:28s} photos {len(absl)}  x{2 ** a_med:.2f}{rel_txt}" + ("  CONSISTENT" if scale_ok else "")
              + (f" (outliers: {', '.join(summ[g]['outliers'])})" if scale_ok and summ[g]["outliers"] else "")
              + (f";  {k_med:.0f} K{' CONSISTENT' if k_ok else ''}" if ks else ""))
    alphas = [r["whiteBalance"]["adaptation"] for r in results.values() if r["whiteBalance"]["adaptation"] is not None]
    wb_ok, wb_med, wb_out = agree(wb_all, a.max_kelvin_spread)
    wb_med = int(round(wb_med, -1))
    print(f"  white balance: {wb_med} K (photos {min(wb_all.values())}-{max(wb_all.values())})" + ("  CONSISTENT" if wb_ok else "")
          + (f" (outliers: {', '.join(wb_out)})" if wb_ok and wb_out else "")
          + (f"; the camera neutralised {np.median(alphas):.0%} of the light's cast (median over {len(alphas)} photos; photometry.WB_ADAPTATION = {ph.WB_ADAPTATION})" if alphas else ""))
    dEs = [(r["dE"]["set_up"], r["dE"]["fitted"]) for r in results.values()]
    print(f"  trusted parts dE2000: median {np.median([x for x, _ in dEs]):.1f} as set up -> {np.median([y for _, y in dEs]):.1f} fitted")
    (out / "summary.json").write_text(json.dumps({"lighting": a.lighting, "anchor": anchor, "cameraOffset": round(off_med, 2), "cameraOffsetConsistent": off_ok, "cameraOffsetOutliers": off_out,
                                                  "groups": summ, "whiteBalance": wb_med, "whiteBalanceConsistent": wb_ok,
                                                  "adaptation": None if not alphas else round(float(np.median(alphas)), 2),
                                                  "cameras": list(results)}, indent=2) + "\n")
    if a.write:
        bias = None
        if not a.absolute and room.get("scenes", {}).get(a.lighting, {}).get("exposure") == "photo" and off_ok:
            bias = round(off_med, 1)
        lay = None
        if a.to == "layout":
            lay = {"slug": a.layout, "data": json.loads((rp.ROOM / f"layouts/{a.layout}.json").read_text())}
        changes = write_back(rp.ROOM, a.lighting, info, summ, wb_med if wb_ok else None, a.absolute, bias, lay)
        print("\nwrote:\n  " + ("\n  ".join(changes) if changes else "nothing (no consistent result)"))
    else:
        print("\n(--write puts the CONSISTENT results into room.json / catalog.json)")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
