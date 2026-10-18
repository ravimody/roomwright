"""Imported by every Blender tool just before `import bpy`.

bpy 4.5 crashes (SIGSEGV) on import inside Codex's macOS sandbox: Blender probes the Metal GPU while it starts, the
sandbox hides the device name, and Blender reads a null pointer. Exit with a clear message instead, so the agent knows
to rerun the command outside the sandbox (approve it, or give the project full access). ROOMWRIGHT_SANDBOX_OK=1 skips it.
"""

import os
import sys

if sys.platform == "darwin" and os.environ.get("CODEX_SANDBOX") == "seatbelt" and not os.environ.get("ROOMWRIGHT_SANDBOX_OK"):
    sys.exit(f"{os.path.basename(sys.argv[0])}: Blender (bpy) crashes inside Codex's macOS sandbox. Rerun this command outside the "
             "sandbox (request escalated permissions / approve it), or run Codex with --sandbox danger-full-access for this "
             "project. See docs/AGENT_SETUP.md in the engine docs.")
