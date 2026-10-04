"""Run the flip-disc screens under node.

`tests/test_web_app.py` reads the scripts as text. This one executes them, which
is what caught a painter that redrew itself until the stack overflowed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "board.test.mjs"


def test_the_screens_run_under_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.fail("node is required to execute the flip-disc screens")
    completed = subprocess.run(
        [node, str(HARNESS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
