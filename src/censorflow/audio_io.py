"""ffprobe/ffmpeg decode, encode and clip extraction.

Everything is validated with ffprobe rather than trusted from the file extension, so any
container ffmpeg can read is accepted. All internal audio is 44.1 kHz stereo float32.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config

logger = logging.getLogger(__name__)


class AudioError(RuntimeError):
    """Raised with a message meant to be shown to the user."""


def check_ffmpeg() -> None:
    """Fail early with an actionable message if ffmpeg or ffprobe is missing."""
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise AudioError(
                f"{tool} is not installed. CensorFlow needs it to read and write audio. "
                "Install it with:  brew install ffmpeg"
            )


def probe(path: Path) -> dict[str, object]:
    """Return ffprobe's JSON description of `path`, or raise AudioError."""
    if not Path(path).exists():
        raise AudioError(f"No such file: {path}")
    check_ffmpeg()
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        raise AudioError(
            f"Could not read {Path(path).name}. ffmpeg says: "
            f"{detail[-1] if detail else 'unknown error'}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"Timed out reading {Path(path).name}.") from exc
    return json.loads(proc.stdout)


def has_audio_stream(path: Path) -> bool:
    """True if the file contains at least one decodable audio stream.

    A file ffprobe refuses to read at all has no audio in it, so it answers False rather
    than raising: callers use this to turn "not a song" into a friendly refusal.
    """
    try:
        info = probe(path)
    except AudioError:
        return False
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


def duration_seconds(path: Path) -> float:
    """Container duration in seconds, preferring the audio stream's own value."""
    info = probe(path)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio" and stream.get("duration"):
            return float(stream["duration"])
    raw = info.get("format", {}).get("duration")
    return float(raw) if raw else 0.0


def decode(
    src: Path,
    dst: Path,
    *,
    sample_rate: int = config.SAMPLE_RATE,
    channels: int = config.CHANNELS,
    start: float | None = None,
    duration: float | None = None,
) -> Path:
    """Decode `src` to a PCM WAV at the working format via ffmpeg.

    Returns `dst`. When `start`/`duration` are given, only that region is decoded,
    which is how `--clip-seconds` keeps iteration fast.
    """
    check_ffmpeg()
    if not has_audio_stream(src):
        raise AudioError(f"{Path(src).name} has no audio stream that ffmpeg can read.")

    cmd = ["ffmpeg", "-v", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, start):.3f}"]
    cmd += ["-i", str(src)]
    if duration is not None:
        cmd += ["-t", f"{max(0.0, duration):.3f}"]
    cmd += [
        "-vn", "-ac", str(channels), "-ar", str(sample_rate),
        "-c:a", "pcm_f32le", str(dst),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        raise AudioError(f"Could not decode {Path(src).name}: {detail[-1] if detail else exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"Decoding {Path(src).name} timed out.") from exc
    logger.info("decoded %s -> %s (%.1fs)", src.name, dst.name, duration_seconds(dst))
    return dst


def read(path: Path) -> tuple[np.ndarray, int]:
    """Read an audio file as float32 samples shaped (frames, channels)."""
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    return data, rate


def write(path: Path, data: np.ndarray, sample_rate: int, subtype: str) -> Path:
    """Write float32 (frames, channels) samples to `path` with the given subtype."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(data, dtype=np.float32), sample_rate, subtype=subtype)
    return path


def to_wav_bytes(
    data: np.ndarray, sample_rate: int, subtype: str = config.WAV_SUBTYPE
) -> bytes:
    """Encode samples as an in-memory WAV, for HTTP responses that never touch disk."""
    buffer = io.BytesIO()
    sf.write(
        buffer, np.asarray(data, dtype=np.float32), sample_rate, subtype=subtype, format="WAV"
    )
    return buffer.getvalue()


def to_mono16k(path: Path, dst: Path) -> Path:
    """Produce the mono 16 kHz copy the ASR model expects."""
    check_ffmpeg()
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn",
        "-ac", str(config.ASR_CHANNELS), "-ar", str(config.ASR_SAMPLE_RATE),
        "-c:a", "pcm_s16le", str(dst),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        raise AudioError(f"Could not resample for speech recognition: {detail[-1] if detail else exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError("Resampling for speech recognition timed out.") from exc
    return dst


def encode(src: Path, dst: Path, fmt: str, *, bitrate: str = config.MP3_BITRATE) -> Path:
    """Export to flac/wav/mp3. Lossless by default; see config.EXPORT_FORMATS."""
    fmt = fmt.lower().lstrip(".")
    if fmt not in config.SUPPORTED_EXPORT_FORMATS:
        raise AudioError(
            f"Unsupported export format {fmt!r}. Use one of: "
            f"{', '.join(config.SUPPORTED_EXPORT_FORMATS)}."
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    if fmt in ("flac", "wav"):
        data, rate = read(src)
        subtype = config.FLAC_SUBTYPE if fmt == "flac" else config.WAV_SUBTYPE
        write(dst, data, rate, subtype)
        return dst
    check_ffmpeg()
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", bitrate, str(dst)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise AudioError(f"Could not write {dst.name}: {exc}") from exc
    return dst


def match_length(data: np.ndarray, target_frames: int, source_len: int | None = None) -> np.ndarray:
    """Pad with zeros or trim so `data` has exactly `target_frames` frames.

    Separation output should already line up with the mix; this only guards against
    off-by-a-few drift. Differences within `STEM_LENGTH_TOLERANCE_SAMPLES` are expected
    and silent; anything larger is logged as a warning.
    """
    frames = len(data)
    if frames == target_frames:
        return data
    drift = abs(frames - target_frames)
    if drift > config.STEM_LENGTH_TOLERANCE_SAMPLES:
        logger.warning(
            "stem length %d differs from mix length %d by %d samples (> tolerance %d)",
            frames, target_frames, drift, config.STEM_LENGTH_TOLERANCE_SAMPLES,
        )
    if frames > target_frames:
        return data[:target_frames]
    pad = np.zeros((target_frames - frames, data.shape[1]), dtype=data.dtype)
    return np.concatenate([data, pad], axis=0)