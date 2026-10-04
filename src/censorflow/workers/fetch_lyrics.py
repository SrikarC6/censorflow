"""Lyrics lookup stage: `python -m censorflow.workers.fetch_lyrics <source> <out.json>`.

Metadata tags plus the filename are read, LRCLIB is queried, and whatever timed lines come
back are written to `out.json` as `lyrics.json`. The merge with the ASR transcript is not
done here: only the parent holds the word list, so `pipeline.py` does the merge.

Useful on its own for checking a lookup without running a whole job:

    uv run python -m censorflow.workers.fetch_lyrics samples/foo.m4a /tmp/lyrics.json
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from ..lyrics import lookup_to_payload
from .base import run

logger = logging.getLogger(__name__)


def stage(source: Path, out_path: Path) -> dict[str, object]:
    payload = lookup_to_payload(source)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: fetch_lyrics <audio-file> <out.json>", file=sys.stderr)
        return 2
    run("lyrics", lambda: stage(Path(argv[0]).expanduser(), Path(argv[1]).expanduser()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))