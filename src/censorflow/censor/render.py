"""Render the censored output: windows -> mask -> subtraction -> export.

`AGENTS.md` rule 1 is enforced here: the full mix is never silenced, only the vocal stem
inside the censor windows is removed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import audio_io, config, metadata
from . import windows as win

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RenderStats:
    """What the result screen reports."""

    word_count: int
    window_count: int
    muted_seconds: float
    output_path: Path
    # The merged windows actually used, so callers can persist them instead of rebuilding.
    windows: list[win.Window] = field(default_factory=list)
    # Samples that exceeded full scale and were clamped on export. See
    # `clamp_to_full_scale`: this is a property of integer audio formats, not of the render.
    clipped_samples: int = 0


def clamp_to_full_scale(data: np.ndarray) -> tuple[np.ndarray, int]:
    """Clamp to [-1, 1] and report how many samples needed it.

    Lossless output here means FLAC 24-bit, which is an integer format and therefore cannot
    hold a sample above full scale. Decoded mixes do go above it: one real track peaked at
    1.089, with 0.055 % of samples over 1.0. Left alone, libsndfile clamps them silently and
    the exported file then differs from the input outside the censor windows, which would
    quietly break `AGENTS.md` rule 1 at the file level even though the render is exact.

    Clamping here makes the step deliberate and visible: it happens in one place, it is
    logged, and it is the same thing a playback device would do to those peaks anyway.
    """
    if data.size == 0:
        return data, 0
    peak = float(np.abs(data).max())
    if peak <= 1.0:
        return data, 0
    over = int(np.count_nonzero(np.abs(data) > 1.0))
    logger.warning(
        "clamping %d sample(s) (%.3f%%) that exceeded full scale; loudest was %+.4f",
        over, 100 * over / data.size, peak,
    )
    return np.clip(data, -1.0, 1.0).astype(np.float32, copy=False), over


def build_from_flags(
    spans: list[tuple[float, float]],
    vocals: np.ndarray,
    sample_rate: int,
) -> tuple[list[win.Window], np.ndarray]:
    """Build windows for (start, end) spans and the matching mask for `vocals`.

    Spans must already be in ascending order with no duplicates: `next_word` guarding is
    derived from position, so unsorted input would silently mis-cap a tail.
    """
    rms, hop_s = win.short_time_rms(vocals, sample_rate)
    built = win.build_windows(spans, rms=rms, hop_s=hop_s)
    mask = win.build_mask(vocals.shape, built, sample_rate)
    return built, mask


def render_to_file(
    mix_path: Path,
    vocals_path: Path,
    spans: list[tuple[float, float]],
    output_path: Path,
    *,
    export_format: str = config.DEFAULT_EXPORT_FORMAT,
    bitrate: str = config.MP3_BITRATE,
    tags_from: Path | None = None,
) -> RenderStats:
    """Produce the censored file at `output_path` and keep `tags_from`'s tags on it.

    `spans` are (start, end) seconds in ascending order. Returns stats for the UI.
    """
    mix, rate = audio_io.read(mix_path)
    vocals, vrate = audio_io.read(vocals_path)
    if rate != vrate:
        raise audio_io.AudioError(
            f"mix is {rate} Hz but vocal stem is {vrate} Hz; they must match"
        )
    if not spans:
        logger.info("no censor windows; exporting the mix unchanged")

    built, mask = build_from_flags(spans, vocals, rate)
    vocals = audio_io.match_length(vocals, len(mix), source_len=len(vocals))
    if len(mask) != len(mix):
        mask = mask[: len(mix)]
    final = win.render(mix, vocals, mask)
    final, clipped = clamp_to_full_scale(final)

    staged = output_path.with_suffix(".staged.wav")
    audio_io.write(staged, final, rate, config.FLAC_SUBTYPE)
    audio_io.encode(staged, output_path, export_format, bitrate=bitrate)
    staged.unlink(missing_ok=True)
    if tags_from is not None:
        metadata.copy_metadata(tags_from, output_path)

    muted = float(np.count_nonzero(mask) / rate)
    logger.info(
        "rendered %d windows covering %.2fs of %.2fs -> %s",
        len(built), muted, len(mix) / rate, output_path.name,
    )
    return RenderStats(
        word_count=len(spans),
        window_count=len(built),
        muted_seconds=round(muted, 3),
        output_path=output_path,
        windows=built,
        clipped_samples=clipped,
    )


def render_region(
    mix: np.ndarray,
    vocals: np.ndarray,
    mask: np.ndarray,
    start: float,
    end: float,
    sample_rate: int,
) -> np.ndarray:
    """Render only [start, end) for the review screen's per-flag A/B preview.

    The same subtraction is applied, so what the user hears is exactly what the final
    render will produce in that region.
    """
    s = max(0, round(start * sample_rate))
    e = min(len(mix), round(end * sample_rate))
    if e <= s:
        return np.zeros((0, mix.shape[1]), dtype=np.float32)
    return win.render(mix[s:e], vocals[s:e], mask[s:e])