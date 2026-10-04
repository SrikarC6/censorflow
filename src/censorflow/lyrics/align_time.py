"""Place matched words on the lyric clock, and pack the holes.

`align.py` decides which words match. This module decides where those words,
and the ones the match missed, sit in time.
"""

from __future__ import annotations

from collections.abc import Sequence

from .. import config
from ..models import LyricLine, Word
from ..profanity import detect


def _warp_span(
    words: list[Word],
    placed: list[tuple[int, int]],
    line: LyricLine,
    starts: list[float],
    ends: list[float],
    assigned: list[bool],
) -> None:
    first, last = placed[0][1], placed[-1][1]
    asr0 = words[first].start
    asr1 = words[last].end
    asr_dur = asr1 - asr0
    line_dur = max(line.end - line.start, config.LYRICS_MIN_LINE_S)
    if asr_dur <= 1e-6:
        _place_one(words, placed[0], line, detect.tokenise(line.text), starts, ends, assigned)
        return

    stretch = line_dur / asr_dur
    if stretch > config.ALIGN_MAX_STRETCH or stretch < 1.0 / config.ALIGN_MAX_STRETCH:
        # The lyric card is not the length of the phrase. Keep the sung timing.
        for word_i, word in enumerate(words):
            if assigned[word_i] or word.start < asr0 or word.start > asr1:
                continue
            starts[word_i] = word.start
            ends[word_i] = word.end
            assigned[word_i] = True
        return

    def warp(at: float) -> float:
        return line.start + (at - asr0) / asr_dur * line_dur

    for word_i, word in enumerate(words):
        if assigned[word_i]:
            continue
        if word.start < asr0 or word.start > asr1:
            continue
        starts[word_i] = warp(word.start)
        ends[word_i] = warp(word.end)
        assigned[word_i] = True


def _place_one(
    words: list[Word],
    placed: tuple[int, int],
    line: LyricLine,
    tokens: list[str],
    starts: list[float],
    ends: list[float],
    assigned: list[bool],
) -> None:
    token_i, word_i = placed
    if assigned[word_i]:
        return
    spans = _proportional(line, tokens) if tokens else []
    if token_i < len(spans):
        dest = spans[token_i][1]
    else:
        dest = line.start
    if abs(dest - words[word_i].start) > config.ALIGN_MAX_SHIFT_S:
        dest = words[word_i].start
    duration = max(words[word_i].end - words[word_i].start, 1e-4)
    starts[word_i] = dest
    ends[word_i] = min(dest + duration, line.end if line.end > dest else dest + duration)
    assigned[word_i] = True


def _proportional(line: LyricLine, tokens: list[str]) -> list[tuple[str, float, float]]:
    span = max(line.end - line.start, config.LYRICS_MIN_LINE_S)
    weights = [max(len(token), 2) for token in tokens]
    total = sum(weights) or 1
    out: list[tuple[str, float, float]] = []
    cursor = line.start
    for token, weight in zip(tokens, weights, strict=True):
        width = min(max(span * weight / total, config.LYRICS_MIN_WORD_S), config.LYRICS_MAX_WORD_S)
        out.append((token, cursor, cursor + width))
        cursor += width
    return out


def _anchor_to_words(
    line: LyricLine,
    tokens: list[str],
    words: Sequence[Word],
    proportional: list[tuple[str, float, float]],
) -> list[tuple[str, float, float]]:
    in_line = [word for word in words if word.start < line.end and word.end > line.start]
    if not in_line:
        return proportional

    anchors: dict[int, tuple[float, float]] = {}
    cursor = 0
    for token_i, token in enumerate(tokens):
        key = detect.normalise(token)
        if not key:
            continue
        for word_i in range(cursor, len(in_line)):
            if detect.normalise(in_line[word_i].text) != key:
                continue
            word = in_line[word_i]
            anchors[token_i] = (word.start, word.end)
            cursor = word_i + 1
            break
    if not anchors:
        return proportional
    return _fill_holes(tokens, anchors, line)


def _fill_holes(
    tokens: list[str],
    anchors: dict[int, tuple[float, float]],
    line: LyricLine,
) -> list[tuple[str, float, float]]:
    out: list[tuple[str, float, float]] = [("", 0.0, 0.0)] * len(tokens)
    for token_i, span in anchors.items():
        out[token_i] = (tokens[token_i], span[0], span[1])

    index = 0
    while index < len(tokens):
        if index in anchors:
            index += 1
            continue
        left = index - 1
        while left >= 0 and left not in anchors:
            left -= 1
        right = index
        while right < len(tokens) and right not in anchors:
            right += 1
        prev_end = anchors[left][1] if left >= 0 else line.start
        next_start = anchors[right][0] if right < len(tokens) else line.end
        hole = tokens[index:right]
        hole_start, hole_end = _pack_loose_hole(
            prev_end, next_start, len(hole), left_real=left >= 0, right_real=right < len(tokens)
        )
        filled = _proportional(
            LyricLine(text=" ".join(hole), start=hole_start, end=max(hole_end, hole_start)),
            hole,
        )
        for offset, span in enumerate(filled):
            out[index + offset] = span
        index = right
    return out


def _pack_loose_hole(
    prev_end: float,
    next_start: float,
    count: int,
    *,
    left_real: bool,
    right_real: bool,
) -> tuple[float, float]:
    """Keep a short run of missing words beside a real neighbour.

    A lyric card often runs on after the phrase. Spreading the missing tokens
    across that leftover time puts them in the gap. Pack them against the
    neighbour that was actually sung.
    """
    span = max(next_start - prev_end, 1e-3)
    need = max(count * config.ALIGN_PACK_WORD_S, config.LYRICS_MIN_WORD_S)
    if span <= max(need * 2.0, need + 0.6):
        return prev_end, next_start
    if left_real:
        return prev_end, min(next_start, prev_end + need)
    if right_real:
        return max(prev_end, next_start - need), next_start
    return prev_end, next_start


def _with_time(word: Word, start: float, end: float) -> Word:
    start = max(0.0, start)
    return Word(
        text=word.text,
        start=start,
        end=max(start + 1e-4, end),
        confidence=word.confidence,
        source=word.source,
    )
