"""Split the mix into stems, in its own process.

    python -m censorflow.workers.separate <mix.wav> <out_dir> [stems] [quality]

`stems` is a comma-separated list, defaulting to `config.STEMS_CENSOR`. The result data is
`{"stems": {name: path}, "seconds": float}`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from .. import config
from . import base

STAGE = "separating"


def _separate(argv: list[str]) -> dict[str, Any]:
    # Imported inside the stage so the Apple-only dependencies load after stdout has been
    # claimed, and only in the process that actually needs them.
    from ..separation import make_separator

    if len(argv) < 2:
        raise SystemExit("usage: separate <mix.wav> <out_dir> [stems] [quality]")
    mix_path = Path(argv[0]).resolve()
    out_dir = Path(argv[1]).resolve()
    stems = tuple(argv[2].split(",")) if len(argv) > 2 and argv[2] else config.STEMS_CENSOR
    quality = argv[3] if len(argv) > 3 and argv[3] else config.DEFAULT_QUALITY
    if not mix_path.is_file():
        raise FileNotFoundError(f"no such mix file: {mix_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    base.progress(2.0, "loading the separation model", STAGE)
    separator = make_separator(quality=quality, output_dir=out_dir)
    started = time.perf_counter()
    written = separator.separate(mix_path, stems, _on_progress)
    elapsed = time.perf_counter() - started
    base.progress(100.0, f"separated in {elapsed:.1f}s", STAGE)
    return {"stems": {name: str(path) for name, path in written.items()}, "seconds": elapsed}


def _on_progress(pct: float, msg: str) -> None:
    base.progress(pct, msg, STAGE)


if __name__ == "__main__":
    base.run(STAGE, lambda: _separate(sys.argv[1:]))