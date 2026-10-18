// The editor's modelling kit (mirrors tools/blender_models.py). The engine ships no furniture library: it draws an item
// with a core model (box; parts, primitives listed in the catalog; glb, a model file; mat and roundRug, flat rugs) or
// with a household builder: builders/*.js next to rooms/ (and a room's own builders/), each exporting
// BUILDERS = {name(s, g) {...}} and importing these helpers from "/editor/src/kit.js".
// Each builder fills a Group in the item's local frame: origin at footprint center, floor at y=0, width along X,
// depth along Z, front facing +Z.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
const matCache = new Map();

export function mat(color, opts = {}) {
  const key = color + JSON.stringify(opts);
  if (!matCache.has(key)) matCache.set(key, new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.1, ...opts }));
  return matCache.get(key);
}

export function box(g, w, h, d, x, y, z, material) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  g.add(m);
  return m;
}

export function cyl(g, r, len, x, y, z, material, axis = "y", seg = 20) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg), material);
  if (axis === "x") m.rotation.z = Math.PI / 2;
  if (axis === "z") m.rotation.x = Math.PI / 2;
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  g.add(m);
  return m;
}

// Room-relative assets (rug textures). main.js sets the room folder URL.
let assetBase = "";

export function setAssetBase(base) {
  assetBase = base;
}

const rugMats = new Map();

export function rugMaterial(path) {
  // whole-rug image; top of the image = the rug's back (north at rot 0), i.e. -Z in the editor frame
  if (!rugMats.has(path)) {
    const tex = new THREE.TextureLoader().load(assetBase + path);
    tex.colorSpace = THREE.SRGBColorSpace;
    rugMats.set(path, new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95 }));
  }
  return rugMats.get(path);
}

// Deterministic 0..1 noise, same formula as tools/blender_models.py rnd(), so both draw the same books.
export const rnd = (k) => (((Math.sin(k * 12.9898) * 43758.5453) % 1) + 1) % 1;

export const steel = () => mat("#2b2b2b", { metalness: 0.6, roughness: 0.4 });

export const chrome = () => mat("#b8bcc2", { metalness: 0.9, roughness: 0.25 });

export const pad = () => mat("#151515", { roughness: 0.9 });

export function lathe(g, profile, material, x = 0, z = 0) {
  const m = new THREE.Mesh(new THREE.LatheGeometry(profile.map(([r, y]) => new THREE.Vector2(Math.max(r, 0.001), y)), 24), material);
  m.position.set(x, 0, z);
  m.castShadow = m.receiveShadow = true;
  g.add(m);
  return m;
}

export const lin = (c) => "#" + new THREE.Color().setRGB(c[0], c[1], c[2], THREE.LinearSRGBColorSpace).getHexString(THREE.SRGBColorSpace);

export const glow = (color = "#fff1dc", k = 0.6) => mat(color, { emissive: "#ffd9a0", emissiveIntensity: k });

export const paperLit = () => mat("#f2ead9", { side: THREE.DoubleSide, emissive: "#ffd9a0", emissiveIntensity: 0.35 });

export function frustum(g, rTop, rBottom, len, x, y, z, material, seg = 24) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rTop, rBottom, len, seg), material);
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  g.add(m);
  return m;
}

export function rng(seed) {
  // small deterministic PRNG (mulberry32), so plants keep their shape between redraws
  let a = (seed | 0) + 0x6d2b79f5;
  return (lo = 0, hi = 1) => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return lo + (hi - lo) * (((t ^ (t >>> 14)) >>> 0) / 4294967296);
  };
}

const builders = {
  box(s, g) {
    box(g, s.w, s.h, s.d, 0, s.h / 2, 0, mat(s.color ?? "#999999"));
  },

  mat(s, g) {
    const m = box(g, s.w, Math.max(s.h, 0.005), s.d, 0, Math.max(s.h, 0.005) / 2, 0, s.texture ? rugMaterial(s.texture) : mat(s.color, { roughness: 0.95 }));
    m.castShadow = false;
  },

  roundRug(s, g) {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(s.w / 2, s.w / 2, 0.01, 48), mat(s.color, { roughness: 0.95 }));
    m.position.y = 0.005;
    m.receiveShadow = true;
    g.add(m);
  },

};

// ---------- parts: simple modelling as catalog data (the same data as tools/blender_models.py b_parts)
// Part positions are item-local metres in the plan frame: x to the right as you face the item's front, y toward its
// back, z up. The editor frame is (x, y_up, z_front), so a plan point (x, y, z) is (x, z, -y) here.
const DEG = Math.PI / 180;
const PART_MIRRORS = { x: [[1, 1], [-1, 1]], y: [[1, 1], [1, -1]], xy: [[1, 1], [-1, 1], [1, -1], [-1, -1]] };
const AX = { x: new THREE.Vector3(1, 0, 0), y: new THREE.Vector3(0, 1, 0), z: new THREE.Vector3(0, 0, 1) };
const q = (axis, a) => new THREE.Quaternion().setFromAxisAngle(AX[axis], a);

// A rotation given as plan-frame degrees [rx, ry, rz] (applied x, then y, then z, as Blender's XYZ Euler).
export function planRotation([rx, ry, rz] = [0, 0, 0]) {
  return q("y", rz * DEG).multiply(q("z", -ry * DEG)).multiply(q("x", rx * DEG));
}

// A part's material: a name from the item's `materials`, a "#rrggbb" colour, or the item's own colour.
export function partMaterial(s, ref) {
  const mats = s.materials ?? {};
  const spec = typeof ref === "string" && mats[ref] ? mats[ref] : typeof ref === "string" && ref.startsWith("#") ? { hex: ref } : {};
  const color = spec.hex ?? s.color ?? "#888888";
  const rough = spec.rough;
  switch (spec.kind ?? "paint") {
    case "wood":
      return mat(color, { roughness: rough ?? 0.55 });
    case "fabric":
      return mat(color, { roughness: rough ?? 0.95, metalness: 0 });
    case "metal":
      return mat(color, { roughness: rough ?? 0.3, metalness: spec.metal ?? 1 });
    case "glass":
      return mat(color, { roughness: rough ?? 0.02, metalness: 0, transparent: true, opacity: 0.35 });
    case "shade":
      return paperLit();
    case "glow":
      return glow(color);
    default:
      return mat(color, { roughness: rough ?? 0.6, metalness: spec.metal ?? 0 });
  }
}

function addPart(g, p, material, sx, sy) {
  const [ax, ay, az] = p.at ?? [0, 0, 0];
  const x = ax * sx, y = ay * sy;
  let [rx, ry, rz] = p.rot ?? [0, 0, 0];
  if (sx < 0) [ry, rz] = [-ry, -rz];
  if (sy < 0) [rx, rz] = [-rx, -rz];
  const shape = p.shape ?? "box", seg = p.seg ?? 32;
  let geom, base = new THREE.Quaternion();
  if (shape === "box") geom = new THREE.BoxGeometry(p.size[0], p.size[2], p.size[1]);
  else if (shape === "cylinder" || shape === "cone") {
    const [r0, r1] = shape === "cylinder" ? [p.r, p.r] : [p.r0, p.r1];
    geom = new THREE.CylinderGeometry(Math.max(r1, 1e-4), Math.max(r0, 1e-4), p.h, seg, 1, !!p.open);
    base = { x: q("z", Math.PI / 2), y: q("x", Math.PI / 2), z: new THREE.Quaternion() }[p.axis ?? "z"];
  } else if (shape === "sphere") geom = new THREE.SphereGeometry(p.r, seg, Math.max(seg / 2, 4));
  else if (shape === "lathe") geom = new THREE.LatheGeometry(p.profile.map(([r, z]) => new THREE.Vector2(Math.max(r, 0.001), z)), seg);
  else if (shape === "extrude") {
    const sh = new THREE.Shape(p.points.map(([px, py]) => new THREE.Vector2(px * sx, py * sy)));
    geom = new THREE.ExtrudeGeometry(sh, { depth: p.h, bevelEnabled: false });
    base = q("x", -Math.PI / 2); // shape (x, y) lies in the plan, extruded up
  } else return null;
  if (p.open && material.side !== THREE.DoubleSide) {
    material = material.clone(); // an open shade or tube shows its inside too
    material.side = THREE.DoubleSide;
  }
  const m = new THREE.Mesh(geom, material);
  if (shape === "sphere" && p.scale) m.scale.set(p.scale[0], p.scale[2], p.scale[1]);
  m.quaternion.copy(planRotation([rx, ry, rz]).multiply(base));
  m.position.set(x, az, -y);
  m.castShadow = m.receiveShadow = true;
  if (p.role) m.userData.role = p.role;
  g.add(m);
  return m;
}

// ---------- glb: a model file fitted to the item's w x d x h (tools/blender_models.py b_glb)
let householdBase = "/household/";
export function setHouseholdBase(base) {
  householdBase = base;
}
const gltfs = new Map();
function loadGLB(file) {
  if (!gltfs.has(file)) {
    const loader = new GLTFLoader();
    gltfs.set(file, loader.loadAsync(assetBase + file).catch(() => loader.loadAsync(householdBase + file)));
  }
  return gltfs.get(file);
}

function glbModel(s, g) {
  const holder = new THREE.Group();
  g.add(holder);
  loadGLB(s.file)
    .then((gltf) => {
      const turn = new THREE.Group(); // `rotate` first, then the fit, in room axes
      turn.quaternion.copy(planRotation(s.rotate));
      turn.add(gltf.scene.clone(true));
      turn.traverse((o) => {
        if (o.isMesh) o.castShadow = o.receiveShadow = true;
      });
      turn.updateMatrixWorld(true);
      const bb = new THREE.Box3().setFromObject(turn), size = bb.getSize(new THREE.Vector3());
      let k = [s.w / Math.max(size.x, 1e-6), s.h / Math.max(size.y, 1e-6), s.d / Math.max(size.z, 1e-6)];
      if ((s.fit ?? "scale") === "scale") k = Array(3).fill(Math.min(...k));
      else if (s.fit === "none") k = [1, 1, 1];
      holder.scale.set(...k);
      holder.position.set((-(bb.min.x + bb.max.x) / 2) * k[0], -bb.min.y * k[1], (-(bb.min.z + bb.max.z) / 2) * k[2]);
      holder.add(turn);
    })
    .catch(() => {
      console.warn(`model file ${s.file} not found for ${s.id ?? s.name}; drawn as a box`);
      builders.box(s, holder);
    });
}

// ---------- registry: core models plus the household's and room's builders (builders/*.js, loaded by loadBuilders)
Object.assign(builders, {
  // drawn at `partsSize` (default: the catalog entry's size); an item resized in a layout stretches
  parts(s, g) {
    if (!s.parts?.length) return builders.box(s, g);
    const [pw, pd, ph] = s.partsSize ?? [s.w, s.d, s.h];
    g.scale.set(s.w / pw, s.h / ph, s.d / pd);
    const mats = new Map();
    for (const p of s.parts) {
      if (!mats.has(p.material)) mats.set(p.material, partMaterial(s, p.material));
      for (const [sx, sy] of PART_MIRRORS[p.mirror] ?? [[1, 1]]) addPart(g, p, mats.get(p.material), sx, sy);
    }
  },
  glb: glbModel,
});
export const CORE = Object.keys(builders);

export function registerBuilders(reg) {
  Object.assign(builders, reg);
}

export const hasBuilder = (name) => name in builders;

// Import every builder module the server lists for a room (household builders/, then the room's own); returns the
// problems (a module that fails to load is skipped, its items draw as boxes).
export async function loadBuilders(roomId) {
  const problems = [];
  let urls = [];
  try {
    const r = await fetch(`/api/builders?room=${encodeURIComponent(roomId)}`);
    urls = r.ok ? await r.json() : [];
  } catch (e) {
    problems.push(`builder list: ${e.message}`);
  }
  for (const url of urls) {
    try {
      registerBuilders((await import(url)).BUILDERS ?? {});
    } catch (e) {
      problems.push(`${url}: ${e.message}`);
    }
  }
  return problems;
}

export function buildModel(spec) {
  const g = new THREE.Group();
  (builders[spec.model] ?? builders.box)(spec, g);
  // the core models are drawn from the floor; a ceiling-hung one (`hang: "ceiling"`, or a `ceiling` height) hangs h below
  // it (household builders read spec.ceiling themselves)
  if (CORE.includes(spec.model ?? "box") && spec.ceiling != null && !spec.z) g.position.y = spec.ceiling - spec.h;
  return g;
}
