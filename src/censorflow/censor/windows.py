"""Build censor windows and the vocal-subtraction mask.

A window must cover the sung syllable, then stop. Official Apple Music cleans of the
same master duck only the vocal for ~90–170 ms and leave the beat; padding and the
minimum length are sized to that punch. A modest RMS tail still covers a stretched vowel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .. import config

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Window:
    """A censor window in seconds, before or after merging."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def short_time_rms(vocals: np.ndarray, sample_rate: int) -> tuple[np.ndarray, float]:
    """Frame RMS of a mono float signal, plus the hop in seconds.

    20 ms window, 10 ms hop, per `AGENTS.md`. Padding is appended so the final partial
    frame is still measured, which matters for a word near the end of the track.
    """
    if vocals.ndim > 1:
        vocals = vocals.mean(axis=1)
    win = max(1, round(config.RMS_WINDOW_MS / 1000 * sample_rate))
    hop = max(1, round(config.RMS_HOP_MS / 1000 * sample_rate))
    if len(vocals) < win:
        vocals = np.pad(vocals, (0, win - len(vocals)))
    n_frames = 1 + (len(vocals) - win) // hop
    frames = np.lib.stride_tricks.as_strided(
        vocals, shape=(n_frames, win), strides=(vocals.strides[0] * hop, vocals.strides[0])
    )
    return np.sqrt(np.mean(np.square(frames), axis=1)), hop / sample_rate


def extend_tail(
    start: float,
    end: float,
    rms: np.ndarray,
    hop_s: float,
    *,
    limit: float,
) -> float:
    """Extend `end` forward while the vocal is still sounding.

    `word_peak` is the max frame RMS inside the word; we extend while frames stay at or
    above `RMS_TAIL_FRACTION` of that peak. Stops after `RMS_TAIL_QUIET_MS` of quiet, at
    `MAX_TAIL_MS`, or at `limit` (the next word's start) whichever comes first.
    """
    if len(rms) == 0:
        return end

    first = int(np.floor(start / hop_s))
    last = int(np.ceil(end / hop_s))
    first, last = max(0, first), min(len(rms) - 1, max(first, last))
    inside = rms[first : last + 1]
    peak = float(inside.max()) if len(inside) else 0.0
    if peak <= 0.0:
        return end  # silence: nothing to cover

    threshold = config.RMS_TAIL_FRACTION * peak
    quiet_needed = max(1, round(config.RMS_TAIL_QUIET_MS / 1000 / hop_s))
    hard_cap = min(end + config.MAX_TAIL_MS / 1000, limit)

    i = last + 1
    quiet_run = 0
    while i < len(rms) and (i * hop_s) < hard_cap:
        if rms[i] >= threshold:
            quiet_run = 0
            i += 1
            continue
        quiet_run += 1
        if quiet_run >= quiet_needed:
            break
        i += 1

    # Back off the frames that were only counted as trailing quiet.
    extended_end = (i - quiet_run) * hop_s
    return float(min(extended_end, hard_cap))


def snap_to_vocal(
    start: float,
    end: float,
    rms: np.ndarray,
    hop_s: float,
) -> tuple[float, float]:
    """Recentre a short estimate on the vocal peak within `SNAP_RADIUS_MS`.

    Lyrics-only times are a gap between neighbours, not a syllable. If a clearly
    louder frame sits just beside the estimate, the punch belongs there. The
    radius stays inside one syllable so a louder word further along is left alone.
    """
    if hop_s <= 0 or len(rms) == 0:
        return start, end
    # The loudest frame of a long word is a later syllable. Shifting the whole
    # span onto it uncovers the onset, which is where the beginning leaks.
    if end - start > config.SNAP_LONG_SPAN_S:
        return start, end
    centre = (start + end) / 2
    index = round(centre / hop_s)
    index = min(max(index, 0), len(rms) - 1)
    radius = max(1, round(config.SNAP_RADIUS_MS / 1000 / hop_s))
    lo, hi = max(0, index - radius), min(len(rms) - 1, index + radius)
    peak = lo + int(np.argmax(rms[lo : hi + 1]))
    if rms[peak] < config.SNAP_PEAK_RATIO * max(float(rms[index]), 1e-8):
        return start, end
    new_centre = peak * hop_s
    half = (end - start) / 2
    return new_centre - half, new_centre + half


def build_window(
    start: float,
    end: float,
    *,
    rms: np.ndarray | None = None,
    hop_s: float = 0.01,
    next_word_start: float | None = None,
) -> Window:
    """Build one window from a word's timing, extending the tail when energy supports it."""
    limit = float("inf")
    if next_word_start is not None:
        limit = next_word_start - config.NEXT_WORD_GUARD_MS / 1000

    if rms is not None and len(rms):
        start, end = snap_to_vocal(start, end, rms, hop_s)
        end = max(end, start)
        end = extend_tail(start, end, rms, hop_s, limit=limit)
    else:
        end = min(end, limit)

    centre = (start + end) / 2
    start -= config.PAD_PRE_MS / 1000
    end += config.PAD_POST_MS / 1000

    # Floor the length, grown symmetrically about the word centre. Padding is asymmetric,
    # so the centre has to be captured before it is applied.
    if (end - start) * 1000 < config.MIN_WINDOW_MS:
        half = config.MIN_WINDOW_MS / 2000
        start, end = centre - half, centre + half

    if next_word_start is not None:
        end = min(end, next_word_start)
    # After the detected span is padded and floored. Moving the start earlier
    # here is the systematic correction: the clock is late, the end is not.
    start -= config.CENSOR_LEAD_MS / 1000
    return Window(start=max(0.0, start), end=max(end, start + 1e-4))


def build_windows(
    words: list[tuple[float, float]],
    *,
    rms: np.ndarray | None = None,
    hop_s: float = 0.01,
) -> list[Window]:
    """Build windows for (start, end) pairs in transcript order, then merge overlaps."""
    starts = [w[0] for w in words]
    windows = []
    for i, (start, end) in enumerate(words):
        nxt = None
        for later in starts[i + 1 :]:
            if later > start:
                nxt = later
                break
        windows.append(build_window(start, end, rms=rms, hop_s=hop_s, next_word_start=nxt))
    return merge_windows(windows)


def merge_windows(windows: list[Window], gap_ms: float = config.MERGE_GAP_MS) -> list[Window]:
    """Merge windows separated by less than `gap_ms`, so no audible sliver survives."""
    if not windows:
        return []
    ordered = sorted(windows, key=lambda w: w.start)
    gap = gap_ms / 1000
    merged = [ordered[0]]
    for w in ordered[1:]:
        last = merged[-1]
        if w.start - last.end <= gap:
            merged[-1] = Window(last.start, max(last.end, w.end))
        else:
            merged.append(w)
    return merged


def build_mask(
    shape: tuple[int, int], windows: list[Window], sample_rate: int, fade_ms: float = config.FADE_MS
) -> np.ndarray:
    """Float mask, 1 inside windows with raised-cosine edges, 0 elsewhere.

    Kept float (not bool) so the ramps are smooth: a hard edge on a subtraction
    produces an audible click.
    """
    frames = shape[0]
    mask = np.zeros(frames, dtype=np.float32)
    fade = max(1, round(fade_ms / 1000 * sample_rate))
    for w in windows:
        s = max(0, round(w.start * sample_rate))
        e = min(frames, round(w.end * sample_rate))
        if e <= s:
            continue
        segment = np.ones(e - s, dtype=np.float32)
        ramp_len = min(fade, (e - s) // 2)
        if ramp_len > 0:
            ramp = 0.5 * (1 - np.cos(np.pi * np.arange(ramp_len) / ramp_len))
            segment[:ramp_len] = ramp
            segment[-ramp_len:] = ramp[::-1]
        mask[s:e] = np.maximum(mask[s:e], segment)
    return mask


def render(
    mix: np.ndarray,
    vocals: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """The product rule: subtract only the vocals inside the mask.

    `final = mix - vocals * mask`. Outside the windows the mask is exactly 0.0, so the
    output is bit-identical to the input there rather than merely close.
    """
    if len(vocals) != len(mix):
        raise ValueError(f"vocal stem has {len(vocals)} frames, mix has {len(mix)}")
    if mask.shape[0] != len(mix):
        raise ValueError(f"mask has {mask.shape[0]} samples, mix has {len(mix)}")
    gated = vocals * mask[:, None]
    return (mix - gated).astype(np.float32, copy=False)


def windows_to_json(windows: list[Window]) -> list[dict[str, float]]:
    return [{"start": round(w.start, 4), "end": round(w.end, 4)} for w in windows]