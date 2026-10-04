"""Worker subprocesses must not be able to hang the server."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from censorflow import config
from censorflow.compute.base import ComputeError
from censorflow.compute.local import LocalBackend
from censorflow.compute.remote import RemoteBackend


def test_a_hung_worker_is_stopped(tmp_path: Path) -> None:
    backend = LocalBackend(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        with pytest.raises(ComputeError, match="timed out"):
            backend._pump(proc, "separate", None, timeout_s=0.3)
        assert proc.wait(timeout=5) is not None or proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_cloud_compute_is_not_implemented(tmp_path: Path) -> None:
    backend = RemoteBackend()
    with pytest.raises(NotImplementedError, match="not implemented"):
        backend.separate(tmp_path / "mix.wav", ["vocals"], "fast")
    with pytest.raises(NotImplementedError, match="not implemented"):
        backend.transcribe(tmp_path / "vocals.wav")


def test_the_modules_the_app_runs_stay_near_three_hundred_lines() -> None:
    """AGENTS.md asks for roughly 300 lines. The text-heavy tests are not in this count."""
    offenders: list[str] = []
    for folder in ("src", "web"):
        for path in (config.PROJECT_DIR / folder).rglob("*"):
            if path.suffix not in {".py", ".js"} or not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            count = len(path.read_text(encoding="utf-8").splitlines())
            if count > 300:
                offenders.append(f"{path.relative_to(config.PROJECT_DIR)} ({count})")
    assert not offenders, offenders
