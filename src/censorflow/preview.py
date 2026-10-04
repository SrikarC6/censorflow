"""Region-only rendering for the review screen's per-flag A/B preview.

Not named in `AGENTS.md`; the split is recorded in `docs/DECISIONS.md`. It lives apart from
`server.py` because the interesting part is the audio, not the HTTP: the same subtraction
the final render uses, applied to a few seconds only, so what the user hears while deciding
is exactly what they will get.

Nothing here touches the disk beyond reading the job's `mix.wav` and `vocals.wav`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from . import audio_io, config, review
from .censor import render as render_mod
from .review import JobError, censor_spans

if TYPE_CHECKING:
    from .jobs import Job

logger = logging.getLogger(__name__)

# A clip shorter than this is a click, not a preview.
MIN_REGION_S = 0.05


def resolve_region(job: Job, start: float, end: float) -> tuple[float, float]:
    """Clamp a requested clip to the audio that actually exists."""
    duration = review.duration_of(job)
    if end <= start:
        raise JobError("end must be greater than start")
    lo = max(0.0, min(start, duration))
    hi = max(lo, min(end, duration))
    if hi - lo < MIN_REGION_S:
        raise JobError("that clip is too short to play")
    return lo, hi


def padded_region(job: Job, flag_index: int) -> tuple[float, float]:
    """The preview window for one flag: the word plus `PREVIEW_PAD_S` either side."""
    flag = job.flags[flag_index]
    return (
        max(0.0, flag.start - config.PREVIEW_PAD_S),
        flag.end + config.PREVIEW_PAD_S,
    )


def region_audio(job: Job, kind: str, start: float, end: float) -> np.ndarray:
    """Render [start, end) of the mix, with or without the censor mask applied."""
    if kind not in {"original", "censored"}:
        raise JobError("kind must be original or censored")
    mix, rate = audio_io.read(job.mix_path)
    if kind == "original":
        lo = round(start * rate)
        return mix[lo : min(len(mix), round(end * rate))]

    vocals, vocal_rate = audio_io.read(job.vocals_path)
    if rate != vocal_rate:  # pragma: no cover - the pipeline asserts this already
        raise audio_io.AudioError("the mix and the vocal stem disagree about the sample rate")
    _windows, mask = render_mod.build_from_flags(censor_spans(job), vocals, rate)
    return render_mod.render_region(mix, vocals, mask, start, end, rate)


def wav_response(audio: np.ndarray, rate: int) -> tuple[bytes, str]:
    """Encode a preview as WAV bytes plus the media type to serve them with."""
    return audio_io.to_wav_bytes(audio, rate), "audio/wav"