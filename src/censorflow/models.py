"""Shared record types crossing pipeline stage boundaries.

These are the two objects `AGENTS.md` names in the pipeline contract: `Word` from ASR
and `Flag` from profanity detection. Both are plain dataclasses so they serialise to
JSON for the job directory and the review endpoint without extra machinery.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field

# Flag provenance values, also used as review-screen source badges.
SOURCE_ASR = "asr"
SOURCE_LYRICS = "lyrics"
SOURCE_BOTH = "both"

# Progress callback shared by every heavy stage: (percent 0-100, message). It lives here
# so the separator, the ASR backend and the compute seam can all name the type without
# importing each other.
ProgressFn = Callable[[float, str], None]


@dataclass(frozen=True, slots=True)
class Word:
    """One recognised word. ASR is the source of truth for timing."""

    text: str
    start: float
    end: float
    confidence: float = 1.0
    source: str = SOURCE_ASR

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class Flag:
    """A word to censor, before and after user review.

    `word_index` indexes into the transcript's word list so a flag can always be traced
    back to the word it came from, including lyrics-only flags that have no ASR word.
    """

    word_index: int
    text: str
    start: float
    end: float
    source: str = SOURCE_ASR
    confidence: float = 1.0
    # True when timing is estimated rather than measured, e.g. a lyrics-only flag
    # positioned proportionally inside a lyric line. Shown as "verify" in the UI.
    approx: bool = False
    censor: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class TrackInfo:
    """Descriptive metadata used only to look lyrics up; never blocks the pipeline."""

    artist: str | None = None
    title: str | None = None
    album: str | None = None
    duration: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LyricLine:
    """One lyric line with its measured span.

    `start`/`end` come from the lyricsfile `start_ms`/`end_ms` when available, which is
    what makes a proportional estimate for a lyrics-only flag reasonably tight.
    """

    text: str
    start: float
    end: float
    # Present only when the provider supplied true word-level timings.
    words: list[tuple[float, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "words": self.words,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> LyricLine:
        raw = payload.get("words") or []
        spans = [
            (float(span[0]), float(span[1]))
            for span in raw
            if isinstance(span, (list, tuple)) and len(span) == 2
        ]
        return cls(
            text=str(payload.get("text", "")),
            start=float(payload.get("start", 0.0)),
            end=float(payload.get("end", 0.0)),
            words=spans,
        )