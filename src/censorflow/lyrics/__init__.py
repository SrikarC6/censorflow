"""Lyrics are a cross-check only. Nothing in this package may fail a job.

`lrclib` fetches, `synced` turns a payload into timed lines, `merge` turns timed lines plus
a transcript into flags. Every public function here returns `None` or an empty list instead
of raising.

`lookup` is the one-call convenience wrapper the pipeline uses: source file in, timed lines
out. It lives here rather than in `pipeline.py` so the pipeline does not need to know the
order of the steps, and `workers/fetch_lyrics.py` is only a thin wrapper around it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..models import LyricLine, TrackInfo
from .lrclib import LyricsRecord, fetch, shutdown
from .merge import merge_flags
from .synced import lines_from_record, parse_lyricsfile, parse_synced_lyrics

logger = logging.getLogger(__name__)

__all__ = [
    "LyricsLookup",
    "LyricsRecord",
    "fetch",
    "lines_from_record",
    "lookup",
    "lookup_to_payload",
    "merge_flags",
    "parse_lyricsfile",
    "parse_synced_lyrics",
    "shutdown",
]


@dataclass(slots=True)
class LyricsLookup:
    """The result of one lookup: what we asked, what we got, and the timed lines."""

    track: TrackInfo = field(default_factory=TrackInfo)
    record: LyricsRecord | None = None
    lines: list[LyricLine] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.record is not None

    def to_payload(self) -> dict[str, object]:
        """The on-disk shape for `<job>/lyrics.json`, so the server need not re-query."""
        return {
            "found": self.found,
            "track": self.track.to_dict(),
            "provider": self.record.provider if self.record else None,
            "track_id": self.record.track_id if self.record else None,
            "has_word_sync": bool(self.record.has_word_sync) if self.record else False,
            "lines": [line.to_dict() for line in self.lines],
        }


def lookup(source: Path) -> LyricsLookup:
    """Read tags from `source`, then look the lyrics up. Never raises."""
    from ..metadata import artist_candidates, read_metadata

    try:
        track = read_metadata(Path(source))
    except Exception:
        logger.exception("could not read metadata from %s", source)
        return LyricsLookup()

    artists = artist_candidates(track.artist) if track.artist else None
    try:
        record = fetch(track, artists=artists)
    except Exception:
        logger.exception("lyrics lookup failed for %r", track.title)
        return LyricsLookup(track=track)

    lines = lines_from_record(record)
    if record is None:
        logger.info("no lyrics found for %r; the transcript stands alone", track.title)
    else:
        logger.info(
            "lyrics from %s id=%s: %d timed lines%s",
            record.provider,
            record.track_id,
            len(lines),
            " with word timing" if record.has_word_sync else "",
        )
    return LyricsLookup(track=track, record=record, lines=lines)


def lookup_to_payload(source: Path) -> dict[str, object]:
    """`lookup`, serialised. Used by the worker stage."""
    return lookup(source).to_payload()