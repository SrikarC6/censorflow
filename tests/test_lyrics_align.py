"""Tests for warping ASR times onto the lyric-line clock.

Placeholder words only (`snork`, `zzapp`); no real lyrics and no profanity.
"""

from __future__ import annotations

import pytest

from censorflow.lyrics.align import align_words, token_spans
from censorflow.lyrics.merge import merge_flags
from censorflow.models import SOURCE_BOTH, LyricLine, Word

LIST = (frozenset({"snork", "zzapp"}), frozenset())


def _words(*spec: tuple[str, float, float]) -> list[Word]:
    return [Word(text=text, start=start, end=end) for text, start, end in spec]


def _line(text: str, start: float, end: float, words: list[tuple[float, float]] | None = None) -> LyricLine:
    return LyricLine(text=text, start=start, end=end, words=words or [])


class TestIdentity:
    def test_no_lines_leaves_times_alone(self) -> None:
        words = _words(("snork", 10.6, 10.9))
        aligned = align_words(words, [])
        assert aligned[0].start == 10.6
        assert aligned[0].end == 10.9

    def test_no_words_is_empty(self) -> None:
        assert align_words([], [_line("hey snork", 10.0, 11.0)]) == []


class TestWarp:
    def test_a_late_transcript_is_pulled_onto_the_line_clock(self) -> None:
        # ASR is 0.6 s late, about one rap word. Three matches stretch the ASR
        # span onto the lyric line, so snork must move earlier, into the line.
        words = _words(("yeah", 10.6, 10.8), ("snork", 11.0, 11.2), ("out", 11.4, 11.6))
        aligned = align_words(words, [_line("yeah snork out", 10.0, 11.2)])
        assert 10.0 <= aligned[1].start < aligned[1].end <= 11.2 + 1e-6
        assert aligned[1].start < 11.0
        assert aligned[1].text == "snork"

    def test_the_same_token_in_two_lines_stays_on_its_own_line(self) -> None:
        words = _words(("snork", 10.6, 10.9), ("snork", 50.6, 50.9))
        lines = [_line("hey snork", 10.0, 11.0), _line("hey snork", 50.0, 51.0)]
        aligned = align_words(words, lines)
        assert aligned[0].start < 20.0
        assert aligned[1].start > 40.0
        assert 10.0 <= aligned[0].start <= 11.0
        assert 50.0 <= aligned[1].start <= 51.0

    def test_an_ad_lib_picks_up_the_global_offset(self) -> None:
        words = _words(("snork", 10.6, 10.9), ("zzapp", 12.0, 12.3))
        aligned = align_words(words, [_line("only snork here", 10.0, 11.0)])
        shift = aligned[0].start - 10.6
        assert aligned[1].start == pytest.approx(12.0 + shift)
        assert aligned[1].end == pytest.approx(12.3 + shift)

    def test_a_long_lyric_card_does_not_stretch_a_short_phrase(self) -> None:
        # The line stays up for 10 s; the phrase is under a second. Stretching
        # it to the card would park the mute in the gap.
        words = _words(("alpha", 1.0, 1.2), ("snork", 1.3, 1.5), ("charlie", 1.6, 1.8))
        aligned = align_words(words, [_line("alpha snork charlie", 0.0, 10.0)])
        assert aligned[1].start == pytest.approx(1.3)
        assert aligned[1].end == pytest.approx(1.5)

    def test_a_single_match_will_not_jump_across_a_long_line(self) -> None:
        words = _words(("snork", 1.2, 1.4))
        aligned = align_words(words, [_line("aaaa snork", 0.0, 8.0)])
        assert aligned[0].start == pytest.approx(1.2)

    def test_word_level_spans_win_when_the_counts_match(self) -> None:
        line = _line(
            "alpha snork charlie",
            10.0,
            12.0,
            words=[(10.0, 10.5), (10.6, 11.4), (11.5, 12.0)],
        )
        words = _words(("alpha", 10.5, 10.7), ("snork", 11.1, 11.4), ("charlie", 11.8, 12.1))
        aligned = align_words(words, [line])
        assert aligned[1].start == pytest.approx(10.6)
        assert aligned[1].end == pytest.approx(11.4)


class TestTokenSpans:
    def test_a_missed_token_is_interpolated_between_neighbours(self) -> None:
        line = _line("alpha zzapp charlie", 10.0, 13.0)
        words = _words(("alpha", 10.0, 10.4), ("charlie", 11.0, 11.3))
        spans = token_spans(line, ["alpha", "zzapp", "charlie"], words)
        assert spans[1][0] == "zzapp"
        assert spans[1][1] == pytest.approx(10.4)
        assert spans[1][2] == pytest.approx(11.0)

    def test_a_missed_token_after_the_phrase_stays_with_the_phrase(self) -> None:
        # The card runs to 10 s. The only sung anchor ends at 1.2 s, so the
        # missing word belongs just after it, not in the middle of the card.
        line = _line("alpha zzapp", 0.0, 10.0)
        spans = token_spans(line, ["alpha", "zzapp"], words=_words(("alpha", 1.0, 1.2)))
        assert spans[1][1] == pytest.approx(1.2)
        assert spans[1][2] < 2.0

    def test_no_overlapping_words_falls_back_to_length_weights(self) -> None:
        line = _line("a zzapp", 0.0, 3.0)
        spans = token_spans(line, ["a", "zzapp"], words=_words(("elsewhere", 50.0, 50.4)))
        assert spans[1][1] == pytest.approx(3.0 * 2 / 7)


class TestMerge:
    def test_align_then_merge_moves_a_late_asr_flag_onto_the_line(self) -> None:
        words = _words(("yeah", 10.6, 10.8), ("snork", 11.0, 11.2), ("out", 11.4, 11.6))
        lines = [_line("yeah snork out", 10.0, 11.2)]
        aligned = align_words(words, lines)
        flags = merge_flags(aligned, lines, profane=LIST[0], allowed=LIST[1])
        assert len(flags) == 1
        assert flags[0].source == SOURCE_BOTH
        assert 10.0 <= flags[0].start <= 11.2
        assert flags[0].start < 11.0
