"""Tests for tag reading and the artist/title fallbacks.

No real songs: tags are written onto a short synthetic WAV, and the words used are
invented placeholders.
"""

from __future__ import annotations

import json
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
from mutagen.id3 import TALB, TIT2, TPE1
from mutagen.mp4 import MP4, MP4Cover
from mutagen.wave import WAVE

from censorflow import audio_io
from censorflow.audio_io import write
from censorflow.metadata import (
    artist_candidates,
    copy_metadata,
    primary_artist,
    read_metadata,
    title_from_filename,
)
from censorflow.pipeline import PipelineResult, render_reviewed

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


def _png() -> bytes:
    """A valid 1x1 PNG, so a cover-art copy has a real picture to carry."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    image = b"\x00\xff\x00\x00"
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(image)) + chunk(b"IEND", b"")


def _rich_m4a(directory: Path) -> Path:
    """A silent m4a carrying the tags a ripped song actually has, plus a cover."""
    wav = directory / "bare.wav"
    write(wav, silence(0.4), RATE, "PCM_16")
    path = directory / "song.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac", str(path)],
        check=True,
        capture_output=True,
    )
    audio = MP4(path)
    audio["\xa9nam"] = ["Zed Song"]
    audio["\xa9ART"] = ["Zed Artist"]
    audio["\xa9alb"] = ["Zed Album"]
    audio["aART"] = ["Zed Band"]
    audio["\xa9gen"] = ["Zed Genre"]
    audio["\xa9day"] = ["2020"]
    audio["trkn"] = [(4, 10)]
    audio["disk"] = [(1, 2)]
    audio["\xa9cmt"] = ["Zed comment"]
    audio["\xa9lyr"] = ["la la"]
    audio["\xa9wrt"] = ["Zed Writer"]
    audio["covr"] = [MP4Cover(_png(), imageformat=MP4Cover.FORMAT_PNG)]
    audio.save()
    wav.unlink()
    return path


def _format_tags(path: Path) -> dict[str, str]:
    raw = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)]
    )
    return json.loads(raw)["format"].get("tags") or {}


def _has_cover(path: Path) -> bool:
    """True when the file carries a picture block. FLAC stores it outside any video stream."""
    from mutagen import File

    audio = File(path)
    if audio is None:
        return False
    if getattr(audio, "pictures", None):
        return True
    tags = getattr(audio, "tags", None) or {}
    return any(str(key).startswith("APIC") for key in tags)


@pytest.mark.parametrize("fmt", ["flac", "mp3", "wav"])
def test_a_cleaned_file_keeps_the_source_tags(tmp_path: Path, fmt: str) -> None:
    source = _rich_m4a(tmp_path)
    bare = tmp_path / "bare.wav"
    write(bare, silence(0.4), RATE, "PCM_16")
    dest = tmp_path / f"clean.{fmt}"
    audio_io.encode(bare, dest, fmt)
    assert copy_metadata(source, dest)

    tags = _format_tags(dest)
    for key, value in {
        "title": "Zed Song",
        "artist": "Zed Artist",
        "album": "Zed Album",
        "genre": "Zed Genre",
        "date": "2020",
        "comment": "Zed comment",
        "track": "4/10",
    }.items():
        assert tags.get(key) == value, key
    if fmt == "wav":
        return
    assert tags.get("album_artist") == "Zed Band"
    assert tags.get("composer") == "Zed Writer"
    assert tags.get("lyrics") == "la la"
    assert tags.get("disc") == "1/2"
    assert _has_cover(dest)


def test_rendering_a_job_copies_tags_from_the_original(tmp_path: Path) -> None:
    source = _rich_m4a(tmp_path)
    original = tmp_path / "original.m4a"
    source.rename(original)
    mix = tmp_path / "mix.wav"
    vocals = tmp_path / "vocals.wav"
    audio = silence(0.4)
    write(mix, audio, RATE, "PCM_16")
    write(vocals, audio * 0, RATE, "PCM_16")
    result = PipelineResult(job_dir=tmp_path, mix_path=mix, stems={"vocals": vocals})
    rendered = render_reviewed(result, tmp_path / "clean.flac", "flac")
    assert _format_tags(rendered.output_path)["title"] == "Zed Song"
    assert _has_cover(rendered.output_path)