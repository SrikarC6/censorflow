"""Turn a provider payload into timed lyric lines.

Three sources, best first:

1. **`lyricsfile`** - Lyricsfile YAML, which gives each line both `start_ms` **and**
   `end_ms`. Two timestamps per line is what makes the proportional estimate in `merge.py`
   usable, so this is preferred even though a plain LRC string is also in the payload.
2. **`syncedLyrics`** - LRC: one `[mm:ss.xx]` stamp per line, no end times. Ends are
   inferred from the following line's start.
3. **`plainLyrics`** - untimed. Returned as nothing: a line with no position cannot place a
   censor window, and a badly placed window is worse than no flag.

Word-level timing is handled when it exists (`words[]` in Lyricsfile, or inline
`<mm:ss.xx>` tags in LRC) but is not depended upon: none of the tracks available during
development had it, so `merge.py` must work from line timing alone.

Nothing here raises. A malformed YAML document yields an empty list and a log line.
"""

from __future__ import annotations

import logging
import re

import yaml

from .. import config
from ..models import LyricLine
from .lrclib import LyricsRecord

logger = logging.getLogger(__name__)

# "[01:23.45]" or "[01:23]" at the start of an LRC line, and "<01:23.45>" inline.
_LRC_STAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_LRC_INLINE = re.compile(r"<(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?>")
_LRC_META = re.compile(r"^\[(ar|ti|al|by|offset|re|ve|length):.*\]$", re.IGNORECASE)

# A line shorter than this cannot hold a word, whatever the timing says.
_MIN_LINE_TEXT = 1

# An LRC line paired with the LyricLine it became, kept sorted by start time.
StampedText = tuple[float, LyricLine]


def lines_from_record(record: LyricsRecord | None) -> list[LyricLine]:
    """Every timed line the record can give us. Empty when there is nothing usable."""
    if record is None:
        return []
    if record.instrumental:
        logger.info("the provider marks this track as instrumental")
        return []

    lines = _from_lyricsfile(record)
    if lines:
        return lines
    lines = _from_synced(record)
    if lines:
        return lines
    if record.plain_lyrics:
        logger.info(
            "lyrics found (%s) but they carry no timing, so they cannot place flags",
            record.track_id,
        )
    return []


def parse_lyricsfile(text: str) -> list[LyricLine]:
    """Parse a Lyricsfile YAML document into timed lines."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        logger.info("lyricsfile is not valid YAML (%s)", error)
        return []
    if not isinstance(document, dict):
        logger.info("lyricsfile is not a mapping")
        return []

    raw_lines = document.get("lines")
    if not isinstance(raw_lines, list):
        return []

    lines: list[LyricLine] = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        body = raw.get("text")
        if not isinstance(body, str) or len(body.strip()) < _MIN_LINE_TEXT:
            continue
        start = _ms(raw.get("start_ms"))
        end = _ms(raw.get("end_ms"))
        if start is None:
            continue
        lines.append(
            LyricLine(
                text=body,
                start=max(0.0, start),
                end=max(0.0, end) if end is not None else start,
                words=_words(raw.get("words")),
            )
        )
    return _close_spans(lines)


def parse_synced_lyrics(text: str, *, duration: float | None = None) -> list[LyricLine]:
    """Parse LRC into timed lines, inferring each end from the next line's start."""
    offset_s = 0.0
    stamped: list[StampedText] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _LRC_META.match(line):
            offset_s = _lrc_offset(line, offset_s)
            continue
        stamps = _LRC_STAMP.findall(line)
        if not stamps:
            continue
        body = _LRC_STAMP.sub("", line).strip()
        if len(body) < _MIN_LINE_TEXT:
            continue
        for minute, second, fraction in stamps:
            at = _minutes(minute, second, fraction) + offset_s
            stamped.append((at, _line_from_body(at, body)))

    stamped.sort(key=lambda entry: entry[0])
    return _close_spans([line for _, line in stamped], duration=duration)


def _from_lyricsfile(record: LyricsRecord) -> list[LyricLine]:
    text = record.raw.get("lyricsfile")
    if not isinstance(text, str) or not text.strip():
        return []
    lines = parse_lyricsfile(text)
    if lines:
        logger.info("parsed %d timed line(s) from lyricsfile", len(lines))
    return lines


def _from_synced(record: LyricsRecord) -> list[LyricLine]:
    if not record.synced_lyrics:
        return []
    lines = parse_synced_lyrics(record.synced_lyrics, duration=record.duration)
    if lines:
        logger.info("parsed %d timed line(s) from synced lyrics", len(lines))
    return lines


def _line_from_body(start: float, body: str) -> LyricLine:
    """One LRC body, with any inline `<mm:ss.xx>` word stamps unpacked into spans."""
    pieces = _split_inline(body)
    stamps = [at for at, _ in pieces if at is not None]
    # The last stamped word has no successor to end against, so its span closes on itself.
    # `censor.windows` enforces MIN_WINDOW_MS, which turns that into a usable window.
    words = [
        (at, stamps[index + 1] if index + 1 < len(stamps) else at)
        for index, at in enumerate(stamps)
    ]
    return LyricLine(
        text=" ".join(word for _, word in pieces), start=start, end=start, words=words
    )


def _split_inline(body: str) -> list[tuple[float | None, str]]:
    """Split a body into `(stamp or None, text)` pieces.

    `None` marks text that belongs to the line as a whole; a stamp marks a word the
    provider timed individually. Matching by position rather than by `re.split` matters:
    the pattern has three capture groups, so splitting returns `[text, mm, ss, xx, text,
    ...]` and index arithmetic over it lands on the wrong element.
    """
    marks = list(_LRC_INLINE.finditer(body))
    if not marks:
        return [(None, body)]

    pieces: list[tuple[float | None, str]] = []
    leading = body[: marks[0].start()].strip()
    if leading:
        pieces.append((None, leading))
    for index, mark in enumerate(marks):
        stop = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        word = body[mark.end() : stop].strip()
        if word:
            pieces.append((_minutes(mark.group(1), mark.group(2), mark.group(3)), word))
    return pieces


def _words(raw: object) -> list[tuple[float, float]]:
    """Word spans from a Lyricsfile `words` block, if the provider supplied one.

    Both spellings are accepted: `[start_ms, end_ms]` pairs and `{"start_ms": ...,
    "end_ms": ...}` mappings. No record seen during development had a `words` block at all,
    so the schema is taken from the format rather than from an observed payload.
    """
    if not isinstance(raw, list):
        return []
    spans: list[tuple[float, float]] = []
    for entry in raw:
        if isinstance(entry, dict):
            start = _ms(entry.get("start_ms"))
            end = _ms(entry.get("end_ms"))
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            start = _ms(entry[0])
            end = _ms(entry[1])
        else:
            continue
        if start is None or end is None:
            continue
        spans.append((start, end))
    return sorted(spans)


def _close_spans(lines: list[LyricLine], *, duration: float | None = None) -> list[LyricLine]:
    """Give every line a usable end: the next line's start, the track's end, or +3 s.

    Providers supply either both timestamps or only a start. A zero-length line would make
    the proportional estimate in `merge.py` collapse to a single point.
    """
    if not lines:
        return []
    lines.sort(key=lambda line: line.start)
    out: list[LyricLine] = []
    for index, line in enumerate(lines):
        if index + 1 < len(lines):
            end = lines[index + 1].start
        elif duration:
            end = float(duration)
        else:
            end = line.end if line.end > line.start else line.start + 3.0
        span = max(end - line.start, config.LYRICS_MIN_LINE_S)
        out.append(
            LyricLine(
                text=line.text,
                start=line.start,
                end=line.start + span,
                words=line.words,
            )
        )
    return out


def _lrc_offset(line: str, current: float) -> float:
    """Read an LRC `[offset:...]` tag.

    The sign convention differs between players and LRCLIB does not emit the tag, so this
    is recognised and reported rather than applied: guessing it would silently shift every
    window in the song.
    """
    logger.info("ignoring an LRC %s tag in the synced lyrics", line.strip())
    return current


def _minutes(minute: str, second: str, fraction: str | None) -> float:
    fraction_text = (fraction or "0").ljust(3, "0")[:3]
    return (
        int(minute) * 60.0 + int(second) + int(fraction_text) / 1000.0
    )


def _ms(value: object) -> float | None:
    """Milliseconds to seconds. LRCLIB has been seen sending ints, floats and strings."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000.0
    if isinstance(value, str):
        try:
            return float(value) / 1000.0
        except ValueError:
            return None
    return None