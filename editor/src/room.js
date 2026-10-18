// Builds the empty room shell (floor, walls with openings, fixtures, ceiling) from room.json.
// Plan (x, y, z-up) maps to three.js as (x, z, -y).
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { walls, doorSwing, fixturePoly, downstandPoly, bbox } from "./geom.js";
import { mat } from "./kit.js";

export const P3 = (x, y, z = 0) => new THREE.Vector3(x, z, -y);

function label(text, cls = "lbl lbl-room") {
  const el = document.createElement("div");
  el.className = cls;
  el.textContent = text;
  return new CSS2DObject(el);
}

function onSegment(p, w) {
  const t = (p[0] - w.a[0]) * w.ux + (p[1] - w.a[1]) * w.uy;
  const off = Math.abs((p[0] - w.a[0]) * w.nx + (p[1] - w.a[1]) * w.ny);
  return off < 0.03 && t > -0.03 && t < w.len + 0.03 ? t : null;
}

export function buildRoom(room) {
  const root = new THREE.Group();
  const H = room.wallHeight, T = room.wallThickness;
  const ws = walls(room.outline);

  // floor
  const shape = new THREE.Shape(room.outline.map(([x, y]) => new THREE.Vector2(x, y)));
  const floor = new THREE.Mesh(new THREE.ShapeGeometry(shape), mat("#c9a27a", { roughness: 0.85 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  floor.name = "floor";
  root.add(floor);

  // 0.5 m floor grid, clipped to the room's bounding box
  const grid = new THREE.Group();
  grid.name = "grid";
  const gm = new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.08 });
  const xs = room.outline.map((p) => p[0]), ys = room.outline.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pts = [];
  for (let x = Math.ceil(x0 * 2) / 2; x <= x1; x += 0.5) pts.push(P3(x, y0, 0.002), P3(x, y1, 0.002));
  for (let y = Math.ceil(y0 * 2) / 2; y <= y1; y += 0.5) pts.push(P3(x0, y, 0.002), P3(x1, y, 0.002));
  grid.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), gm));
  root.add(grid);

  // walls, split around doors/windows
  const wallMat = mat("#cfd6d1", { roughness: 0.95 });
  const wallGroups = [];
  const n = room.outline.length;
  const convexAt = (i) => {
    const p = ws[(i - 1 + n) % n], q = ws[i];
    return p.ux * q.uy - p.uy * q.ux > 0;
  };
  ws.forEach((w, i) => {
    const g = new THREE.Group();
    const extA = convexAt(i) ? T : 0, extB = convexAt((i + 1) % n) ? T : 0;
    const openings = [];
    for (const d of room.doors) {
      const ta = onSegment(d.a, w), tb = onSegment(d.b, w);
      if (ta !== null && tb !== null) openings.push({ t0: Math.min(ta, tb), t1: Math.max(ta, tb), z0: 0, z1: d.height, kind: "door", d });
    }
    for (const win of room.windows) {
      const ta = onSegment(win.a, w), tb = onSegment(win.b, w);
      if (ta !== null && tb !== null) openings.push({ t0: Math.min(ta, tb), t1: Math.max(ta, tb), z0: win.z0, z1: win.z1, kind: "window" });
    }
    openings.sort((a, b) => a.t0 - b.t0);
    const piece = (t0, t1, z0, z1, material = wallMat, depth = T, inset = 0) => {
      if (t1 - t0 < 0.005 || z1 - z0 < 0.005) return;
      const tm = (t0 + t1) / 2, off = -depth / 2 + inset;
      const cx = w.a[0] + w.ux * tm + w.nx * off, cy = w.a[1] + w.uy * tm + w.ny * off;
      const m = new THREE.Mesh(new THREE.BoxGeometry(t1 - t0, z1 - z0, depth), material);
      m.position.copy(P3(cx, cy, (z0 + z1) / 2));
      m.rotation.y = Math.atan2(w.uy, w.ux);
      m.castShadow = m.receiveShadow = true;
      g.add(m);
    };
    let t = -extA;
    for (const o of openings) {
      piece(t, o.t0, 0, H);
      piece(o.t0, o.t1, 0, o.z0);
      piece(o.t0, o.t1, o.z1, H);
      if (o.kind === "window") piece(o.t0, o.t1, o.z0, o.z1, mat("#bcd9ea", { transparent: true, opacity: 0.45, roughness: 0.05 }), 0.02, -T / 2);
      if (o.kind === "door") {
        const style = o.d.style || "door";
        if (style === "door") piece(o.t0 + 0.04, o.t1 - 0.04, 0, o.z1 - 0.02, mat("#f2f0eb"), 0.04, -T + 0.02);
        else if (style === "glass" || style === "sliding")
          piece(o.t0, o.t1, 0, o.z1, mat("#bcd9ea", { transparent: true, opacity: 0.45, roughness: 0.05 }), 0.02, -T / 2);
        // style "opening": cased opening, left open
      }
      t = o.t1;
    }
    piece(t, w.len + extB, 0, H);
    const mid = [w.a[0] + (w.ux * w.len) / 2, w.a[1] + (w.uy * w.len) / 2];
    g.userData = { center: P3(mid[0], mid[1], H / 2), outward: new THREE.Vector3(-w.nx, 0, w.ny) };
    wallGroups.push(g);
    root.add(g);
  });

  // door swings on the floor
  const swingMat = new THREE.LineDashedMaterial({ color: 0x555555, dashSize: 0.06, gapSize: 0.04 });
  for (const d of room.doors) {
    const s = doorSwing(d, room.outline);
    if (!s.poly) continue;
    for (const { hinge, other, len } of s.leaves) {
      const a0 = Math.atan2(other[1] - hinge[1], other[0] - hinge[0]), a1 = Math.atan2(s.ny, s.nx);
      let da = a1 - a0;
      if (da > Math.PI) da -= 2 * Math.PI;
      if (da < -Math.PI) da += 2 * Math.PI;
      const arc = [];
      for (let k = 0; k <= 24; k++) {
        const a = a0 + (da * k) / 24;
        arc.push(P3(hinge[0] + Math.cos(a) * len, hinge[1] + Math.sin(a) * len, 0.004));
      }
      arc.push(P3(hinge[0], hinge[1], 0.004));
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(arc), swingMat);
      line.computeLineDistances();
      root.add(line);
    }
    const lb = label(d.name);
    lb.position.copy(P3((d.a[0] + d.b[0]) / 2 + s.nx * 0.35, (d.a[1] + d.b[1]) / 2 + s.ny * 0.35, 0.05));
    root.add(lb);
  }

  // fixed wall fixtures
  for (const f of room.fixtures) {
    const [[fx0, fy0], , [fx1, fy1]] = fixturePoly(f);
    const m = new THREE.Mesh(new THREE.BoxGeometry(fx1 - fx0, f.z1 - f.z0, fy1 - fy0), mat(f.color ?? "#1a1a1a", { roughness: 0.4 })); // same default as Blender
    m.position.copy(P3((fx0 + fx1) / 2, (fy0 + fy1) / 2, (f.z0 + f.z1) / 2));
    m.castShadow = true;
    root.add(m);
    if (f.conduitToFloor) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, f.z0), mat("#888"));
      c.position.copy(P3((fx0 + fx1) / 2, (fy0 + fy1) / 2, f.z0 / 2));
      root.add(c);
    }
    if (f.label === false) continue;
    const lb = label(f.name);
    lb.position.copy(P3((fx0 + fx1) / 2, (fy0 + fy1) / 2, f.z1 + 0.08));
    root.add(lb);
  }

  // ceiling: downstands hang from the top slab (3D), plus a floor-level height map (plan)
  const ceiling = new THREE.Group();
  ceiling.name = "ceiling";
  const ceilingMap = new THREE.Group();
  ceilingMap.name = "ceilingMap";
  const cm = mat("#9fb4c7", { transparent: true, opacity: 0.35, depthWrite: false });
  const top = room.ceiling.top;
  // colour range from the room's own lowest underside up to the top (red = low, blue = high)
  const lows = room.ceiling.downstands.flatMap((ds) => (ds.slope ? [ds.slope.zFrom, ds.slope.zTo] : [ds.z]));
  const low = Math.min(top - 0.3, ...lows);
  const heightColor = (z) => new THREE.Color().setHSL(0.6 * Math.max(0, Math.min(1, (z - low) / (top - low))), 0.7, 0.55);
  for (const ds of room.ceiling.downstands) {
    const poly = downstandPoly(ds);
    const shape = new THREE.Shape(poly.map(([x, y]) => new THREE.Vector2(x, y)));
    const geo = new THREE.ExtrudeGeometry(shape, { depth: top - ds.z, bevelEnabled: false });
    if (ds.slope) {
      // drop the underside along the slope: shape-space z=0 is the underside
      const pos = geo.attributes.position, s = ds.slope, k = s.axis === "x" ? 0 : 1;
      for (let i = 0; i < pos.count; i++) {
        if (pos.getZ(i) > 1e-6) continue;
        const t = Math.min(Math.max(k ? pos.getY(i) : pos.getX(i), s.from), s.to);
        pos.setZ(i, s.zFrom + ((s.zTo - s.zFrom) * (t - s.from)) / (s.to - s.from) - ds.z);
      }
      geo.computeVertexNormals();
    }
    const m = new THREE.Mesh(geo, cm);
    m.rotation.x = -Math.PI / 2;
    m.position.y = ds.z;
    ceiling.add(m);
    const [bx0, by0, bx1, by1] = bbox(poly);
    const text = ds.slope ? `${ds.name} ${ds.slope.zFrom.toFixed(2)}→${ds.slope.zTo.toFixed(2)} m` : `${ds.name} ${ds.z.toFixed(2)} m`;
    const lb = label(text, "lbl lbl-ceil");
    lb.position.copy(P3((bx0 + bx1) / 2, (by0 + by1) / 2, ds.z));
    ceiling.add(lb);
    // plan map: floor fill colored by underside height (low = red, high = blue)
    const fill = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color: heightColor(ds.slope ? (ds.slope.zFrom + ds.slope.zTo) / 2 : ds.z), transparent: true, opacity: 0.35, depthWrite: false }));
    fill.rotation.x = -Math.PI / 2;
    fill.position.y = 0.004 + ds.z * 0.0001; // lower ceilings draw on top
    ceilingMap.add(fill);
    const lb2 = label(text, "lbl lbl-ceil");
    lb2.position.copy(P3((bx0 + bx1) / 2, (by0 + by1) / 2, 0.01));
    ceilingMap.add(lb2);
  }
  const tl = room.ceiling.topLabel; // optional label(s) for areas at full ceiling height
  for (const [x, y] of tl?.at ?? []) {
    const rest = label(`${tl.name} ${top.toFixed(2)} m`, "lbl lbl-ceil");
    rest.position.copy(P3(x, y, 0.01));
    ceilingMap.add(rest);
  }
  root.add(ceilingMap);
  root.add(ceiling);

  return { root, wallGroups, ceiling, ceilingMap, grid, floor };
}
