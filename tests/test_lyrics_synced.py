"""Tests for turning a provider payload into timed lines.

Every lyric here is invented filler, and no provider is contacted.
"""

from __future__ import annotations

import pytest

from censorflow.lyrics.lrclib import LyricsRecord
from censorflow.lyrics.synced import (
    lines_from_record,
    parse_lyricsfile,
    parse_synced_lyrics,
)

_LYRICSFILE = """
version: 0.1
metadata:
  title: Filler Song
  artist: Nobody
  album: Filler Album
  duration_ms: 120000
  instrumental: false
lines:
  - text: alpha bravo charlie
    start_ms: 1000
    end_ms: 4000
  - text: delta echo
    start_ms: 4000
    end_ms: 6000
"""


class TestLyricsfile:
    def test_start_and_end_are_read_in_seconds(self) -> None:
        lines = parse_lyricsfile(_LYRICSFILE)
        assert [line.text for line in lines] == ["alpha bravo charlie", "delta echo"]
        assert lines[0].start == pytest.approx(1.0, abs=1e-6)
        assert lines[0].end == pytest.approx(4.0, abs=1e-6)
        assert lines[1].start == pytest.approx(4.0, abs=1e-6)

    def test_string_milliseconds_are_accepted(self) -> None:
        document = "lines:\n  - text: one two\n    start_ms: '2500'\n    end_ms: '3000'\n"
        assert parse_lyricsfile(document)[0].start == pytest.approx(2.5)

    def test_malformed_yaml_gives_nothing_rather_than_raising(self) -> None:
        assert parse_lyricsfile("lines: [oops\n  - broken: {{{") == []

    def test_a_document_that_is_not_a_mapping_gives_nothing(self) -> None:
        assert parse_lyricsfile("- just\n- a list\n") == []

    def test_lines_without_a_start_are_dropped(self) -> None:
        document = "lines:\n  - text: no timing here\n"
        assert parse_lyricsfile(document) == []

    @pytest.mark.parametrize(
        "block",
        [
            "      - [100, 900]\n      - [900, 1900]\n",
            "      - {start_ms: 100, end_ms: 900}\n      - {start_ms: 900, end_ms: 1900}\n",
        ],
        ids=["pairs", "mappings"],
    )
    def test_word_spans_are_kept_when_present(self, block: str) -> None:
        document = f"lines:\n  - text: alpha bravo\n    start_ms: 0\n    end_ms: 2000\n    words:\n{block}"
        assert parse_lyricsfile(document)[0].words == [(0.1, 0.9), (0.9, 1.9)]

    def test_a_word_entry_of_the_wrong_shape_is_skipped(self) -> None:
        document = (
            "lines:\n  - text: alpha bravo\n    start_ms: 0\n    end_ms: 2000\n"
            "    words:\n      - [100]\n      - [900, 1900]\n"
        )
        assert parse_lyricsfile(document)[0].words == [(0.9, 1.9)]

    def test_a_line_missing_its_end_borrows_the_span_floor(self) -> None:
        document = "lines:\n  - text: only a start\n    start_ms: 4000\n"
        line = parse_lyricsfile(document)[0]
        assert line.start == pytest.approx(4.0)
        assert line.end > line.start


class TestSyncedLyrics:
    def test_line_stamps_become_starts(self) -> None:
        text = "[ar:Nobody]\n[00:01.00]alpha bravo\n[00:05.50]delta echo\n"
        lines = parse_synced_lyrics(text)
        assert [line.text for line in lines] == ["alpha bravo", "delta echo"]
        assert lines[0].start == pytest.approx(1.0)
        assert lines[1].start == pytest.approx(5.5)

    def test_a_lines_end_is_the_next_lines_start(self) -> None:
        text = "[00:01.00]alpha bravo\n[00:05.50]delta echo\n"
        assert parse_synced_lyrics(text)[0].end == pytest.approx(5.5)

    def test_the_last_line_stops_at_the_track_duration(self) -> None:
        text = "[00:01.00]alpha\n[00:30.00]bravo\n"
        assert parse_synced_lyrics(text, duration=40.0)[1].end == pytest.approx(40.0)

    def test_metadata_lines_are_skipped(self) -> None:
        text = "[ti:A Title]\n[offset:+500]\n[00:01.00]only a lyric\n"
        assert [line.text for line in parse_synced_lyrics(text)] == ["only a lyric"]

    def test_inline_word_timestamps_become_word_spans(self) -> None:
        text = "[00:10.00]<00:10.00>alpha <00:10.50>bravo <00:11.00>charlie"
        line = parse_synced_lyrics(text)[0]
        assert line.text == "alpha bravo charlie"
        assert len(line.words) == 3
        assert line.words[0] == pytest.approx((10.0, 10.5))

    def test_a_stamp_with_no_words_is_dropped(self) -> None:
        assert parse_synced_lyrics("[00:01.00]\n") == []


class TestLinesFromRecord:
    def _record(self, **kwargs: object) -> LyricsRecord:
        defaults: dict[str, object] = {
            "provider": "lrclib",
            "track_id": 1,
            "title": "Filler",
            "artist": "Nobody",
            "album": None,
            "duration": 120.0,
            "instrumental": False,
            "has_word_sync": False,
            "synced_lyrics": None,
            "plain_lyrics": "alpha bravo",
            "raw": {},
        }
        defaults.update(kwargs)
        return LyricsRecord(**defaults)  # type: ignore[arg-type]

    def test_nothing_in_nothing_out(self) -> None:
        assert lines_from_record(None) == []

    def test_the_lyricsfile_is_preferred_over_lrc(self) -> None:
        record = self._record(
            raw={"lyricsfile": _LYRICSFILE}, synced_lyrics="[00:01.00]something else"
        )
        assert lines_from_record(record)[0].text == "alpha bravo charlie"

    def test_lrc_is_used_when_there_is_no_lyricsfile(self) -> None:
        record = self._record(synced_lyrics="[00:01.00]alpha bravo")
        assert lines_from_record(record)[0].text == "alpha bravo"

    def test_untimed_lyrics_are_deliberately_ignored(self) -> None:
        # A window cannot be placed on an unpositioned line, and a badly placed window is
        # worse than no flag at all.
        assert lines_from_record(self._record()) == []

    def test_an_instrumental_has_no_lines(self) -> None:
        record = self._record(instrumental=True, raw={"lyricsfile": _LYRICSFILE})
        assert lines_from_record(record) == []
