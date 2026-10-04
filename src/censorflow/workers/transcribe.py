"""Read the vocal stem into timed words, in its own process.

    python -m censorflow.workers.transcribe <vocals.wav>

The result data is `{"words": [Word...], "seconds": float}`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from . import base

STAGE = "transcribing"


def _transcribe(argv: list[str]) -> dict[str, Any]:
    # Imported inside the stage so the Apple-only dependencies load after stdout has been
    # claimed, and only in the process that actually needs them.
    from ..asr import make_transcriber

    if not argv:
        raise SystemExit("usage: transcribe <vocals.wav>")
    vocal_path = Path(argv[0]).resolve()
    if not vocal_path.is_file():
        raise FileNotFoundError(f"no such vocal stem: {vocal_path}")

    base.progress(5.0, "loading the speech recognition model", STAGE)
    transcriber = make_transcriber()
    started = time.perf_counter()
    words = transcriber.transcribe(vocal_path, _on_progress)
    elapsed = time.perf_counter() - started
    base.progress(100.0, f"read {len(words)} words in {elapsed:.1f}s", STAGE)
    return {"words": [word.to_dict() for word in words], "seconds": elapsed}


def _on_progress(pct: float, msg: str) -> None:
    base.progress(pct, msg, STAGE)


if __name__ == "__main__":
    base.run(STAGE, lambda: _transcribe(sys.argv[1:]))