"""Review edits: validating what the browser sends back, and turning it into flags.

Split out of `jobs.py` so both stay readable, and so the validation rules can be tested
without an HTTP client. `AGENTS.md` does not name this file; the split is recorded in
`docs/DECISIONS.md`.

The rule that shapes this module: the **user** decides what gets censored. The server
recomputes whether a word is profane (so the UI badge is honest) but it honours the
`censor` switch exactly as sent, because the user must be able to censor a word that is not
on the list and to un-censor one that is.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from . import audio_io
from .models import Flag
from .profanity import detect

if TYPE_CHECKING:
    from .jobs import Job

logger = logging.getLogger(__name__)


class JobError(RuntimeError):
    """A job failed, or the browser sent something unusable. The user needs to hear it."""


def apply_review(job: Job, payload: dict[str, Any]) -> list[Flag]:
    """Replace the job's flags with the reviewed ones, after validating every field.

    The `censor` switch is taken exactly as the client sent it. The user is the authority
    here: they must be able to censor a word that is not on the list, and to un-censor one
    that is. What the server recomputes is `profane`, which is reported back for the badge.
    """
    if job.result is None:
        raise JobError("this job has no transcript to review")
    raw_flags = payload.get("flags")
    if not isinstance(raw_flags, list):
        raise JobError("review payload must contain a list of flags")

    words = job.words
    updated: list[Flag] = []
    for entry in raw_flags:
        if not isinstance(entry, dict):
            raise JobError("each flag must be an object")
        index = _as_int(entry.get("word_index", -1), "word_index")
        text = str(entry.get("text", "")).strip()
        if not text:
            raise JobError("a flag needs a word")
        if words and not -1 <= index < len(words):
            raise JobError(f"word_index {index} is outside the transcript")
        start = _as_float(entry.get("start", 0.0), "start")
        end = _as_float(entry.get("end", 0.0), "end")
        if start < 0.0 or end <= start:
            raise JobError(f"flag {text!r} has an empty or negative time span")
        censor = entry.get("censor", True)
        if not isinstance(censor, bool):
            raise JobError("censor must be true or false")
        updated.append(
            Flag(
                word_index=index,
                text=text,
                start=start,
                end=end,
                source=str(entry.get("source", "asr")),
                confidence=float(entry.get("confidence", 0.0)),
                approx=bool(entry.get("approx", False)),
                censor=censor,
            )
        )
    updated.sort(key=lambda flag: (flag.start, flag.end))
    job.flags = updated
    job.result.flags = updated
    job.review = {"flags": [flag.to_dict() for flag in updated], "saved_at": time.time()}
    (job.directory / "review.json").write_text(
        json.dumps(job.review, indent=2), encoding="utf-8"
    )
    return updated


def censor_spans(job: Job) -> list[tuple[float, float]]:
    """The spans to mute, derived from the flags the user left switched on.

    Delegates to `PipelineResult.censor_spans` so the CLI and the server cannot disagree
    about ordering or de-duplication.
    """
    if job.result is not None:
        return job.result.censor_spans()
    return sorted(
        (flag.start, flag.end) for flag in job.flags if flag.censor and flag.end > flag.start
    )


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise JobError(f"{name} must be a whole number") from exc


def _as_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise JobError(f"{name} must be a number") from exc


def duration_of(job: Job) -> float:
    """Length of the audio this job actually processed, in seconds.

    Not the file's length: `--clip-seconds` means the job may hold less than the source.
    """
    try:
        return audio_io.duration_seconds(job.mix_path)
    except audio_io.AudioError:
        return 0.0


def payload(job: Job) -> dict[str, Any]:
    """The whole review screen's data: transcript, flags, and what the server thinks of them."""
    if job.result is None:
        return {"job": job.id, "state": str(job.state), "ready": False}
    profane, allowed = detect.wordlists()
    return {
        "job": job.id,
        "state": str(job.state),
        "ready": True,
        "track": job.track.to_dict(),
        "duration": duration_of(job),
        "words": [word.to_dict() for word in job.words],
        "flags": [flag_payload(flag, profane, allowed) for flag in job.flags],
        "lyrics_found": bool(job.result.lyric_lines),
        "lyric_lines": len(job.result.lyric_lines),
    }


def flag_payload(flag: Flag, profane: frozenset[str], allowed: frozenset[str]) -> dict[str, Any]:
    """A flag plus the verdict the review screen shows.

    `profane` is recomputed from the word text on every read, so editing a word's text in
    the UI immediately changes what the server thinks of it without a second request.
    """
    payload = flag.to_dict()
    payload["profane"] = detect.is_profane(flag.text, profane, allowed)
    return payload
