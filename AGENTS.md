# Agent instructions (roomwright engine)

These apply to agents working **on the engine** (this repo) and, through `.roomwright/ENGINE_AGENTS.md`, to agents working on a household's rooms with it. This is the one instructions file for every coding agent (Claude Code, Codex, Antigravity, Cursor, Gemini CLI, …); keep it under 24 KB.

## Read before working
Agents that follow `@path` imports (Claude Code) load these automatically; every other agent: read them first.
- @ARCHITECTURE.md — how the engine works and why
- @COOKBOOK.md — the pipeline step by step, and best practices
- On demand: `docs/QUICKSTART.md`, `docs/DESIGN_GUIDE.md`, `docs/MODELING.md`, `docs/TOOLS.md`, `docs/DATA.md`, `docs/AGENT_SETUP.md` (agent sandboxes), `docs/PERSONAS.md` (who the docs must work for)

## Principles
- **Engine and lessons are generic; a household and its rooms are data.** Code in `tools/`, `editor/` and `server.py` never names a room (a test enforces it). Room geometry, materials, lights, cameras, scenes, furniture and flow paths live in `rooms/<room>/`; household preferences in `HOUSEHOLD.md`.
- **Measure, then verify.** At standard and verified depth ([COOKBOOK](COOKBOOK.md#how-much-to-do)), when a room has a scan, run `geometry-check <layout>` after any geometry or layout change and fix or explain every `CHECK` item before showing renders; measure fixes from the scan (height maps, `wall-profile`), never by eye. Without a scan, or on a quick pass, say what wasn't verified.
- **Choices, not one answer.** Give a recommendation with reasons and as many rendered alternatives as the person wants; adopt the person's edits as the new baseline.
- Read the room's `style` and `sourcing` before proposing anything. Design advice comes from `docs/DESIGN_GUIDE.md`: guidance to explain and offer, never rules; `HOUSEHOLD.md` and the room's style override it, and options include at least one beyond the safe default.
- Product sizes come from spec sheets; check depth and height against soffits, keep-clear zones and door swings.

## Working on the engine
- Every change goes on a branch and through a pull request; one topic per PR. CI runs ruff, the test suite and `validate_room --all` on the sample household (`examples/`).
- No furniture library in the engine: items are `box`, `parts` or `glb` catalog data (docs/MODELING.md), or a household's own builders (`builders/<name>.py` + `.js`, a pair per builder; `tests/test_engine.py::test_builder_parity`). The engine keeps only the modelling kit (`tools/blender_models.py`, `editor/src/kit.js`); a new core model goes in both in the same PR. JS `x, y, z` = Python `x, z, -y`.
- New data key: add it to `schema/*.schema.json`, then run `uv run tools/make_docs.py` (`docs/DATA.md` and `docs/TOOLS.md` are generated; never edit them by hand).
- Docs changes (COOKBOOK, the design guide, QUICKSTART, MODELING, the README, the household template): read them as each person in `docs/PERSONAS.md`; nothing may assume one country, culture, taste, budget, device, skill level or amount of time.
- New tool: a PEP 723 header with its dependencies, a docstring with a `uv run ../../tools/<tool>.py …` usage line, outputs under the room's `renders/`, `roomframe.font()` for labels and `roomframe.show()` to open results.
- Renders: lights in real units from data (an `ASSUMED:` line means ask for the bulb or fit it with `light-match`), white balance on, no fake fill lights or ambient boosts, quick tests at `--samples 16`. Check a change that should not alter renders with a pixel diff of a few reference views.

## Working on a household's rooms
- Run tools from inside `rooms/<room>/` (`roomwright <tool> …`).
- Talk and write reports in the household's language and units, and deliver the way `HOUSEHOLD.md` says (images in chat, a PDF, a phone-friendly page, a local HTML report).
- Put lessons that apply to any room in the engine's `COOKBOOK.md`: open an issue or a PR upstream, only with the person's agreement and with household details removed. Write them as best practice (no specific rooms, households, products or dates). Household preferences go in `HOUSEHOLD.md`, room decisions in the room's README.
