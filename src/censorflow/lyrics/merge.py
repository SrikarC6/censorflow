"""Cross-check the ASR transcript against timed lyrics.

Timing is applied *before* this module: `align_words` warps the transcript onto the
lyric-line clock. This module only decides *which* flags to keep or add.

- A profane word the ASR heard is flagged as before, `source=asr`.
- A profane word that both the lyrics and the ASR saw is upgraded to `source=both`.
  The window stays on the (already aligned) word; merge does not retime it.
- A profane word in the lyrics that the ASR did **not** hear becomes a new flag with
  `source=lyrics` and `approx=True`. Timing comes from provider word spans, neighbouring
  aligned words, or a proportional split of the line. A run of short ASR fragments
  just before that slot is the opening of the same word, so the start walks back
  across it.

A lyric token is matched to an ASR flag by whole token, by normalised form, and only
when the flag starts within `_MATCH_SLACK_S` of the estimated position.
"""

from __future__ import annotations

import logging

from .. import config
from ..models import SOURCE_ASR, SOURCE_BOTH, SOURCE_LYRICS, Flag, LyricLine, Word
from ..profanity import detect
from .align import token_spans

logger = logging.getLogger(__name__)

# How far an ASR word may sit from a lyric token's estimated position and still count as
# having heard it. Generous, because the estimate can be a beat out.
_MATCH_SLACK_S = 1.5

# Two flags closer together than this are the same moment; a chorus repeating a word must
# not produce ten flags stacked on one window.
_SAME_MOMENT_S = 0.5


def merge_flags(
    words: list[Word],
    lines: list[LyricLine],
    *,
    profane: frozenset[str] | None = None,
    allowed: frozenset[str] | None = None,
    region_end: float | None = None,
) -> list[Flag]:
    """ASR flags first, then upgrades and additions from the lyrics.

    Returns flags sorted by start time. With no lines the result is exactly
    `detect.detect(words)`, so the pipeline is safe to run with no lyrics provider at all.

    `region_end` is the end of the audio actually being processed. Lyrics cover the whole
    song, so with `--clip-seconds` most of them point at audio that was never decoded:
    lines and flags past that point are dropped rather than piled onto the end of the clip.
    """
    if profane is None or allowed is None:
        profane, allowed = detect.wordlists()

    flags = detect.detect(words, wordlist=(profane, allowed))
    lines = _within(lines, region_end)
    if not lines:
        logger.info("no timed lyrics to cross-check against; %d ASR flags", len(flags))
        return _within_flags(flags, region_end)

    upgrades, additions = _cross_check(words, lines, profane, allowed, flags)
    for flag, token in upgrades:
        flag.source = SOURCE_BOTH
        logger.debug("flag at %.2fs confirmed by the lyrics (%s)", flag.start, detect.mask_word(token))

    merged = flags + additions
    merged = _within_flags(merged, region_end)
    merged.sort(key=lambda flag: (flag.start, flag.end))
    logger.info(
        "lyrics cross-check over %d line(s): %d ASR flag(s), %d confirmed, %d lyrics-only",
        len(lines),
        len([flag for flag in flags if flag.source == SOURCE_ASR]),
        len(upgrades),
        len(additions),
    )
    return merged


def _within(lines: list[LyricLine], region_end: float | None) -> list[LyricLine]:
    """Lines that begin inside the region being processed."""
    if region_end is None:
        return lines
    kept = [line for line in lines if line.start < region_end]
    if len(kept) != len(lines):
        logger.info(
            "dropped %d lyric line(s) past the end of the audio being processed (%.1fs)",
            len(lines) - len(kept),
            region_end,
        )
    return kept


def _within_flags(flags: list[Flag], region_end: float | None) -> list[Flag]:
    if region_end is None:
        return flags
    return [flag for flag in flags if flag.start < region_end]


def _cross_check(
    words: list[Word],
    lines: list[LyricLine],
    profane: frozenset[str],
    allowed: frozenset[str],
    flags: list[Flag],
) -> tuple[list[tuple[Flag, str]], list[Flag]]:
    """Return (flags confirmed by lyrics, flags invented by lyrics)."""
    heard = [(word.start, detect.normalise(word.text)) for word in words]
    upgrades: list[tuple[Flag, str]] = []
    additions: list[Flag] = []
    taken: set[int] = set()

    for line in lines:
        tokens = detect.tokenise(line.text)
        if not tokens:
            continue
        for token, start, end in token_spans(line, tokens, words):
            if not detect.is_profane(token, profane, allowed):
                continue
            flag_index = _match_flag(flags, token, start, heard, taken)
            if flag_index is not None:
                upgrades.append((flags[flag_index], token))
                continue
            if _same_moment(start, flags) or _same_moment(start, additions):
                continue
            start = _cover_leading_fragments(words, start)
            additions.append(
                Flag(
                    word_index=-1,
                    text=token,
                    start=start,
                    end=end,
                    source=SOURCE_LYRICS,
                    confidence=0.0,
                    approx=True,
                    censor=True,
                )
            )
    return upgrades, additions


def _cover_leading_fragments(words: list[Word], start: float) -> float:
    """Move `start` back across the short ASR pieces that lead into it.

    A long word the model will not spell comes out as a chain of ~80 ms
    fragments, and the lyric slot lands on a later one. Walking back across
    that chain covers the opening syllables. A gap, a real-length word, or
    `ONSET_PULL_MAX_S` is the previous word, and the walk stops there.
    """
    pulled = start
    cursor = start
    leading = sorted(
        (word for word in words if word.start < start),
        key=lambda word: word.start,
        reverse=True,
    )
    for word in leading:
        if word.end - word.start > config.ONSET_FRAGMENT_MAX_S:
            break
        if cursor - word.end > config.ONSET_FRAGMENT_GAP_S:
            break
        if start - word.start > config.ONSET_PULL_MAX_S:
            break
        pulled = word.start
        cursor = word.start
    return max(0.0, pulled)


def _match_flag(
    flags: list[Flag],
    token: str,
    estimated_start: float,
    heard: list[tuple[float, str]],
    taken: set[int],
) -> int | None:
    """Index of the ASR flag this lyric token corroborates, if there is one.

    The flag must be unclaimed, must carry the same word once normalised, and must sit
    within the slack of the estimated position. Claiming is one-to-one so a single ASR hit
    is not upgraded twice by two lyric lines that both contain the word.
    """
    normalised = detect.normalise(token)
    if not normalised:
        return None
    for index, flag in enumerate(flags):
        if index in taken or flag.source != SOURCE_ASR:
            continue
        if detect.normalise(flag.text) != normalised:
            continue
        if abs(flag.start - estimated_start) > _MATCH_SLACK_S:
            continue
        if not _heard_near(heard, normalised, flag.start):
            continue
        taken.add(index)
        return index
    return None


def _heard_near(heard: list[tuple[float, str]], normalised: str, start: float) -> bool:
    return any(form == normalised and abs(at - start) <= _MATCH_SLACK_S for at, form in heard)


def _same_moment(start: float, flags: list[Flag]) -> bool:
    """Is there already a flag at (very nearly) this moment?

    Two guards, both needed. Against ASR flags, because a lyrics hit on a word that was
    already flagged is not a new word. Against lyrics-only flags, because providers often
    publish overlapping or repeated lines, and each repeat would otherwise stack a flag on
    the same window.
    """
    return any(abs(flag.start - start) < _SAME_MOMENT_S for flag in flags)