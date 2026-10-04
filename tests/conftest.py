"""Synthetic audio fixtures. Tests never touch real music; see AGENTS.md rule 7."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from censorflow import config
from censorflow.audio_io import duration_seconds, read, write
from censorflow.models import SOURCE_ASR, ProgressFn, Word

RATE = config.SAMPLE_RATE


def tone(freq: float, seconds: float, amp: float = 0.3, rate: int = RATE) -> np.ndarray:
    """Mono float32 sine, shaped (frames, channels) once stacked."""
    t = np.arange(int(seconds * rate), dtype=np.float32) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def burst(
    freq: float,
    start: float,
    length: float,
    amp: float = 0.4,
    rate: int = RATE,
    total: float | None = None,
) -> np.ndarray:
    """Mono sine gated to silence outside [start, start + length).

    `total` pads the result out to that many seconds, so a burst can be added straight
    into a full-length track.
    """
    stop = start + length
    frames = round((total if total is not None else stop) * rate)
    out = np.zeros(frames, dtype=np.float32)
    seg = tone(freq, length, amp, rate)
    offset = round(start * rate)
    end = min(frames, offset + len(seg))
    out[offset:end] = seg[: end - offset]
    return out


def stereo(mono: np.ndarray, channels: int = config.CHANNELS) -> np.ndarray:
    return np.repeat(mono[:, None], channels, axis=1)


def silence(seconds: float, rate: int = RATE, channels: int = config.CHANNELS) -> np.ndarray:
    return np.zeros((int(seconds * rate), channels), dtype=np.float32)


@pytest.fixture
def stems() -> dict[str, np.ndarray]:
    """A mix built as `vocals + instrumentals`, with two sung bursts.

    The vocal bursts are loud enough that a mask which fails to remove them is obvious,
    and the instrumental runs continuously so a mask which silences the mix is obvious.
    """
    instrumentals = stereo(tone(110.0, 6.0, amp=0.25))
    vocals = np.zeros_like(instrumentals)
    vocals[:, 0] += burst(440.0, 1.0, 0.5, amp=0.45, total=6.0)
    vocals[:, 0] += burst(660.0, 3.0, 0.7, amp=0.45, total=6.0)
    mix = instrumentals + vocals
    return {"mix": mix, "vocals": vocals, "instrumentals": instrumentals}


def rms(data: np.ndarray, start: float, end: float, rate: int = RATE) -> float:
    """RMS of a region, ignoring the fade edges the mask always adds."""
    guard = 0.02
    s = int((start + guard) * rate)
    e = int((end - guard) * rate)
    return float(np.sqrt(np.mean(np.square(data[s:e]))))

# --- a backend that needs no model weights ------------------------------------------
#
# `JobStore` takes a backend factory, so the whole state machine and the HTTP API can be
# driven without loading Demucs or Parakeet. The fake is deliberately honest: it derives
# the instrumental as `mix - vocals`, exactly like the real one.

_SONG_WORDS = ("we", "run", "the", "night", "zzapp", "again", "and", "stay")


class FakeBackend:
    """Stands in for `LocalBackend`: writes stems and returns a fixed transcript."""

    def __init__(self, job_dir: Path, words: tuple[str, ...] = _SONG_WORDS) -> None:
        self.job_dir = Path(job_dir)
        self.words = words

    def separate(
        self,
        audio_path: Path,
        stems: tuple[str, ...],
        quality: str,
        on_progress: ProgressFn | None = None,
    ) -> dict[str, Path]:
        mix, rate = read(audio_path)
        # A vocal stem that is a quarter of the mix: enough for the mask and the RMS tail
        # extension to have something real to work with.
        vocals = (mix * 0.25).astype(np.float32)
        written = {"vocals": self.job_dir / "vocals.wav"}
        write(written["vocals"], vocals, rate, config.FLAC_SUBTYPE)
        if "instrumental" in stems:
            instrumental = mix - vocals
            written["instrumental"] = self.job_dir / "instrumental.wav"
            write(written["instrumental"], instrumental, rate, config.FLAC_SUBTYPE)
        for report in (5, 90, 100):
            if on_progress is not None:
                on_progress(float(report), "fake separation")
        return written

    def transcribe(
        self, vocal_path: Path, on_progress: ProgressFn | None = None
    ) -> list[Word]:
        duration = duration_seconds(vocal_path)
        step = duration / (len(self.words) + 1)
        found = [
            Word(
                text=text,
                start=round((index + 1) * step, 3),
                end=round((index + 1) * step + step * 0.6, 3),
                confidence=0.9,
                source=SOURCE_ASR,
            )
            for index, text in enumerate(self.words)
        ]
        if on_progress is not None:
            on_progress(100.0, "fake transcription")
        return found


@pytest.fixture
def song(tmp_path: Path) -> Path:
    """A short synthetic song on disk, tagged so lyrics lookup has something to read."""
    instrumentals = stereo(tone(110.0, 4.0, amp=0.25))
    vocals = np.zeros_like(instrumentals)
    vocals[:, 0] += burst(440.0, 0.5, 0.4, amp=0.45, total=4.0)
    vocals[:, 0] += burst(660.0, 2.0, 0.5, amp=0.45, total=4.0)
    wav = tmp_path / "source.wav"
    write(wav, instrumentals + vocals, RATE, "PCM_16")
    path = tmp_path / "fake song.m4a"
    _transcode(wav, path)
    return path


def _transcode(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:a", "aac", str(dst)],
        capture_output=True,
        check=True,
    )


@pytest.fixture
def fake_backend():
    return lambda job_dir: FakeBackend(job_dir)


# --- a test-only word list ----------------------------------------------------------
#
# AGENTS.md rule 7: unit tests must use innocuous placeholder words, never real profanity.
# So the shipped list is stubbed out for anything that goes through the detector by
# default, and these invented words take its place.
TEST_PROFANE = frozenset({"zzapp", "snork", "blorp"})
TEST_ALLOWED = frozenset({"wibble"})


@pytest.fixture
def test_wordlist(monkeypatch: pytest.MonkeyPatch) -> frozenset[str]:
    """Make `detect` see only the placeholder words above."""
    monkeypatch.setattr(
        "censorflow.profanity.detect._cached_wordlist",
        lambda extra=None, allow=None: (TEST_PROFANE, TEST_ALLOWED),
    )
    return TEST_PROFANE
