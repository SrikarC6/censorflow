"""Snap ASR word times onto the lyric-line clock.

Parakeet is good at *which* tokens were sung and a poor clock for *when*. LRCLIB
gives line start/end (almost never word-level). Align the two sequences, warp
each matched line's ASR times onto that line's span, then shift leftover ad-libs
by the median offset. Lookup failure is a no-op: the transcript is returned as-is.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Sequence

from .. import config
from ..models import LyricLine, Word
from ..profanity import detect

logger = logging.getLogger(__name__)

# One lyric token: (line index, token index in that line, normalised text, estimated start).
_LyricTok = tuple[int, int, str, float]


def align_words(words: list[Word], lines: list[LyricLine]) -> list[Word]:
    """Return words with start/end remapped onto the lyric-line clock.

    With no lines or no words the input is returned unchanged. Word identity and
    order are preserved so `word_index` on flags still points at the same token.
    """
    if not words or not lines:
        return words

    lyric_toks = _flatten(lines)
    if not lyric_toks:
        return words

    pairs = _align(lyric_toks, words)
    starts = [word.start for word in words]
    ends = [word.end for word in words]
    assigned = [False] * len(words)
    _place_matches(lines, lyric_toks, words, pairs, starts, ends, assigned)

    deltas = [starts[i] - words[i].start for i, flag in enumerate(assigned) if flag]
    offset = statistics.median(deltas) if deltas else 0.0
    if offset:
        for i, word in enumerate(words):
            if not assigned[i]:
                starts[i] = word.start + offset
                ends[i] = word.end + offset

    logger.info(
        "aligned %d/%d words onto %d lyric line(s); median shift %+.3fs",
        sum(assigned),
        len(words),
        len(lines),
        offset,
    )
    return [_with_time(word, starts[i], ends[i]) for i, word in enumerate(words)]


def token_spans(
    line: LyricLine,
    tokens: list[str],
    words: Sequence[Word] | None = None,
) -> list[tuple[str, float, float]]:
    """Where each token sits inside `line`.

    Provider word spans win when the counts match. Otherwise ASR words that
    already sit on this line (after `align_words`) are used as anchors and any
    hole is interpolated. With neither, the line is split in proportion to
    token length.
    """
    if not tokens:
        return []
    span = max(line.end - line.start, config.LYRICS_MIN_LINE_S)
    if len(tokens) == 1:
        return [(tokens[0], line.start, line.start + span)]
    if len(line.words) == len(tokens):
        return [
            (
                token,
                min(max(line.words[index][0], line.start), line.end),
                min(max(line.words[index][1], line.start), line.end),
            )
            for index, token in enumerate(tokens)
        ]
    proportional = _proportional(line, tokens)
    if not words:
        return proportional
    return _anchor_to_words(line, tokens, words, proportional)


def _flatten(lines: list[LyricLine]) -> list[_LyricTok]:
    out: list[_LyricTok] = []
    for line_i, line in enumerate(lines):
        tokens = detect.tokenise(line.text)
        if not tokens:
            continue
        for token_i, (token, start, _end) in enumerate(token_spans(line, tokens)):
            key = detect.normalise(token)
            if key:
                out.append((line_i, token_i, key, start))
    return out


def _align(lyric_toks: list[_LyricTok], words: list[Word]) -> list[tuple[int, int]]:
    """Needleman-Wunsch pairs of (lyric-token index, word index)."""
    n, m = len(lyric_toks), len(words)
    gap = config.ALIGN_GAP_SCORE
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    ptr = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * gap
        ptr[i][0] = 1
    for j in range(1, m + 1):
        dp[0][j] = j * gap
        ptr[0][j] = 2

    asr_keys = [detect.normalise(word.text) for word in words]
    for i in range(1, n + 1):
        _line_i, _tok_i, key, est = lyric_toks[i - 1]
        row, prev = dp[i], dp[i - 1]
        prow = ptr[i]
        for j in range(1, m + 1):
            score = _pair_score(key, asr_keys[j - 1], est, words[j - 1].start)
            best, choice = prev[j] + gap, 1
            left = row[j - 1] + gap
            if left > best:
                best, choice = left, 2
            diag = prev[j - 1] + score
            if diag > best:
                best, choice = diag, 0
            row[j] = best
            prow[j] = choice

    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        choice = ptr[i][j]
        if i > 0 and j > 0 and choice == 0:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or choice == 1):
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _pair_score(lyric_key: str, asr_key: str, est_start: float, asr_start: float) -> float:
    if not lyric_key or not asr_key or lyric_key != asr_key:
        return config.ALIGN_MISMATCH_SCORE
    if abs(asr_start - est_start) <= config.ALIGN_TIME_GATE_S:
        return config.ALIGN_MATCH_SCORE
    return config.ALIGN_FAR_SCORE


def _place_matches(
    lines: list[LyricLine],
    lyric_toks: list[_LyricTok],
    words: list[Word],
    pairs: list[tuple[int, int]],
    starts: list[float],
    ends: list[float],
    assigned: list[bool],
) -> None:
    by_line: dict[int, list[tuple[int, int]]] = {}
    for tok_i, word_i in pairs:
        line_i, token_i, key, est = lyric_toks[tok_i]
        asr_key = detect.normalise(words[word_i].text)
        if key != asr_key:
            continue
        if abs(words[word_i].start - est) > config.ALIGN_TIME_GATE_S:
            continue
        by_line.setdefault(line_i, []).append((token_i, word_i))

    for line_i, placed in by_line.items():
        line = lines[line_i]
        placed.sort(key=lambda item: item[1])
        tokens = detect.tokenise(line.text)
        if len(line.words) == len(tokens) and tokens:
            for token_i, word_i in placed:
                if assigned[word_i] or token_i >= len(line.words):
                    continue
                starts[word_i], ends[word_i] = line.words[token_i]
                assigned[word_i] = True
            continue
        if len(placed) >= 2:
            _warp_span(words, placed, line, starts, ends, assigned)
        else:
            _place_one(words, placed[0], line, tokens, starts, ends, assigned)


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
        filled = _proportional(
            LyricLine(text=" ".join(hole), start=prev_end, end=max(next_start, prev_end)),
            hole,
        )
        for offset, span in enumerate(filled):
            out[index + offset] = span
        index = right
    return out


def _with_time(word: Word, start: float, end: float) -> Word:
    start = max(0.0, start)
    return Word(
        text=word.text,
        start=start,
        end=max(start + 1e-4, end),
        confidence=word.confidence,
        source=word.source,
    )
