"""Snap ASR word times onto timed lyrics without stretching a short phrase.

Parakeet is the tokeniser. A lyric line is the clock only when it is about as
long as the singing inside it. Lines that stay on screen across a gap are much
longer than the phrase; stretching ASR onto those bounds parks the mute in the
gap. Those phrases keep their ASR times. A single match may slide by at most
`ALIGN_MAX_SHIFT_S`. Leftover ad-libs take the median offset of the words that
did move. Lookup failure is a no-op.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Sequence

from .. import config
from ..models import LyricLine, Word
from ..profanity import detect
from .align_time import (
    _anchor_to_words,
    _place_one,
    _proportional,
    _warp_span,
    _with_time,
)

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
