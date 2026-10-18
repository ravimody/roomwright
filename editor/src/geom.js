// Plan-space geometry and layout checks. Plan frame: x east, y north (meters).
// Item rot (deg): 0 = front faces south (-y), 90 = east, 180 = north, 270 = west.

export const rad = (deg) => (deg * Math.PI) / 180;

export function toPlan(item, lx, ly) {
  const t = rad(item.rot || 0), c = Math.cos(t), s = Math.sin(t);
  return [item.x + c * lx - s * ly, item.y + s * lx + c * ly];
}

const rectLocal = (item, x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([a, b]) => toPlan(item, a, b));

export function footprint(item, shrink = 0) {
  // baseW/baseD: floor contact for items wider up top (floor lamp shades overhang a sofa arm)
  const w = (item.baseW ?? item.w) / 2 - shrink, d = (item.baseD ?? item.d) / 2 - shrink;
  return rectLocal(item, -w, -d, w, d);
}

// Clearance zones: front = -y local, back = +y. Left/right as seen facing the same way as the
// item's front (facing -y, your left hand points to +x).
export function clearanceZones(item) {
  const c = item.clearance || {}, w = item.w / 2, d = item.d / 2, out = [];
  if (c.front) out.push({ side: "front", poly: rectLocal(item, -w, -d - c.front, w, -d) });
  if (c.back) out.push({ side: "back", poly: rectLocal(item, -w, d, w, d + c.back) });
  if (c.left) out.push({ side: "left", poly: rectLocal(item, w, -d, w + c.left, d) });
  if (c.right) out.push({ side: "right", poly: rectLocal(item, -w - c.right, -d, -w, d) });
  return out;
}

export function shrinkPoly(poly, eps) {
  const cx = poly.reduce((a, p) => a + p[0], 0) / poly.length, cy = poly.reduce((a, p) => a + p[1], 0) / poly.length;
  return poly.map(([x, y]) => {
    const dx = x - cx, dy = y - cy, l = Math.hypot(dx, dy) || 1;
    return [x - (dx / l) * eps, y - (dy / l) * eps];
  });
}

// Separating-axis test for convex polygons.
export function convexOverlap(a, b) {
  for (const poly of [a, b]) {
    for (let i = 0; i < poly.length; i++) {
      const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
      const nx = y1 - y2, ny = x2 - x1;
      const pa = a.map(([x, y]) => x * nx + y * ny), pb = b.map(([x, y]) => x * nx + y * ny);
      if (Math.max(...pa) <= Math.min(...pb) || Math.max(...pb) <= Math.min(...pa)) return false;
    }
  }
  return true;
}

export function pointInPoly([x, y], poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// Convex poly fully inside (possibly concave) room outline.
export function insideRoom(poly, outline) {
  const p = shrinkPoly(poly, 0.01);
  return p.every((pt) => pointInPoly(pt, outline)) && !outline.some((v) => pointInPoly(v, p));
}

export function distPointPoly([px, py], poly) {
  if (pointInPoly([px, py], poly)) return 0;
  let best = Infinity;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
    const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy;
    const t = L ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / L)) : 0;
    best = Math.min(best, Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)));
  }
  return best;
}

export function distPolyPoly(a, b) {
  if (polysOverlap(a, b)) return 0;
  return Math.min(...a.map((p) => distPointPoly(p, b)), ...b.map((p) => distPointPoly(p, a)));
}

export const bbox = (poly) => {
  const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
};

export const rectPoly = ([x0, y0, x1, y1]) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];

// Wall segments of the outline with inward normals (outline is CCW → interior on the left).
export function walls(outline) {
  return outline.map((a, i) => {
    const b = outline[(i + 1) % outline.length];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len;
    return { a, b, len, ux, uy, nx: -uy, ny: ux };
  });
}

// Rotation (deg) that makes an item's front face along a wall's inward normal.
export const rotFacing = (nx, ny) => ((Math.round((Math.atan2(nx, -ny) * 180) / Math.PI) % 360) + 360) % 360;

export function nearestWall(x, y, ws) {
  let best = null;
  for (const w of ws) {
    const t = Math.max(0, Math.min(w.len, (x - w.a[0]) * w.ux + (y - w.a[1]) * w.uy));
    const px = w.a[0] + w.ux * t, py = w.a[1] + w.uy * t;
    const dist = Math.hypot(x - px, y - py);
    if (!best || dist < best.dist) best = { wall: w, t, px, py, dist };
  }
  return best;
}

const segsCross = ([a, b], [c, d]) => {
  const o = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
  return o(a, b, c) * o(a, b, d) < 0 && o(c, d, a) * o(c, d, b) < 0;
};

// Overlap test for simple (possibly concave) polygons.
export function polysOverlap(a, b) {
  if (a.some((p) => pointInPoly(p, b)) || b.some((p) => pointInPoly(p, a))) return true;
  for (let i = 0; i < a.length; i++)
    for (let j = 0; j < b.length; j++)
      if (segsCross([a[i], a[(i + 1) % a.length]], [b[j], b[(j + 1) % b.length]])) return true;
  return false;
}

export const downstandPoly = (ds) => ds.poly ?? rectPoly(ds.rect);

// Lowest ceiling height over a footprint. Sloped downstands are linear along slope.axis.
export function ceilingOver(poly, room) {
  const fp = bbox(poly);
  const inner = shrinkPoly(poly, 0.005);
  let z = room.ceiling.top;
  for (const ds of room.ceiling.downstands) {
    if (!polysOverlap(inner, downstandPoly(ds))) continue;
    const s = ds.slope;
    if (!s) { z = Math.min(z, ds.z); continue; }
    const k = s.axis === "x" ? 0 : 1;
    const at = (t) => s.zFrom + ((s.zTo - s.zFrom) * (Math.min(Math.max(t, s.from), s.to) - s.from)) / (s.to - s.from);
    z = Math.min(z, at(fp[k]), at(fp[k + 2]));
  }
  return z;
}

export function doorSwing(door, outline) {
  const [ax, ay] = door.a, [bx, by] = door.b;
  const len = Math.hypot(bx - ax, by - ay), ux = (bx - ax) / len, uy = (by - ay) / len;
  let nx = -uy, ny = ux;
  const mid = [(ax + bx) / 2, (ay + by) / 2];
  if (!pointInPoly([mid[0] + nx * 0.1, mid[1] + ny * 0.1], outline)) { nx = -nx; ny = -ny; }
  // swing-out doors, cased openings and sliding doors have no swing arc on this side
  if (door.swing === "out" || door.style === "opening" || door.style === "sliding") return { poly: null, leaves: [], nx, ny, len };
  // one leaf hinged at door.hinge ("a" default), or leaves: 2 = a pair hinged at both jambs meeting in the middle
  const box = (p, q, w) => [p, q, [q[0] + nx * w, q[1] + ny * w], [p[0] + nx * w, p[1] + ny * w]];
  const leaves = door.leaves === 2
    ? [{ hinge: door.a, other: mid, len: len / 2, poly: box(door.a, mid, len / 2) }, { hinge: door.b, other: mid, len: len / 2, poly: box(mid, door.b, len / 2) }]
    : [{ hinge: door.hinge === "b" ? door.b : door.a, other: door.hinge === "b" ? door.a : door.b, len, poly: box(door.a, door.b, len) }];
  return { poly: leaves[0].poly, leaves, nx, ny, len };
}

// ---------- room and item normalisation (shared by the editor and tools/check_layout.mjs) ----------

const signedArea = (poly) => poly.reduce((a, [x1, y1], i) => {
  const [x2, y2] = poly[(i + 1) % poly.length];
  return a + x1 * y2 - x2 * y1;
}, 0) / 2;

// Fill optional room.json keys once, so the rest of the code can rely on them. Returns the room (mutated), with
// room._warnings listing what looked wrong (clockwise outline, repeated vertices).
export function normalizeRoom(room) {
  const w = [];
  room.doors ??= [];
  room.windows ??= [];
  room.fixtures ??= [];
  room.rules ??= [];
  room.ceiling ??= { top: room.wallHeight ?? 2.4 };
  room.ceiling.downstands ??= [];
  room.wallHeight ??= room.ceiling.top;
  room.wallThickness ??= 0.12;
  const n0 = room.outline.length;
  room.outline = room.outline.filter((p, i, a) => {
    const q = a[(i + 1) % a.length];
    return Math.hypot(q[0] - p[0], q[1] - p[1]) > 1e-6;
  });
  if (room.outline.length !== n0) w.push(`outline had ${n0 - room.outline.length} repeated vertex(es); ignored`);
  if (signedArea(room.outline) < 0) w.push("outline is clockwise; room.json outlines must be counter-clockwise (wall normals and snapping assume it)");
  room._warnings = w;
  return room;
}

const FALLBACK_ITEM = { name: "Unknown item", category: "Other", model: "box", w: 0.5, d: 0.5, h: 0.5, color: "#999999" };

// The full spec of a layout item: catalog entry (room catalog over shared) plus the item's own overrides.
export function makeSpec(catalog, inst, room) {
  const known = inst.type in catalog;
  const base = known ? catalog[inst.type] : catalog.generic_box ?? FALLBACK_ITEM;
  const s = { ...base, ...inst, name: inst.label || (known ? base.name : `${inst.type} (unknown type)`) };
  if (!known) s.unknownType = true;
  if (s.model === "parts" && s.partsSize == null) s.partsSize = [base.w ?? s.w, base.d ?? s.d, base.h ?? s.h]; // parts' drawn size
  // `hang: "ceiling"` (a pendant, a ceiling fan): without its own `ceiling`, it hangs from the room's ceiling over it
  if (s.ceiling == null && s.hang === "ceiling" && room) s.ceiling = ceilingOver(footprint(s), room);
  return s;
}

// Ceiling-hung items carry `ceiling` and hang h below it; the rest stand at z.
export const zRange = (it) => (it.ceiling != null && !it.z ? [it.ceiling - it.h, it.ceiling] : [it.z || 0, (it.z || 0) + it.h]);
const zOverlap = (a, b) => a[0] < b[1] - 0.005 && b[0] < a[1] - 0.005;
const centroid = (poly) => [poly.reduce((a, p) => a + p[0], 0) / poly.length, poly.reduce((a, p) => a + p[1], 0) / poly.length];

// b rests on or sits in a: `on: <a.id>`, or b is lifted (z > 0), its centre is over a, and its bottom is within 3 cm
// of a's top or its footprint lies inside a's (a vase on a shelf, towels in a basket).
function restsOn(b, a, fa, fb) {
  if (b.on === a.id) return true;
  if (!(b.z > 0) || b.ceiling != null || a.ceiling != null) return false;
  const [a0, a1] = zRange(a);
  if (b.z < a0 + 0.01 || !pointInPoly(centroid(fb), fa)) return false;
  return Math.abs(b.z - a1) <= 0.03 || fb.every((p) => pointInPoly(p, shrinkPoly(fa, -0.01)));
}

// Clear height under a table top: catalog `kneeSpace` in metres, or "apron": for a table without drawers, just under
// its apron (`apron` deep, default 0.1 m, below a `top` thick top, default 0.04 m).
function kneeSpace(t) {
  if (typeof t.kneeSpace === "number") return t.kneeSpace;
  if (t.kneeSpace === "apron" && !t.drawer && t.h > 0.6) {
    const apron = typeof t.apron === "number" ? t.apron : 0.1;
    return apron < 0.2 ? t.h - (typeof t.top === "number" ? t.top : 0.04) - apron : null;
  }
  return null;
}
// A chair (anything with a seatH) whose seat fits under a table's apron can be pushed in.
const tucksUnder = (chair, table) => chair.seatH != null && kneeSpace(table) != null && chair.seatH <= kneeSpace(table) - 0.02;
// Pieces of one sectional, a desk and its return, and so on share a `group`: no clearance warnings between them.
const sameGroup = (a, b) => a.group != null && a.group === b.group;

// Returns [{level: 'error'|'warn'|'info', ids: [...], msg}]
export function checkLayout(items, room) {
  const out = [];
  const solid = items.filter((it) => !it.floorLayer);
  const fps = new Map(items.map((it) => [it.id, footprint(it)]));
  const name = (it) => it.label || it.name;
  const byId = new Map(items.map((it) => [it.id, it]));

  for (const w of room._warnings ?? []) out.push({ level: "warn", ids: [], msg: `room.json: ${w}` });
  const seen = new Set();
  for (const it of items) {
    if (seen.has(it.id)) out.push({ level: "error", ids: [it.id], msg: `Two items share the id ${it.id}` });
    seen.add(it.id);
    if (it.unknownType) out.push({ level: "warn", ids: [it.id], msg: `${it.id}: unknown type "${it.type}" (drawn as a plain box)` });
    if (it.on != null && !byId.has(it.on)) out.push({ level: "warn", ids: [it.id], msg: `${name(it)}: "on" names a missing item (${it.on})` });
  }

  for (const it of items) {
    if (!insideRoom(fps.get(it.id), room.outline)) out.push({ level: "error", ids: [it.id], msg: `${name(it)} sticks out past a wall` });
    const ceil = ceilingOver(fps.get(it.id), room);
    const top = (it.z || 0) + it.h;
    if (!it.floorLayer && it.ceiling == null && top > ceil - 0.01) out.push({ level: "error", ids: [it.id], msg: `${name(it)} is ${top.toFixed(2)} m tall here but the ceiling is ${ceil.toFixed(2)} m` });
  }

  for (let i = 0; i < solid.length; i++)
    for (let j = i + 1; j < solid.length; j++) {
      const a = solid[i], b = solid[j];
      const fa = fps.get(a.id), fb = fps.get(b.id);
      if (!zOverlap(zRange(a), zRange(b)) || !convexOverlap(shrinkPoly(fa, 0.01), shrinkPoly(fb, 0.01))) continue;
      if (restsOn(a, b, fb, fa) || restsOn(b, a, fa, fb) || tucksUnder(a, b) || tucksUnder(b, a)) continue;
      out.push({ level: "error", ids: [a.id, b.id], msg: `${name(a)} overlaps ${name(b)}` });
    }

  for (const a of solid)
    for (const z of clearanceZones(a)) {
      const zp = shrinkPoly(z.poly, 0.01);
      if (!insideRoom(z.poly, room.outline)) out.push({ level: "warn", ids: [a.id], msg: `${name(a)}: ${z.side} clearance runs into a wall` });
      for (const b of solid) {
        if (b === a || b.d <= 0.1 || zRange(b)[0] > 1.9) continue; // flat wall items and ceiling lights don't block clearance
        if (sameGroup(a, b) || restsOn(b, a, fps.get(a.id), fps.get(b.id)) || tucksUnder(b, a)) continue;
        if (convexOverlap(zp, fps.get(b.id))) out.push({ level: "warn", ids: [a.id, b.id], msg: `${name(b)} is in ${name(a)}'s ${z.side} clearance` });
      }
    }

  for (const door of room.doors) {
    if (door.style === "sliding") continue; // walk path handled by a keepClear rule in front of the operable panels
    const sw = doorSwing(door, room.outline);
    const zones = sw.leaves.length ? sw.leaves.map((l) => l.poly) : [[door.a, door.b, [door.b[0] + sw.nx * 0.6, door.b[1] + sw.ny * 0.6], [door.a[0] + sw.nx * 0.6, door.a[1] + sw.ny * 0.6]]];
    for (const b of solid)
      if (zRange(b)[0] < door.height && zones.some((zone) => convexOverlap(shrinkPoly(zone, 0.01), fps.get(b.id))))
        out.push({ level: "error", ids: [b.id], msg: `${name(b)} blocks the ${door.name}` });
  }

  const openings = [
    ...room.windows.map((w) => ({ name: w.name, poly: segPoly(w.a, w.b), z: [w.z0, w.z1] })),
    ...room.fixtures.map((f) => ({ name: f.name, poly: fixturePoly(f), z: [f.z0, f.z1] })),
  ];
  for (const o of openings)
    for (const b of solid)
      if (zOverlap(o.z, zRange(b)) && convexOverlap(o.poly, fps.get(b.id))) out.push({ level: "warn", ids: [b.id], msg: `${name(b)} covers the ${o.name}` });

  for (const r of room.rules || []) {
    const label = r.message || r.name || r.kind;
    if (r.kind === "keepClear") {
      const zone = rectPoly(r.rect);
      for (const b of solid)
        if (zRange(b)[0] < (r.maxZ ?? 2.0) && convexOverlap(shrinkPoly(zone, 0.005), fps.get(b.id))) out.push({ level: r.level || "error", ids: [b.id], msg: `${name(b)}: ${label}` });
      continue;
    }
    if (r.kind !== "maxDistance" && r.kind !== "minDistance") {
      out.push({ level: "warn", ids: [], msg: `room.json rule "${label}": unknown kind "${r.kind}" (ignored)` });
      continue;
    }
    const f = r.kind === "minDistance" ? room.fixtures.find((x) => x.id === r.fixture) : null;
    if (r.kind === "minDistance" && !f) {
      out.push({ level: "error", ids: [], msg: `room.json rule "${label}": no fixture with id "${r.fixture}"` });
      continue;
    }
    for (const it of items.filter((i) => i.type === r.itemType)) {
      if (r.kind === "maxDistance") {
        const dist = distPointPoly(r.to, fps.get(it.id));
        if (dist > r.max) out.push({ level: r.level || "error", ids: [it.id], msg: `${label} (now ${dist.toFixed(2)} m, max ${r.max} m)` });
      } else {
        const dist = distPolyPoly(fixturePoly(f), fps.get(it.id));
        if (dist < r.min - 0.005) out.push({ level: r.level || "warn", ids: [it.id], msg: `${label} (now ${dist.toFixed(2)} m)` });
      }
    }
  }
  return out;
}

function segPoly(a, b, t = 0.12) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]), nx = -(b[1] - a[1]) / len, ny = (b[0] - a[0]) / len;
  return [[a[0] - nx * t, a[1] - ny * t], [b[0] - nx * t, b[1] - ny * t], [b[0] + nx * t, b[1] + ny * t], [a[0] + nx * t, a[1] + ny * t]];
}

export function fixturePoly(f) {
  if (f.wall === "north" || f.wall === "south") {
    const s = f.wall === "north" ? -1 : 1;
    return rectPoly([f.x0, Math.min(f.y, f.y + s * f.depth), f.x1, Math.max(f.y, f.y + s * f.depth)]);
  }
  const s = f.wall === "east" ? -1 : 1;
  return rectPoly([Math.min(f.x, f.x + s * f.depth), f.y0, Math.max(f.x, f.x + s * f.depth), f.y1]);
}
