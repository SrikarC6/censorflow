"""Run every heavy stage as a one-shot subprocess on this machine.

Why a subprocess at all: the previous version ran Whisper inside a UI worker thread and
died in tqdm's multiprocessing lock with `bad value(s) in fds_to_keep`. Keeping every
model in its own short-lived process fixes that and also frees memory between stages,
which matters on a fanless 16 GB laptop. Only one stage is ever in flight.

Workers speak one JSON object per line on stdout and nothing else; their stderr, which
carries every library's logging, goes to `logs/<job>/<stage>.log`. `LocalBackend` is the
only implementation of `ComputeBackend` today.
"""

from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .. import config
from ..models import ProgressFn, Word
from .base import ComputeError

logger = logging.getLogger(__name__)

# Worker stdout lines that are not protocol messages. Kept only so a failure can quote them.
_MAX_QUOTED_NOISE = 5


class LocalBackend:
    """Run the ML stages as subprocesses of this interpreter."""

    def __init__(self, job_dir: Path) -> None:
        self.job_dir = Path(job_dir)

    def separate(
        self,
        audio_path: Path,
        stems: Sequence[str] = config.STEMS_CENSOR,
        quality: str = config.DEFAULT_QUALITY,
        on_progress: ProgressFn | None = None,
    ) -> dict[str, Path]:
        argv = [
            str(audio_path),
            str(self.job_dir),
            ",".join(stems),
            quality,
        ]
        data = self._run("separate", argv, on_progress)
        raw = data.get("stems")
        if not isinstance(raw, dict) or not raw:
            raise ComputeError("The separation stage finished but produced no stems.")
        return {str(name): Path(str(path)) for name, path in raw.items()}

    def transcribe(
        self, vocal_path: Path, on_progress: ProgressFn | None = None
    ) -> list[Word]:
        data = self._run("transcribe", [str(vocal_path)], on_progress)
        raw = data.get("words")
        if not isinstance(raw, list):
            raise ComputeError("The transcription stage returned no word list.")
        try:
            return [Word(**item) for item in raw]
        except TypeError as exc:
            raise ComputeError(f"The transcription stage returned malformed words: {exc}") from exc

    # -- process plumbing ---------------------------------------------------------

    def log_path(self, stage: str) -> Path:
        return config.LOG_DIR / self.job_dir.name / f"{stage}.log"

    def _run(self, stage: str, argv: list[str], on_progress: ProgressFn | None) -> dict[str, Any]:
        cmd = [sys.executable, "-m", f"censorflow.workers.{stage}", *argv]
        log_path = self.log_path(stage)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        logger.info("stage %s: %s", stage, " ".join(cmd))
        started = time.perf_counter()
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                bufsize=1,
                env=env,
            )
            try:
                data, noise = self._pump(proc, stage, on_progress)
            except ComputeError:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                raise
            code = proc.wait()

        elapsed = time.perf_counter() - started
        logger.info("stage %s exited %d after %.1fs (log: %s)", stage, code, elapsed, log_path)
        if code != 0 and data is None:
            detail = f" The stage said: {noise[-1]}" if noise else ""
            raise ComputeError(
                f"The {stage} stage failed (exit {code}).{detail} Full details in {log_path}."
            )
        if data is None:
            raise ComputeError(
                f"The {stage} stage produced no result (exit {code}). "
                f"Full details in {log_path}."
            )
        return data

    def _pump(
        self,
        proc: subprocess.Popen[str],
        stage: str,
        on_progress: ProgressFn | None,
        timeout_s: float = config.WORKER_TIMEOUT_S,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """Read protocol lines until EOF, forwarding progress to the caller.

        `readline` would wait forever on a hung worker. The stage is allowed
        `timeout_s` of wall time, then it is killed so the server can move on.
        """
        data: dict[str, Any] | None = None
        noise: list[str] = []
        assert proc.stdout is not None
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait(timeout=5)
                raise ComputeError(
                    f"The {stage} stage timed out after {timeout_s:.0f}s and was stopped. "
                    f"Full details in {self.log_path(stage)}."
                )
            ready, _, _ = select.select([proc.stdout], [], [], min(1.0, remaining))
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            raw = proc.stdout.readline()
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # A worker library printing to stdout. Tolerated, but worth quoting if
                # the stage then fails.
                noise.append(line[:200])
                continue
            if not isinstance(message, dict):
                noise.append(line[:200])
                continue
            kind = message.get("event")
            if kind == "progress":
                if on_progress is not None:
                    on_progress(float(message.get("pct", 0.0)), str(message.get("msg", "")))
            elif kind == "result":
                payload = message.get("data")
                data = payload if isinstance(payload, dict) else {}
            elif kind == "error":
                raise ComputeError(
                    f"The {stage} stage failed: {message.get('message', 'unknown error')}. "
                    f"Full details in {self.log_path(stage)}."
                )
            else:
                noise.append(line[:200])
        return data, noise[-_MAX_QUOTED_NOISE:]