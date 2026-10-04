"""Input format handling: anything ffmpeg can read must decode to the working format."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from censorflow import audio_io, config

# (suffix, ffmpeg encoder arguments)
CONTAINERS = [
    ("flac", ["-c:a", "flac"]),
    ("mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
    ("m4a", ["-c:a", "aac", "-b:a", "192k"]),
    ("ogg", ["-c:a", "vorbis", "-strict", "-2"]),
    ("opus", ["-c:a", "libopus"]),
    ("aiff", ["-c:a", "pcm_s16be"]),
    ("wma", ["-c:a", "wmav2", "-b:a", "192k"]),
]

FREQ = 440.0
SECONDS = 1.0


@pytest.fixture(scope="module")
def source_wav(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("audio") / "source.wav"
    t = np.arange(int(SECONDS * config.SAMPLE_RATE), dtype=np.float32) / config.SAMPLE_RATE
    tone = (0.5 * np.sin(2 * np.pi * FREQ * t)).astype(np.float32)
    audio_io.write(path, np.repeat(tone[:, None], 2, axis=1), config.SAMPLE_RATE, "PCM_16")
    return path


def _make_container(src: Path, suffix: str, args: list[str]) -> Path:
    dst = src.with_name(f"source.{suffix}")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", *args, str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dst.exists():
        pytest.skip(f"ffmpeg cannot write {suffix} here: {proc.stderr.strip()[:120]}")
    return dst


def _dominant_freq(data: np.ndarray, rate: int) -> float:
    """Frequency of the loudest partial, over as much of the signal as is available."""
    mono = data.mean(axis=1)[:rate]
    windowed = mono * np.hanning(len(mono))
    spectrum = np.abs(np.fft.rfft(windowed))
    return float(np.fft.rfftfreq(len(mono), d=1.0 / rate)[np.argmax(spectrum)])


@pytest.mark.parametrize(("suffix", "args"), CONTAINERS, ids=[c[0] for c in CONTAINERS])
def test_every_container_decodes_to_the_working_format(source_wav, tmp_path, suffix, args):
    container = _make_container(source_wav, suffix, args)
    assert audio_io.has_audio_stream(container)

    decoded = audio_io.decode(container, tmp_path / "out.wav")
    data, rate = audio_io.read(decoded)

    assert rate == config.SAMPLE_RATE
    assert data.shape[1] == config.CHANNELS
    assert data.dtype == np.float32
    assert abs(len(data) / rate - SECONDS) < 0.25, f"{suffix} decoded to the wrong duration"
    assert abs(_dominant_freq(data, rate) - FREQ) < 10, f"{suffix} lost the tone"


def test_lossless_wav_input_needs_no_transcoding(source_wav, tmp_path):
    """The WAV path is the one users hit when they already have PCM audio."""
    data, rate = audio_io.read(audio_io.decode(source_wav, tmp_path / "copy.wav"))
    assert rate == config.SAMPLE_RATE
    assert data.shape[1] == config.CHANNELS
    assert abs(_dominant_freq(data, rate) - FREQ) < 10


def test_clip_extraction_keeps_only_the_requested_region(source_wav, tmp_path):
    out = audio_io.decode(source_wav, tmp_path / "clip.wav", start=0.25, duration=0.5)
    data, rate = audio_io.read(out)
    assert abs(len(data) / rate - 0.5) < 0.05


def test_probe_and_duration(source_wav):
    info = audio_io.probe(source_wav)
    assert any(s.get("codec_type") == "audio" for s in info["streams"])
    assert abs(audio_io.duration_seconds(source_wav) - SECONDS) < 0.05


def test_missing_file_raises_a_friendly_error(tmp_path):
    with pytest.raises(audio_io.AudioError, match="No such file"):
        audio_io.probe(tmp_path / "nope.mp3")


def test_unsupported_export_format_is_rejected(source_wav, tmp_path):
    with pytest.raises(audio_io.AudioError, match="Unsupported export format"):
        audio_io.encode(source_wav, tmp_path / "out.aiff", "aiff")


@pytest.mark.parametrize("fmt", config.SUPPORTED_EXPORT_FORMATS)
def test_export_round_trip(source_wav, tmp_path, fmt):
    out = audio_io.encode(source_wav, tmp_path / f"out.{fmt}", fmt)
    assert out.exists() and out.stat().st_size > 0
    assert abs(audio_io.duration_seconds(out) - SECONDS) < 0.25


def test_mono16k_conversion(source_wav, tmp_path):
    out = audio_io.to_mono16k(source_wav, tmp_path / "mono16k.wav")
    info = audio_io.probe(out)
    stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert stream["sample_rate"] == str(config.ASR_SAMPLE_RATE)
    assert stream["channels"] == 1


def test_match_length_pads_and_trims():
    data = np.ones((100, 2), dtype=np.float32)
    assert audio_io.match_length(data, 150).shape == (150, 2)
    assert audio_io.match_length(data, 150)[100:].sum() == 0.0
    assert audio_io.match_length(data, 50).shape == (50, 2)
    assert audio_io.match_length(data, 100) is data