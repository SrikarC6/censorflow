"""Synthetic audio fixtures. Tests never touch real music; see AGENTS.md rule 7."""

from __future__ import annotations

import numpy as np
import pytest

from censorflow import config

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