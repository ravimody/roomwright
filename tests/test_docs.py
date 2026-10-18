"""Generated reference docs match the code and schemas (regenerate with `uv run tools/make_docs.py`)."""

import subprocess
import sys

from conftest import REPO


def test_generated_docs_are_current():
    r = subprocess.run([sys.executable, str(REPO / "tools/make_docs.py"), "--check"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def test_household_details_stay_out_of_engine_docs():
    """Engine docs ship in the public package; household specifics live in HOUSEHOLD.md and rooms/."""
    import re

    import pytest

    lst = REPO / "scripts/privacy_denylist.txt"  # kept in the private repo only
    if not lst.exists():
        pytest.skip("no denylist here")
    deny = re.compile("|".join(x for x in lst.read_text().splitlines() if x.strip() and not x.startswith("#")), re.I)
    for p in [*(REPO / "docs").glob("*.md"), REPO / "COOKBOOK.md", REPO / "ARCHITECTURE.md", *(REPO / "scripts/public").iterdir()]:
        if p.name == "OPEN_SOURCE_PLAN.md" or not p.is_file():
            continue
        hits = [f"{p.name}:{i}" for i, line in enumerate(p.read_text().splitlines(), 1) if deny.search(line)]
        assert not hits, hits
