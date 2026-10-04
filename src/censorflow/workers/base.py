"""One-shot subprocess workers and the JSON-line protocol they speak.

A worker's stdout carries the protocol and nothing else:

    {"event":"progress","stage":"separating","pct":42.0,"msg":"..."}
    {"event":"result","data":{...}}
    {"event":"error","message":"..."}

Every model library also logs, and some of them print. So the first thing a worker does is
`claim_stdout`, which parks the real stdout handle and points `sys.stdout` at stderr, where
logging is already going. After that the only thing that can reach stdout is `emit`, and the
parent can trust every line it reads.

Entry points are `python -m censorflow.workers.<stage>`, one file per stage.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from collections.abc import Callable
from typing import Any, TextIO

__all__ = ["claim_stdout", "emit", "progress", "run"]

_logger = logging.getLogger("censorflow.worker")
_protocol_stream: TextIO | None = None


def claim_stdout() -> None:
    """Reserve stdout for the protocol; route logging and stray prints to stderr.

    Called by `run`, so workers never need to remember it.
    """
    global _protocol_stream
    _protocol_stream = sys.stdout
    sys.stdout = sys.stderr  # type: ignore[assignment]
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def emit(event: str, **fields: Any) -> None:
    """Write one protocol object as a single line, flushing immediately."""
    stream = _protocol_stream if _protocol_stream is not None else sys.stdout
    stream.write(json.dumps({"event": event, **fields}) + "\n")
    stream.flush()


def progress(pct: float, msg: str, stage: str = "") -> None:
    """Tell the parent how far along this stage is. `pct` is 0-100."""
    emit("progress", stage=stage, pct=round(float(pct), 2), msg=msg)


def run(stage: str, fn: Callable[[], dict[str, Any]]) -> None:
    """Run `fn`, emitting exactly one result or error line, then exit.

    Exit code 0 with a `result` line is success; anything else is a failure the parent
    turns into a user-facing message. The traceback goes to stderr, i.e. the stage log.
    """
    claim_stdout()
    try:
        data = fn()
    except Exception as exc:
        _logger.exception("stage %s failed", stage)
        traceback.print_exc(file=sys.stderr)
        emit("error", stage=stage, message=f"{type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc
    emit("result", stage=stage, data=data)
    raise SystemExit(0)