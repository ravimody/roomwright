# Agent setup

roomwright is plain command-line tools and plain files, so any coding agent can drive it. What an agent needs:

1. **Read `AGENTS.md`.** It is the one instructions file: the working rules plus the docs to read before room work. `roomwright init` writes it; there is no `CLAUDE.md` or `GEMINI.md` to keep in sync.
2. **Run shell commands that take minutes** (`new-room` and `geometry-check` take about a minute each; renders 10 s to a few minutes per view on a CPU).
3. **Write uv's cache** (`uv cache dir`), and reach the network the first time a tool runs (Python 3.11, `bpy` ~400 MB, numpy, trimesh). `uv run roomwright doctor --full` run once in a normal terminal fills the cache for the Blender tools; the measurement and layout tools fetch their own packages (trimesh, scipy, shapely, …) the first time each runs, so run each once with the network on before working offline.
4. **Run Blender.** On macOS, Blender can't start inside some agent sandboxes (below).
5. **Look at images.** The checks print numbers, but judging a render, a scan comparison or a photo match needs a model that can view PNG/JPG files. A model without vision can run every check; a person then has to look at the renders. A browser is optional (product research).

Run `uv run roomwright doctor` (add `--full` once) from inside the agent: it recognises Claude Code and Codex, and reports what the sandbox blocks (a read-only uv cache, no network, Blender crashing on start).

## Instructions: one `AGENTS.md`

Keep `AGENTS.md` under 24 KB (Antigravity truncates larger files; Codex reads 32 KiB in total) and put long material in the docs it points to. Its "read before working" list uses `@path` lines: Claude Code loads those files automatically, and other agents read the paths and open them. Don't put another `AGENTS.md` in a subfolder (agents that open a file there load it as that folder's rules); the engine's own conventions are synced as `.roomwright/ENGINE_AGENTS.md` for that reason.

| Agent | Reads `AGENTS.md` | Notes | Tested here |
|---|---|---|---|
| Claude Code | yes, since v2.1.277, when there is no `CLAUDE.md`; follows `@path` imports in it | A `CLAUDE.md` anywhere from the working folder up (or `CLAUDE.local.md`) makes it read that instead. Older versions: a one-line `CLAUDE.md` containing `@AGENTS.md`. | yes |
| Codex CLI | yes, from the repo root down to the working folder (32 KiB in total) | sandbox settings below | yes (0.157, macOS) |
| Antigravity | yes (workspace root and subfolders; 24,000 bytes per file) | its own include syntax is `@[label](path)`; it reads `@path` lines as plain paths | no |
| Gemini CLI | when configured | `roomwright init` writes `.gemini/settings.json` with `"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}` | no |
| Cursor, GitHub Copilot, Windsurf, Jules, Amp, opencode, Zed, Warp, goose, Junie, Roo, Kilo, Devin, Factory, Augment, … | yes, per [agents.md](https://agents.md/) | | no |
| Aider | when asked | `aider --read AGENTS.md --read HOUSEHOLD.md` | no |

Open-weight models (DeepSeek, Qwen, …) run inside one of these agents (opencode, Cline, Roo, or Claude Code and others through an Anthropic- or OpenAI-compatible API), so the agent decides what is read. Check that the model can view images (need 5).

Local models (untested): run a vision model with Ollama or LM Studio and drive it from opencode, Cline or Roo. Vision-capable open-weight families include Qwen-VL, Gemma 3 and Mistral Small; text-only ones (most DeepSeek and Llama coding models) can run the tools but can't judge renders. Expect smaller models to lose track in long, multi-step room work and to need a person to look at the pictures.

## Codex CLI

Tested with Codex 0.157 on macOS in its default `workspace-write` sandbox:

- **uv's cache is outside the workspace,** so every `uv run` fails with `Operation not permitted`. Allow it in `~/.codex/config.toml` (use the path `uv cache dir` prints):
  ```toml
  [sandbox_workspace_write]
  writable_roots = ["<the folder `uv cache dir` prints>"]
  # network_access = true   # only needed if you skip `roomwright doctor --full` outside the sandbox
  ```
- **Network is off,** so first runs that download packages fail. Run `uv run roomwright doctor --full` once in a normal terminal, or set `network_access = true` as above.
- **Blender crashes inside the macOS sandbox:** `bpy` 4.5 probes the Metal GPU when it starts, the sandbox hides the device, and Blender segfaults. The Blender tools (renders, scan views, geometry check, alignment, colour and light match, photo match, model import) stop with a message saying so instead (`tools/sandbox_guard.py`). Approve them to run outside the sandbox when Codex asks, or start Codex with `--sandbox danger-full-access` for your household repo. The measurement and layout tools (`validate-room`, `ceiling-compare`, `wall-profile`, `check-layout`, `flow-plan`, …) run inside the sandbox once the cache is writable. Codex on Linux uses a different sandbox; untested.
- Codex can view local images, so it can judge renders.

## Claude Code

Works as is. If you turn on Claude Code's own sandbox, expect the same limits as Codex (uv's cache, the network on first runs, Blender on macOS); allow the cache folder or run the render tools unsandboxed. Untested.
