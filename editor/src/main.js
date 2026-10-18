import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { buildModel, loadBuilders, setAssetBase } from "./kit.js";
import { buildRoom, P3 } from "./room.js";
import { footprint, clearanceZones, checkLayout, walls, nearestWall, rotFacing, bbox, rad, makeSpec, normalizeRoom, zRange } from "./geom.js";

const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  try {
    return await r.json();
  } catch (e) {
    throw new Error(`${url}: invalid JSON (${e.message})`);
  }
}
// Fatal start-up problems (unknown room, broken room.json) replace the viewport with a message.
function fatal(html) {
  $("#viewport").innerHTML = `<div class="picker">${html}</div>`;
  $("#sidebar").style.display = "none";
  throw new Error("editor stopped");
}

// ?room=<folder under rooms/> picks the room; without it, a room picker. Files are fetched relative to the server root.
const params = new URLSearchParams(location.search);
const ROOM_ID = params.get("room");
if (!ROOM_ID) {
  const rooms = await fetchJSON("/api/rooms").catch((e) => fatal(`<p>Couldn't list rooms: ${esc(e.message)}. Start the editor with <code>uv run server.py</code>.</p>`));
  if (rooms.length === 1) location.replace(`?room=${encodeURIComponent(rooms[0].id)}`);
  fatal(rooms.length
    ? `<h2>Pick a room</h2><ul>${rooms.map((r) => `<li><a href="?room=${encodeURIComponent(r.id)}">${esc(r.name)}</a> <span class="muted">${esc(r.id)}</span></li>`).join("")}</ul>`
    : `<h2>No rooms yet</h2><p>Create one with <code>tools/new_room.sh &lt;room&gt; &lt;scan.glb&gt;</code>, or copy <code>rooms/_template/</code>.</p>`);
}
const ROOM_BASE = `../rooms/${ROOM_ID}/`;
setAssetBase(ROOM_BASE);
const room = normalizeRoom(await fetchJSON(`${ROOM_BASE}room.json`).catch((e) => fatal(`<h2>Can't open room “${esc(ROOM_ID)}”</h2><p>${esc(e.message)}</p><p><a href="?">All rooms</a></p>`)));
document.title = `${room.name ?? ROOM_ID} · Layout editor`;
// catalogs: the engine's generic entries, then the household's catalog.json (next to rooms/), then the room's own
async function optionalCatalog(url, what) {
  try {
    return (await fetchJSON(url)).items ?? {};
  } catch (e) {
    if (!/HTTP 404/.test(e.message)) setTimeout(() => status(`${what} catalog ignored: ${e.message}`), 0);
    return {};
  }
}
const catalog = {
  ...(await fetchJSON("../shared/catalog.json")).items,
  ...(await optionalCatalog("/household/catalog.json", "Household")),
  ...(await optionalCatalog(`${ROOM_BASE}catalog.json`, "Room")),
};
// the household's and the room's builders (builders/*.js); a module that fails to load draws its items as boxes
const builderProblems = await loadBuilders(ROOM_ID);
if (builderProblems.length) setTimeout(() => status(`Builders skipped: ${builderProblems.join("; ")}`), 0);
const WALLS = walls(room.outline);
const ROOM_C = (() => {
  const b = bbox(room.outline);
  return { x: (b[0] + b[2]) / 2, y: (b[1] + b[3]) / 2, w: b[2] - b[0], d: b[3] - b[1] };
})();

// ---------- state ----------
const state = {
  slug: null,
  layout: { name: "", description: "", items: [] },
  extra: {}, // other top-level layout keys (listening, flow, ...): kept as loaded and written back on save
  selected: null,
  dirty: false,
  undo: [],
  redo: [],
  issues: [],
  view: "3d",
  show: { clearance: true, ceiling: false, labels: true, scan: false, grid: true },
  scanOpacity: 0.5,
};

const spec = (inst) => makeSpec(catalog, inst, room);
const findItem = (id) => state.layout.items.find((i) => i.id === id);

// ---------- three setup ----------
const viewport = $("#viewport");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
viewport.appendChild(renderer.domElement);
const labelRenderer = new CSS2DRenderer();
labelRenderer.domElement.className = "label-layer";
viewport.appendChild(labelRenderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color("#e9e6e1");
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.55;
scene.add(new THREE.HemisphereLight(0xffffff, 0xb0a090, 0.9));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.copy(P3(ROOM_C.x - 2, ROOM_C.y - 3, 6));
sun.target.position.copy(P3(ROOM_C.x, ROOM_C.y, 0));
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6, near: 0.5, far: 20 });
sun.shadow.bias = -0.0005;
scene.add(sun, sun.target);

const persp = new THREE.PerspectiveCamera(45, 1, 0.05, 100);
persp.position.copy(P3(ROOM_C.x - 1.5, ROOM_C.y - 6.5, 6.5));
const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 100);
ortho.position.copy(P3(ROOM_C.x, ROOM_C.y, 30));
ortho.up.set(0, 0, -1);
ortho.lookAt(P3(ROOM_C.x, ROOM_C.y, 0));
const ctl3d = new OrbitControls(persp, renderer.domElement);
ctl3d.target.copy(P3(ROOM_C.x, ROOM_C.y, 0.6));
ctl3d.maxPolarAngle = Math.PI / 2 - 0.02;
ctl3d.enableDamping = true;
const ctlPlan = new OrbitControls(ortho, renderer.domElement);
ctlPlan.target.copy(P3(ROOM_C.x, ROOM_C.y, 0));
ctlPlan.enableRotate = false;
ctlPlan.screenSpacePanning = true;
ctlPlan.enabled = false;
const camera = () => (state.view === "3d" ? persp : ortho);
const controls = () => (state.view === "3d" ? ctl3d : ctlPlan);

const shell = buildRoom(room);
scene.add(shell.root);

const itemsRoot = new THREE.Group();
const overlayRoot = new THREE.Group(); // clearances, footprints, dimensions
scene.add(itemsRoot, overlayRoot);
const meshes = new Map(); // id -> { group, sig, label }

function resize() {
  const w = viewport.clientWidth, h = viewport.clientHeight;
  renderer.setSize(w, h);
  labelRenderer.setSize(w, h);
  persp.aspect = w / h;
  persp.updateProjectionMatrix();
  const pad = 1.15, aspect = w / h;
  let hw = (ROOM_C.w / 2) * pad, hh = (ROOM_C.d / 2) * pad;
  if (hw / hh > aspect) hh = hw / aspect;
  else hw = hh * aspect;
  Object.assign(ortho, { left: -hw, right: hw, top: hh, bottom: -hh });
  ortho.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewport);

// ---------- scan overlay ----------
let scanMesh = null, scanLoading = false;
function updateScan() {
  if (state.show.scan && !room.scan?.file) {
    status("No scan in room.json (scan.file)");
    return;
  }
  if (state.show.scan && !scanMesh && !scanLoading) {
    scanLoading = true;
    status("Loading scan…");
    new GLTFLoader().load(
      ROOM_BASE + room.scan.file,
      (gltf) => {
        scanMesh = gltf.scene;
        scanMesh.position.set(...(room.scan.position ?? [0, 0, 0]));
        scanMesh.rotation.y = rad(room.scan.rotationYDeg ?? 0);
        scanMesh.traverse((o) => {
          if (o.isMesh) {
            o.material.transparent = true;
            o.material.side = THREE.DoubleSide;
            o.raycast = () => {};
          }
        });
        scene.add(scanMesh);
        scanLoading = false;
        status("");
        updateScan();
      },
      undefined,
      () => {
        scanLoading = false;
        status(`Couldn't load ${room.scan.file} — run tools/align_and_render.py first`);
      },
    );
  }
  if (!scanMesh) return;
  scanMesh.visible = state.show.scan;
  scanMesh.traverse((o) => {
    if (o.isMesh) {
      o.material.opacity = state.scanOpacity;
      o.material.depthWrite = state.scanOpacity > 0.95;
    }
  });
  itemsRoot.visible = !(state.show.scan && state.scanOpacity > 0.95);
}

// ---------- item rendering ----------
// Rebuild an item's mesh when anything but its placement changes (an undo can restore any override).
const PLACEMENT = new Set(["x", "y", "rot", "z"]);
function syncItems() {
  const ids = new Set(state.layout.items.map((i) => i.id));
  for (const [id, m] of meshes) if (!ids.has(id)) { itemsRoot.remove(m.group); meshes.delete(id); }
  for (const inst of state.layout.items) {
    const s = spec(inst);
    const sig = JSON.stringify(Object.entries(inst).filter(([k]) => !PLACEMENT.has(k))) + (s.ceiling ?? "");
    let m = meshes.get(inst.id);
    if (!m || m.sig !== sig) {
      if (m) itemsRoot.remove(m.group);
      const group = new THREE.Group();
      group.add(buildModel(s));
      group.traverse((o) => (o.userData.itemId = inst.id));
      const el = document.createElement("div");
      el.className = "lbl";
      el.textContent = s.name;
      const lb = new CSS2DObject(el);
      // above standing items; just under ceiling-hung ones (the group sits at the floor, the model hangs from s.ceiling)
      lb.position.y = s.ceiling != null ? zRange(s)[0] - 0.1 : s.h + 0.12;
      group.add(lb);
      m = { group, sig, label: lb };
      meshes.set(inst.id, m);
      itemsRoot.add(group);
    }
    m.group.position.copy(P3(s.x, s.y, s.z || 0));
    m.group.rotation.y = rad(s.rot || 0);
    // thin items against a wall (mirrors, pegboards) hide with that wall in the 3D cutaway
    const nw = s.d <= 0.1 ? nearestWall(s.x, s.y, WALLS) : null;
    m.wallIdx = nw && nw.dist < 0.15 ? WALLS.indexOf(nw.wall) : -1;
  }
}

const lineMat = (color, opacity = 1) => new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity, depthTest: false });
const polyLine = (poly, z, material) => {
  const l = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(poly.map(([x, y]) => P3(x, y, z))), material);
  l.renderOrder = 10;
  return l;
};
const polyFill = (poly, z, color, opacity) => {
  const shape = new THREE.Shape(poly.map(([x, y]) => new THREE.Vector2(x, y)));
  const m = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = z;
  return m;
};

function clearOverlay() {
  for (const o of [...overlayRoot.children]) {
    overlayRoot.remove(o);
    o.traverse((c) => {
      c.geometry?.dispose();
      if (c.isCSS2DObject) c.element.remove();
    });
  }
}

function drawOverlay() {
  clearOverlay();
  const bad = new Set(state.issues.filter((i) => i.level === "error").flatMap((i) => i.ids));
  const warned = new Set(state.issues.filter((i) => i.level === "warn").flatMap((i) => i.ids));
  for (const inst of state.layout.items) {
    const s = spec(inst);
    if (state.show.clearance && !s.floorLayer)
      for (const z of clearanceZones(s)) overlayRoot.add(polyFill(z.poly, 0.006, warned.has(s.id) ? "#e0a030" : "#4a90d9", 0.16));
    const sel = state.selected === s.id;
    if (sel || bad.has(s.id)) overlayRoot.add(polyLine(footprint(s), 0.01, lineMat(sel ? "#ff7a00" : "#e02020")));
  }
  const sel = state.selected && findItem(state.selected);
  if (sel) drawDimensions(spec(sel));
  for (const [id, m] of meshes) {
    m.label.visible = state.show.labels && (state.view === "plan" || id === state.selected);
    m.label.element.classList.toggle("lbl-bad", bad.has(id));
  }
}

// Distances from the selected item's bounding box to the nearest wall / item in each direction.
function drawDimensions(s) {
  const [x0, y0, x1, y1] = bbox(footprint(s));
  const obstacles = state.layout.items.filter((i) => i.id !== s.id && !spec(i).floorLayer && spec(i).d > 0.1).map((i) => bbox(footprint(spec(i))));
  const rays = [
    { o: [x1, (y0 + y1) / 2], d: [1, 0] },
    { o: [x0, (y0 + y1) / 2], d: [-1, 0] },
    { o: [(x0 + x1) / 2, y1], d: [0, 1] },
    { o: [(x0 + x1) / 2, y0], d: [0, -1] },
  ];
  const m = lineMat("#ff7a00");
  for (const { o, d } of rays) {
    let best = Infinity;
    for (const w of WALLS) {
      // only walls perpendicular to the ray
      if (Math.abs(w.ux * d[0] + w.uy * d[1]) > 0.01) continue;
      const along = d[0] ? (w.a[0] - o[0]) * d[0] : (w.a[1] - o[1]) * d[1];
      const lo = d[0] ? Math.min(w.a[1], w.b[1]) : Math.min(w.a[0], w.b[0]);
      const hi = d[0] ? Math.max(w.a[1], w.b[1]) : Math.max(w.a[0], w.b[0]);
      const c = d[0] ? o[1] : o[0];
      if (along > -0.005 && c >= lo && c <= hi) best = Math.min(best, along);
    }
    for (const [bx0, by0, bx1, by1] of obstacles) {
      const c = d[0] ? o[1] : o[0], lo = d[0] ? by0 : bx0, hi = d[0] ? by1 : bx1;
      if (c < lo || c > hi) continue;
      const along = d[0] === 1 ? bx0 - o[0] : d[0] === -1 ? o[0] - bx1 : d[1] === 1 ? by0 - o[1] : o[1] - by1;
      if (along > -0.005) best = Math.min(best, along);
    }
    if (!isFinite(best) || best < 0.01) continue;
    const e = [o[0] + d[0] * best, o[1] + d[1] * best];
    const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints([P3(o[0], o[1], 0.02), P3(e[0], e[1], 0.02)]), m);
    l.renderOrder = 11;
    overlayRoot.add(l);
    const el = document.createElement("div");
    el.className = "lbl lbl-dim";
    el.textContent = fmtLen(best);
    const lb = new CSS2DObject(el);
    lb.position.copy(P3((o[0] + e[0]) / 2, (o[1] + e[1]) / 2, 0.03));
    overlayRoot.add(lb);
  }
}

const fmtLen = (m) => {
  const inches = m / 0.0254, ft = Math.floor(inches / 12), inch = Math.round(inches - ft * 12);
  return `${m.toFixed(2)} m · ${inch === 12 ? ft + 1 : ft}'${inch === 12 ? 0 : inch}"`;
};

// ---------- edits, history ----------
const snapshot = () => JSON.stringify(state.layout.items);
function commit(before) {
  if (before === snapshot()) return;
  state.undo.push(before);
  if (state.undo.length > 200) state.undo.shift();
  state.redo = [];
  setDirty(true);
  refresh();
}
function undo() {
  if (!state.undo.length) return;
  state.redo.push(snapshot());
  state.layout.items = JSON.parse(state.undo.pop());
  if (!findItem(state.selected)) state.selected = null;
  setDirty(true);
  refresh();
}
function redo() {
  if (!state.redo.length) return;
  state.undo.push(snapshot());
  state.layout.items = JSON.parse(state.redo.pop());
  if (!findItem(state.selected)) state.selected = null;
  setDirty(true);
  refresh();
}
function setDirty(d) {
  state.dirty = d;
  $("#dirty").textContent = d ? "● unsaved" : "";
}
function refresh() {
  syncItems();
  state.issues = checkLayout(state.layout.items.map(spec), room);
  drawOverlay();
  renderItemList();
  renderProps();
  renderIssues();
}

function uid(type) {
  let i = 1;
  while (findItem(`${type}-${i}`)) i++;
  return `${type}-${i}`;
}

function addItem(type) {
  const before = snapshot();
  const c = catalog[type];
  const inst = { id: uid(type), type, x: +ROOM_C.x.toFixed(2), y: +ROOM_C.y.toFixed(2), rot: 0 };
  if (c.mount === "wall") Object.assign(inst, wallSnap({ ...c, ...inst }, inst.x, ROOM_C.y + 10));
  state.layout.items.push(inst);
  state.selected = inst.id;
  commit(before);
}

function mutateSelected(fn) {
  const it = findItem(state.selected);
  if (!it) return;
  const before = snapshot();
  fn(it);
  commit(before);
}

// ---------- snapping ----------
const r2 = (v) => Math.round(v * 100) / 100;

function wallSnap(s, x, y) {
  const nw = nearestWall(x, y, WALLS);
  const w = nw.wall;
  const t = Math.max(s.w / 2, Math.min(w.len - s.w / 2, nw.t));
  return {
    x: r2(w.a[0] + w.ux * t + w.nx * (s.d / 2)),
    y: r2(w.a[1] + w.uy * t + w.ny * (s.d / 2)),
    rot: rotFacing(w.nx, w.ny),
  };
}

// Make bounding-box edges flush with nearby axis-aligned walls (diagonal walls, e.g. a bay, don't snap).
function floorSnap(s, x, y, free) {
  if (!free) { x = Math.round(x / 0.05) * 0.05; y = Math.round(y / 0.05) * 0.05; }
  const [bx0, by0, bx1, by1] = bbox(footprint({ ...s, x, y }));
  const TH = 0.12;
  let dx = 0, dy = 0, bestX = TH, bestY = TH;
  for (const w of WALLS) {
    if (Math.abs(w.ux) > 0.01 && Math.abs(w.uy) > 0.01) continue;
    if (Math.abs(w.ux) < 0.01) {
      // vertical wall at x = w.a[0], spanning y
      const lo = Math.min(w.a[1], w.b[1]), hi = Math.max(w.a[1], w.b[1]);
      if (by1 <= lo || by0 >= hi) continue;
      const edge = w.nx > 0 ? bx0 : bx1;
      if (Math.abs(w.a[0] - edge) < bestX) { bestX = Math.abs(w.a[0] - edge); dx = w.a[0] - edge; }
    } else {
      const lo = Math.min(w.a[0], w.b[0]), hi = Math.max(w.a[0], w.b[0]);
      if (bx1 <= lo || bx0 >= hi) continue;
      const edge = w.ny > 0 ? by0 : by1;
      if (Math.abs(w.a[1] - edge) < bestY) { bestY = Math.abs(w.a[1] - edge); dy = w.a[1] - edge; }
    }
  }
  return { x: r2(x + dx), y: r2(y + dy) };
}

// ---------- pointer interaction ----------
const ray = new THREE.Raycaster();
const floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
let drag = null;

function pointer(e) {
  const r = renderer.domElement.getBoundingClientRect();
  return new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
}
function floorPoint(e) {
  ray.setFromCamera(pointer(e), camera());
  const p = new THREE.Vector3();
  return ray.ray.intersectPlane(floorPlane, p) ? [p.x, -p.z] : null;
}

renderer.domElement.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  ray.setFromCamera(pointer(e), camera());
  const hit = ray.intersectObjects(itemsRoot.children, true)[0];
  const id = hit?.object.userData.itemId;
  if (!id) {
    drag = { pending: true, x: e.clientX, y: e.clientY };
    return;
  }
  state.selected = id;
  const it = findItem(id), fp = floorPoint(e);
  drag = { id, before: snapshot(), off: fp ? [it.x - fp[0], it.y - fp[1]] : [0, 0], moved: false };
  controls().enabled = false;
  refresh();
});

renderer.domElement.addEventListener("pointermove", (e) => {
  const fp = floorPoint(e);
  if (fp) $("#cursor").textContent = `x ${fp[0].toFixed(2)}  y ${fp[1].toFixed(2)}`;
  if (!drag?.id || !fp) return;
  const it = findItem(drag.id), s = spec(it);
  const nx = fp[0] + drag.off[0], ny = fp[1] + drag.off[1];
  Object.assign(it, s.mount === "wall" ? wallSnap(s, nx, ny) : floorSnap(s, nx, ny, e.altKey));
  drag.moved = true;
  syncItems();
  state.issues = checkLayout(state.layout.items.map(spec), room);
  drawOverlay();
  renderProps();
});

window.addEventListener("pointerup", (e) => {
  if (drag?.id) {
    controls().enabled = true;
    if (drag.moved) commit(drag.before);
    else refresh();
  } else if (drag?.pending && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 4 && e.target === renderer.domElement) {
    state.selected = null;
    refresh();
  }
  drag = null;
});

window.addEventListener("keydown", (e) => {
  if (e.target.matches("input, select, textarea")) return;
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
  if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); duplicate(); return; }
  if (mod || e.altKey) return; // leave browser shortcuts (Cmd+R reload, ...) alone
  if (e.key === "v") return setView(state.view === "3d" ? "plan" : "3d");
  if (e.key === "Escape") { state.selected = null; return refresh(); }
  if (!state.selected) return;
  const step = e.shiftKey ? 0.1 : 0.01;
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
  if (moves[e.key]) {
    e.preventDefault();
    mutateSelected((it) => { it.x = r2(it.x + moves[e.key][0]); it.y = r2(it.y + moves[e.key][1]); });
  } else if (e.key === "r" || e.key === "R") rotate(e.shiftKey ? -90 : 90);
  else if (e.key === "[") rotate(15);
  else if (e.key === "]") rotate(-15);
  else if (e.key === "Delete" || e.key === "Backspace") removeSelected();
});

function rotate(deg) {
  mutateSelected((it) => {
    it.rot = (((it.rot || 0) + deg) % 360 + 360) % 360;
    const s = spec(it);
    if (s.mount === "wall") Object.assign(it, wallSnap(s, it.x, it.y));
  });
}
function duplicate() {
  const it = findItem(state.selected);
  if (!it) return;
  const before = snapshot();
  const copy = { ...structuredClone(it), id: uid(it.type), x: r2(it.x + 0.3), y: r2(it.y - 0.3) };
  if (copy.label) copy.label += " (copy)";
  state.layout.items.push(copy);
  state.selected = copy.id;
  commit(before);
}
function removeSelected() {
  const before = snapshot();
  state.layout.items = state.layout.items.filter((i) => i.id !== state.selected);
  state.selected = null;
  commit(before);
}

// ---------- views ----------
function setView(v) {
  state.view = v;
  ctl3d.enabled = v === "3d";
  ctlPlan.enabled = v === "plan";
  sun.castShadow = v === "3d"; // top-down shadows just smear across the plan
  document.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  applyToggles();
}
function applyToggles() {
  shell.ceiling.visible = state.show.ceiling && state.view === "3d";
  shell.ceilingMap.visible = state.show.ceiling && state.view === "plan";
  shell.grid.visible = state.show.grid;
  updateScan();
  drawOverlay();
}

// ---------- sidebar UI ----------
function renderItemList() {
  const bad = new Set(state.issues.filter((i) => i.level === "error").flatMap((i) => i.ids));
  const warn = new Set(state.issues.filter((i) => i.level === "warn").flatMap((i) => i.ids));
  $("#items").innerHTML = "";
  for (const inst of state.layout.items) {
    const s = spec(inst);
    const li = document.createElement("li");
    li.className = (state.selected === inst.id ? "sel " : "") + (bad.has(inst.id) ? "bad" : warn.has(inst.id) ? "warn" : "");
    li.innerHTML = `<span class="dot"></span><span>${esc(s.name)}</span><small>${s.w.toFixed(2)}×${s.d.toFixed(2)}</small>`;
    li.onclick = () => { state.selected = inst.id; refresh(); };
    $("#items").appendChild(li);
  }
}

const PROP_FIELDS = [
  ["label", "Label", "text"],
  ["x", "x (m)", "number"], ["y", "y (m)", "number"], ["rot", "Rotation°", "number"],
  ["w", "Width", "number"], ["d", "Depth", "number"], ["h", "Height", "number"], ["z", "Height off floor", "number"],
  ["color", "Color", "color"],
];
function renderProps() {
  const it = findItem(state.selected);
  const box = $("#props");
  if (!it) { box.innerHTML = `<p class="muted">Click an item to edit it.</p>`; return; }
  const s = spec(it);
  if (box.dataset.id === it.id && box.contains(document.activeElement)) {
    // keep the field being typed in; just update position readouts
    for (const k of ["x", "y", "rot"]) { const el = box.querySelector(`[name=${k}]`); if (el !== document.activeElement) el.value = s[k]; }
    return;
  }
  box.dataset.id = it.id;
  box.innerHTML = `<div class="prop-head"><b>${esc(s.name)}</b><span class="muted">${esc(catalog[it.type]?.name ?? it.type)}</span></div>
    ${s.notes ? `<p class="muted small">${esc(s.notes)}</p>` : ""}
    <div class="grid2">${PROP_FIELDS.filter(([k]) => k !== "z" || s.mount === "wall" || it.z != null)
      .map(([k, l, t]) => `<label>${l}<input name="${k}" type="${t}" step="0.01" value="${esc(s[k] ?? (t === "color" ? "#888888" : ""))}"></label>`).join("")}</div>
    <div class="row"><button data-act="rotl">⟲ 90°</button><button data-act="rotr">⟳ 90°</button><button data-act="dup">Duplicate</button><button data-act="del" class="danger">Delete</button></div>`;
  box.querySelectorAll("input").forEach((inp) =>
    inp.addEventListener("change", () => {
      mutateSelected((x) => {
        const k = inp.name;
        if (inp.type === "number") { const v = parseFloat(inp.value); if (!isNaN(v)) x[k] = k === "rot" ? ((v % 360) + 360) % 360 : v; }
        else if (inp.value.trim()) x[k] = inp.value;
        else delete x[k];
      });
    }));
  box.querySelector("[data-act=rotl]").onclick = () => rotate(90);
  box.querySelector("[data-act=rotr]").onclick = () => rotate(-90);
  box.querySelector("[data-act=dup]").onclick = duplicate;
  box.querySelector("[data-act=del]").onclick = removeSelected;
}

function renderIssues() {
  const ul = $("#issues");
  ul.innerHTML = state.issues.length ? "" : `<li class="ok">No problems found</li>`;
  const order = { error: 0, warn: 1, info: 2 };
  for (const is of [...state.issues].sort((a, b) => order[a.level] - order[b.level])) {
    const li = document.createElement("li");
    li.className = is.level;
    li.textContent = is.msg;
    if (is.ids.length) li.onclick = () => { state.selected = is.ids[0]; refresh(); };
    ul.appendChild(li);
  }
  $("#issue-count").textContent = state.issues.length ? `(${state.issues.length})` : "";
}

function renderCatalog() {
  const sel = $("#add-type");
  const cats = {};
  for (const [k, v] of Object.entries(catalog)) (cats[v.category] ??= []).push([k, v]);
  sel.innerHTML = Object.entries(cats)
    .map(([c, list]) => `<optgroup label="${esc(c)}">${list.map(([k, v]) => `<option value="${esc(k)}">${esc(v.name)} (${v.w}×${v.d})</option>`).join("")}</optgroup>`)
    .join("");
  $("#add-btn").onclick = () => addItem(sel.value);
}

// ---------- layouts ----------
async function listLayouts(selectSlug) {
  const list = await fetchJSON(`/api/rooms/${encodeURIComponent(ROOM_ID)}/layouts`);
  $("#layout").innerHTML = list.length
    ? list.map((l) => `<option value="${esc(l.slug)}">${esc(l.name)}</option>`).join("")
    : `<option value="">(new layout, not saved yet)</option>`;
  if (selectSlug) $("#layout").value = selectSlug;
  return list;
}
function setLayout(slug, data) {
  const { name, description, items, ...extra } = data;
  state.slug = slug;
  state.layout = { name: name ?? slug ?? "New layout", description: description ?? "", items: Array.isArray(items) ? items : [] };
  state.extra = extra;
  state.selected = null;
  state.undo = [];
  state.redo = [];
  setDirty(false);
  $("#layout").value = slug ?? "";
  $("#layout-desc").textContent = state.layout.description;
  history.replaceState(null, "", `${location.search}${slug ? "#" + slug : ""}`);
  refresh();
}
async function loadLayout(slug) {
  try {
    setLayout(slug, await fetchJSON(`${ROOM_BASE}layouts/${slug}.json`));
  } catch (e) {
    status(`Couldn't load layout: ${e.message}`);
  }
}
// overwrite: true for saving the open layout in place; Save as… asks before replacing another layout.
async function putLayout(slug, overwrite) {
  const body = JSON.stringify({ ...state.extra, ...state.layout });
  const url = `/api/rooms/${encodeURIComponent(ROOM_ID)}/layouts/${slug}${overwrite ? "?overwrite=1" : ""}`;
  const res = await fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body });
  if (res.status === 409 && !overwrite) {
    if (!confirm(`A layout called "${slug}" already exists. Replace it?`)) return false;
    return putLayout(slug, true);
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    status(`Save failed: ${err.error}`);
    return false;
  }
  setDirty(false);
  status(`Saved rooms/${ROOM_ID}/layouts/${slug}.json`);
  return true;
}
async function save() {
  if (!state.slug || state.slug === "as-scanned") return saveAs();
  await putLayout(state.slug, true);
}
async function saveAs() {
  const name = prompt("Layout name", !state.slug || state.slug === "as-scanned" ? "My layout" : state.layout.name);
  if (!name) return;
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "layout";
  const prevName = state.layout.name;
  state.layout.name = name;
  if (await putLayout(slug, slug === state.slug)) {
    state.slug = slug;
    await listLayouts(slug);
    history.replaceState(null, "", `${location.search}#${slug}`);
  } else state.layout.name = prevName;
}

var statusTimer; // var: status() can run before this line during start-up awaits
function status(msg) {
  $("#status").textContent = msg;
  clearTimeout(statusTimer);
  if (msg) statusTimer = setTimeout(() => ($("#status").textContent = ""), 4000);
}

// ---------- wire up ----------
$("#layout").onchange = (e) => {
  if (state.dirty && !confirm("Discard unsaved changes?")) { e.target.value = state.slug ?? ""; return; }
  if (e.target.value) loadLayout(e.target.value);
};
$("#save").onclick = save;
$("#save-as").onclick = saveAs;
$("#undo").onclick = undo;
$("#redo").onclick = redo;
document.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => setView(b.dataset.view)));
for (const k of Object.keys(state.show)) {
  const el = $(`#show-${k}`);
  el.checked = state.show[k];
  el.onchange = () => { state.show[k] = el.checked; applyToggles(); };
}
$("#scan-opacity").oninput = (e) => { state.scanOpacity = +e.target.value; updateScan(); };
window.addEventListener("beforeunload", (e) => { if (state.dirty) e.preventDefault(); });

renderCatalog();
const layouts = await listLayouts();
const initial = location.hash.slice(1);
// e.g. ?view=plan&ceiling=1&scan=1&labels=0 — handy for screenshots
for (const k of Object.keys(state.show)) if (params.has(k)) $(`#show-${k}`).checked = state.show[k] = params.get(k) !== "0";
if (layouts.length) await loadLayout(layouts.some((l) => l.slug === initial) ? initial : layouts.some((l) => l.slug === "as-scanned") ? "as-scanned" : layouts[0].slug);
else setLayout(null, { name: "New layout", description: "No layouts yet: add items and Save to create one.", items: [] });
if (room._warnings.length) status(`room.json: ${room._warnings.join("; ")}`);
setView(params.get("view") === "plan" ? "plan" : "3d");

renderer.setAnimationLoop(() => {
  controls().update();
  if (state.view === "3d") {
    // dollhouse cutaway: drop walls between the camera and the room
    for (const g of shell.wallGroups) {
      const toCam = persp.position.clone().sub(g.userData.center);
      g.scale.y = toCam.dot(g.userData.outward) > 0 ? 0.06 : 1;
    }
  } else for (const g of shell.wallGroups) g.scale.y = 1;
  for (const m of meshes.values()) m.group.visible = m.wallIdx < 0 || shell.wallGroups[m.wallIdx].scale.y === 1;
  renderer.render(scene, camera());
  labelRenderer.render(scene, camera());
});
