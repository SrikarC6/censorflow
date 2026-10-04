"""Tests for the ASR-plus-lyrics cross-check.

The word list is invented on purpose (`snork`, `zzapp` and friends): the real list lives
in `data/profanity.txt` and must not appear in a test file. The transcript and the lyric
lines are hand-built, so every position here is exact.
"""

from __future__ import annotations

import pytest

from censorflow.lyrics.merge import merge_flags
from censorflow.models import SOURCE_ASR, SOURCE_BOTH, SOURCE_LYRICS, LyricLine, Word

# Two invented words standing in for the word list.
LIST = (frozenset({"snork", "zzapp"}), frozenset())


def _words(*spec: tuple[str, float, float]) -> list[Word]:
    return [Word(text=text, start=start, end=end) for text, start, end in spec]


def _lines(*spec: tuple[str, float, float]) -> list[LyricLine]:
    return [LyricLine(text=text, start=start, end=end) for text, start, end in spec]


class TestWithoutLyrics:
    def test_no_lines_gives_exactly_the_asr_flags(self) -> None:
        words = _words(("nothing here", 1.0, 1.4), ("away now", 2.0, 2.8), ("snork", 3.0, 3.4))
        flags = merge_flags(words, [], profane=LIST[0], allowed=LIST[1])
        assert [flag.text for flag in flags] == ["snork"]
        assert flags[0].source == SOURCE_ASR
        assert flags[0].approx is False


class TestUpgrades:
    def test_a_word_both_sides_saw_becomes_both(self) -> None:
        words = _words(("yeah", 10.0, 10.2), ("snork", 10.4, 10.9), ("out", 11.0, 11.2))
        lines = _lines(("yeah snork out", 10.0, 11.2))
        flags = merge_flags(words, lines, profane=LIST[0], allowed=LIST[1])
        assert len(flags) == 1
        assert flags[0].source == SOURCE_BOTH

    def test_merge_does_not_retime_an_already_placed_word(self) -> None:
        # Alignment is what moves a late transcript. Merge only upgrades source.
        words = _words(("yeah", 10.0, 10.2), ("snork", 10.7, 10.9))
        flags = merge_flags(
            words,
            _lines(("yeah there snork here", 10.0, 11.2)),
            profane=LIST[0],
            allowed=LIST[1],
        )
        assert flags[0].source == SOURCE_BOTH
        assert (flags[0].start, flags[0].end) == (10.7, 10.9)

    def test_one_asr_hit_is_not_upgraded_twice(self) -> None:
        words = _words(("snork", 10.4, 10.9))
        # Two provider lines overlapping on the same word.
        lines = _lines(("snork", 10.0, 11.0), ("snork", 10.3, 11.1))
        flags = merge_flags(words, lines, profane=LIST[0], allowed=LIST[1])
        assert len(flags) == 1
        assert flags[0].source == SOURCE_BOTH


class TestAdditions:
    def test_a_word_only_the_lyrics_knew_becomes_an_approximate_flag(self) -> None:
        words = _words(("something", 10.0, 10.4), ("else entirely", 12.0, 12.6))
        lines = _lines(("something zzapp else entirely", 10.0, 12.6))
        flags = merge_flags(words, lines, profane=LIST[0], allowed=LIST[1])
        added = [flag for flag in flags if flag.source == SOURCE_LYRICS]
        assert len(added) == 1
        assert added[0].text == "zzapp"
        assert added[0].approx is True
        assert added[0].confidence == 0.0
        assert added[0].censor is True
        assert added[0].word_index == -1

    def test_a_late_slot_covers_the_leading_fragments(self) -> None:
        # The lyric slot starts on syllable 3. The two syllables before it are
        # short fragments with no gap, so they belong to the same word.
        words = _words(
            ("ma", 1.00, 1.08),
            ("ha", 1.08, 1.16),
            ("fa", 1.16, 1.24),
            ("ka", 1.24, 1.32),
        )
        flags = merge_flags(words, _lines(("zzapp", 1.16, 1.40)), profane=LIST[0], allowed=LIST[1])
        assert len(flags) == 1
        assert flags[0].source == SOURCE_LYRICS
        assert flags[0].start == pytest.approx(1.00)
        assert flags[0].end == pytest.approx(1.40)

    def test_a_one_syllable_slot_does_not_cross_a_gap(self) -> None:
        words = _words(("hi", 1.00, 1.08))
        flags = merge_flags(words, _lines(("zzapp", 2.00, 2.20)), profane=LIST[0], allowed=LIST[1])
        assert flags[0].start == pytest.approx(2.00)
        assert flags[0].end == pytest.approx(2.20)

    def test_a_lyrics_flag_lands_inside_its_line(self) -> None:
        lines = _lines(("alpha bravo zzapp charlie", 30.0, 34.0))
        flags = merge_flags([], lines, profane=LIST[0], allowed=LIST[1])
        assert len(flags) == 1
        assert 30.0 <= flags[0].start < flags[0].end <= 34.0

    def test_longer_words_get_a_longer_share_of_the_line(self) -> None:
        # Proportional-to-length beats dividing evenly: "zzapp" is sung longer than "a".
        line = LyricLine(text="a zzapp", start=0.0, end=3.0)
        flags = merge_flags([], [line], profane=LIST[0], allowed=LIST[1])
        # Even division would start it at 1.5 s; weighting "a" at 2 and "zzapp" at 5 moves
        # it to 0.857 s of lead-in, which is the point of weighting by length.
        assert flags[0].start == pytest.approx(3.0 * 2 / 7)

    def test_repeated_overlapping_lines_do_not_stack_flags(self) -> None:
        # Providers publish a chorus more than once; one chorus is one window.
        lines = _lines(("hey zzapp", 40.0, 41.0), ("hey zzapp", 40.1, 41.1))
        flags = merge_flags([], lines, profane=LIST[0], allowed=LIST[1])
        assert len(flags) == 1

    def test_the_same_word_in_two_different_places_gives_two_flags(self) -> None:
        lines = _lines(("zzapp", 10.0, 10.6), ("zzapp", 50.0, 50.6))
        flags = merge_flags([], lines, profane=LIST[0], allowed=LIST[1])
        assert len(flags) == 2

    def test_real_word_spans_are_used_when_the_count_matches(self) -> None:
        line = LyricLine(
            text="alpha zzapp charlie", start=10.0, end=12.0, words=[(10.0, 10.5), (10.6, 11.4), (11.5, 12.0)]
        )
        flags = merge_flags([], [line], profane=LIST[0], allowed=LIST[1])
        assert flags[0].start == pytest.approx(10.6)
        assert flags[0].end == pytest.approx(11.4)

    def test_word_spans_of_the_wrong_length_fall_back_to_the_estimate(self) -> None:
        line = LyricLine(text="alpha zzapp charlie", start=10.0, end=12.0, words=[(10.0, 10.5)])
        flags = merge_flags([], [line], profane=LIST[0], allowed=LIST[1])
        assert 10.0 <= flags[0].start < 12.0


class TestAllowlist:
    def test_an_allowed_word_is_never_flagged_from_lyrics(self) -> None:
        allowed = frozenset({"snork"})
        flags = merge_flags([], _lines(("hey snork", 5.0, 6.0)), profane=LIST[0], allowed=allowed)
        assert flags == []

    def test_allowed_is_checked_before_the_lyrics(self) -> None:
        words = _words(("snork", 10.4, 10.9))
        allowed = frozenset({"snork"})
        flags = merge_flags(
            words, _lines(("hey snork", 10.0, 11.0)), profane=LIST[0], allowed=allowed
        )
        assert flags == []


class TestRegion:
    """`--clip-seconds` decodes part of a song, but lyrics cover all of it."""

    def test_lines_past_the_end_of_the_audio_are_dropped(self) -> None:
        lines = _lines(("hey zzapp", 10.0, 11.0), ("hey zzapp", 100.0, 101.0))
        flags = merge_flags([], lines, profane=LIST[0], allowed=LIST[1], region_end=45.0)
        assert len(flags) == 1
        assert flags[0].start < 45.0

    def test_an_asr_flag_past_the_end_is_dropped_too(self) -> None:
        words = _words(("snork", 100.0, 100.4))
        assert merge_flags(words, [], profane=LIST[0], allowed=LIST[1], region_end=45.0) == []

    def test_no_region_means_no_filtering(self) -> None:
        words = _words(("snork", 100.0, 100.4))
        flags = merge_flags(words, [], profane=LIST[0], allowed=LIST[1])
        assert len(flags) == 1

    def test_a_region_covering_everything_changes_nothing(self) -> None:
        words = _words(("snork", 10.4, 10.9))
        lines = _lines(("hey snork", 10.0, 11.0))
        flags = merge_flags(words, lines, profane=LIST[0], allowed=LIST[1], region_end=1e9)
        assert [flag.source for flag in flags] == [SOURCE_BOTH]


class TestProvenanceReporting:
    def test_flags_are_sorted_by_start(self) -> None:
        words = _words(("zzapp", 30.0, 30.4), ("snork", 10.0, 10.4))
        flags = merge_flags(words, _lines(("zzapp later", 29.0, 31.0)), profane=LIST[0], allowed=LIST[1])
        assert [flag.start for flag in flags] == sorted(flag.start for flag in flags)