"""Tests for tag reading and the artist/title fallbacks.

No real songs: tags are written onto a short synthetic WAV, and the words used are
invented placeholders.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mutagen.id3 import TALB, TIT2, TPE1
from mutagen.wave import WAVE

from censorflow.audio_io import write
from censorflow.metadata import (
    artist_candidates,
    primary_artist,
    read_metadata,
    title_from_filename,
)

from .conftest import RATE, silence


def _tagged(tmp_path: Path, **tags: str) -> Path:
    """A one-second silent WAV carrying the given tags.

    Tag values are lists because that is what mutagen reports for MP4/M4A, which is the
    format the real samples use; `_read_tags` has to cope with both.
    """
    path = tmp_path / "song.wav"
    write(path, silence(1.0), RATE, "PCM_16")
    frames = {"artist": TPE1, "title": TIT2, "album": TALB}
    handle = WAVE(str(path))
    handle.add_tags()
    for key, value in tags.items():
        handle.tags.add(frames[key](encoding=3, text=[value]))
    handle.save()
    return path


class TestPrimaryArtist:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Playboi Carti", "Playboi Carti"),
            ("Playboi Carti, Kid Cudi", "Playboi Carti"),
            ("Kanye West feat. Ty Dolla Sign", "Kanye West"),
            ("Kanye West ft. Ty Dolla Sign", "Kanye West"),
            ("Drake featuring The Weeknd", "Drake"),
            ("Alpha / Bravo", "Alpha"),
            ("Alpha; Bravo", "Alpha"),
            ("Simon & Garfunkel", "Simon"),
            ("  Chance The Rapper  ", "Chance The Rapper"),
            ("", None),
        ],
    )
    def test_first_credit_wins(self, raw: str, expected: str | None) -> None:
        assert primary_artist(raw) == expected

    def test_candidates_are_tried_best_first(self) -> None:
        assert artist_candidates("Kanye West feat. Ty Dolla Sign, Kid Cudi") == [
            "Kanye West",
            "Ty Dolla Sign",
            "Kid Cudi",
        ]

    def test_candidates_of_nothing_are_empty(self) -> None:
        assert artist_candidates(None) == []


class TestTitleFromFilename:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("01 All Day.m4a", "All Day"),
            ("1-03 BROTHER STONE.m4a", "BROTHER STONE"),
            # The whole point: Path.stem would stop at the first dot.
            ("03. Carti.m4a", "Carti"),
            ("06 - Playboi Carti (M3tamorphosis).m4a", "Playboi Carti (M3tamorphosis)"),
            ("track.FLAC", "track"),
        ],
    )
    def test_track_numbers_and_extensions_are_stripped(
        self, name: str, expected: str
    ) -> None:
        assert title_from_filename(Path("/music") / name) == expected

    def test_nothing_usable_returns_none(self) -> None:
        assert title_from_filename(Path("01.mp3")) is None


class TestReadMetadata:
    def test_tags_win_over_the_filename(self, tmp_path: Path) -> None:
        path = _tagged(tmp_path, artist="Zed Artist", title="Zed Song")
        track = read_metadata(path)
        assert track.artist == "Zed Artist"
        assert track.title == "Zed Song"

    def test_list_valued_tags_are_joined(self, tmp_path: Path) -> None:
        path = _tagged(tmp_path, artist="A One, B Two", title="Tune")
        assert read_metadata(path).artist == "A One, B Two"

    def test_filename_is_the_fallback_when_there_are_no_tags(self, tmp_path: Path) -> None:
        path = tmp_path / "07 Fallback Track.wav"
        write(path, silence(0.5), RATE, "PCM_16")
        assert read_metadata(path).title == "Fallback Track"

    def test_cli_overrides_win_over_everything(self, tmp_path: Path) -> None:
        path = _tagged(tmp_path, artist="Zed Artist", title="Zed Song")
        track = read_metadata(path, artist="Override Artist", title="Override Song")
        assert track.artist == "Override Artist"
        assert track.title == "Override Song"

    def test_an_unreadable_file_does_not_raise(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.m4a"
        broken.write_bytes(b"not audio at all")
        track = read_metadata(broken)
        # Nothing is readable, so the only thing left is the filename.
        assert track.artist is None
        assert track.title == "broken"
        assert track.duration is None

    def test_duration_comes_from_the_audio_not_the_tags(self, tmp_path: Path) -> None:
        assert read_metadata(_tagged(tmp_path)).duration == pytest.approx(1.0, abs=0.05)