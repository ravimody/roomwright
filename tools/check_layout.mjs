// Run the editor's layout checks from the command line (same rules and fallbacks as the editor).
// Usage, from inside rooms/<room>/:  node ../../tools/check_layout.mjs layouts/<name>.json [...more]
// Prints every issue with the item ids involved; exits 1 if any layout has an error (warnings don't fail).
import { existsSync, readFileSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { checkLayout, makeSpec, normalizeRoom } from "../editor/src/geom.js";

const ROOM = process.env.ROOM || ".";
const roomFile = resolve(ROOM, "room.json");
if (!existsSync(roomFile)) {
  console.error(`no room.json in ${resolve(ROOM)}: run from inside rooms/<room>/ (or set ROOM=)`);
  process.exit(2);
}
const room = normalizeRoom(JSON.parse(readFileSync(roomFile)));
// catalogs: the engine's shared entries, then the household's (the folder holding rooms/), then the room's; later wins
const roomDir = resolve(ROOM);
const household = basename(dirname(roomDir)) === "rooms" ? dirname(dirname(roomDir)) : null;
const readItems = (f) => (f && existsSync(f) ? JSON.parse(readFileSync(f)).items : {});
const catalog = {
  ...JSON.parse(readFileSync(new URL("../shared/catalog.json", import.meta.url))).items,
  ...readItems(household && resolve(household, "catalog.json")),
  ...readItems(resolve(roomDir, "catalog.json")),
};
if (process.argv.length < 3) {
  console.error("usage: node ../../tools/check_layout.mjs layouts/<name>.json [...more]");
  process.exit(2);
}
let failed = false;
for (const file of process.argv.slice(2)) {
  let layout;
  try {
    layout = JSON.parse(readFileSync(file));
  } catch (e) {
    console.log(`\n${file}: cannot read (${e.message})`);
    failed = true;
    continue;
  }
  const issues = [];
  if (!Array.isArray(layout.items)) issues.push({ level: "warn", ids: [], msg: "layout has no items list" });
  const items = (layout.items ?? []).map((i) => makeSpec(catalog, i, room));
  issues.push(...checkLayout(items, room));
  console.log(`\n${layout.name ?? file} (${file}): ${issues.length ? issues.length + " issue(s)" : "clean"}`);
  for (const is of issues) console.log(`  ${is.level.padEnd(5)} ${is.msg}${is.ids.length ? `  [${is.ids.join(", ")}]` : ""}`);
  failed ||= issues.some((i) => i.level === "error");
}
process.exit(failed ? 1 : 0);
