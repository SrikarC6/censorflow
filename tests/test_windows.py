"""Censor window geometry: tail extension, padding, floor, merging."""

from __future__ import annotations

import numpy as np

from censorflow import config
from censorflow.censor import windows as win

from .conftest import RATE, burst, stereo, tone


def _rms_of(mono: np.ndarray) -> tuple[np.ndarray, float]:
    return win.short_time_rms(mono, RATE)


def test_short_time_rms_shape_and_levels():
    # 250 Hz puts exactly five whole cycles in every 20 ms frame, so the level is stable.
    frames, hop_s = _rms_of(stereo(tone(250.0, 1.0, amp=0.5))[:, 0])
    assert hop_s == config.RMS_HOP_MS / 1000
    assert 98 <= len(frames) <= 101
    assert np.allclose(frames, 0.5 / np.sqrt(2), atol=1e-3)


def test_short_time_rms_mono_a_stereo_signal():
    left = stereo(tone(250.0, 0.5, amp=0.4))[:, 0]
    frames, _ = win.short_time_rms(np.repeat(left[:, None], 2, axis=1), RATE)
    assert np.allclose(frames[:5], 0.4 / np.sqrt(2), atol=1e-3)


def test_window_has_the_minimum_length():
    # A 10 ms word still gets MIN_WINDOW_MS, grown symmetrically about its centre.
    w = win.build_window(2.0, 2.01)
    assert round(w.duration * 1000) == config.MIN_WINDOW_MS
    assert abs((w.start + w.end) / 2 - 2.005) < 0.001


def test_padding_is_applied():
    w = win.build_window(2.0, 2.5)
    assert abs(w.start - (2.0 - config.PAD_PRE_MS / 1000)) < 1e-6
    assert abs(w.end - (2.5 + config.PAD_POST_MS / 1000)) < 1e-6


def test_stretched_tail_is_covered_up_to_the_cap():
    """A modest sung tail after the ASR end is still covered; a long howl is not.

    The ASR says the word ended at 1.5 s; energy continues to 1.65 s (150 ms),
    which is inside MAX_TAIL_MS.
    """
    vocals = burst(440.0, 1.0, 0.65, amp=0.5)
    rms, hop_s = _rms_of(vocals)
    w = win.build_window(1.0, 1.5, rms=rms, hop_s=hop_s)
    assert w.end >= 1.65, f"tail left uncovered: window ends at {w.end:.3f}s"


def test_syllable_punch_stays_short():
    """An 80 ms token plus pads should stay in Apple-clean punch range, not 250+ ms."""
    w = win.build_window(2.00, 2.08)
    dur_ms = w.duration * 1000
    assert dur_ms <= 160
    assert dur_ms >= config.MIN_WINDOW_MS


def test_tail_extension_stops_at_silence():
    vocals = burst(440.0, 1.0, 0.2, amp=0.5)
    rms, hop_s = _rms_of(vocals)
    w = win.build_window(1.0, 1.1, rms=rms, hop_s=hop_s)
    # The burst ends at 1.2 s; a few ms of slack is expected, a long tail is not.
    assert 1.2 <= w.end <= 1.2 + 4 * config.RMS_TAIL_QUIET_MS / 1000


def test_extension_never_crosses_the_next_word():
    vocals = burst(440.0, 1.0, 1.5, amp=0.5)  # one long sustained note
    rms, hop_s = _rms_of(vocals)
    w = win.build_window(1.0, 1.2, rms=rms, hop_s=hop_s, next_word_start=1.6)
    assert w.end <= 1.6
    assert w.end >= 1.2


def test_extension_is_capped_by_max_tail():
    vocals = burst(440.0, 1.0, 3.0, amp=0.5)
    rms, hop_s = _rms_of(vocals)
    w = win.build_window(1.0, 1.1, rms=rms, hop_s=hop_s)
    post = config.PAD_POST_MS / 1000
    assert w.end <= 1.1 + config.MAX_TAIL_MS / 1000 + post + 0.02


def test_silence_never_extends():
    rms, hop_s = _rms_of(np.zeros(int(RATE * 2), dtype=np.float32))
    w = win.build_window(0.5, 0.6, rms=rms, hop_s=hop_s)
    assert abs(w.end - (0.6 + config.PAD_POST_MS / 1000)) < 1e-6


def test_close_windows_merge():
    # 20 ms apart, inside MERGE_GAP_MS, so no sliver of vocal survives between them.
    merged = win.merge_windows([win.Window(1.0, 1.2), win.Window(1.22, 1.5)])
    assert len(merged) == 1
    assert merged[0].start == 1.0 and merged[0].end == 1.5


def test_distant_windows_stay_separate():
    kept = win.merge_windows([win.Window(1.0, 1.2), win.Window(4.0, 4.2)])
    assert len(kept) == 2


def test_merge_handles_overlaps_and_order():
    merged = win.merge_windows([win.Window(4.0, 4.2), win.Window(1.0, 1.2), win.Window(1.15, 1.4)])
    assert [(round(w.start, 2), round(w.end, 2)) for w in merged] == [(1.0, 1.4), (4.0, 4.2)]


def test_build_windows_uses_the_next_word_as_a_guard():
    vocals = burst(440.0, 1.0, 0.3, amp=0.5, total=5.0)
    vocals += burst(440.0, 1.45, 0.3, amp=0.5, total=5.0)
    rms, hop_s = _rms_of(vocals)
    built = win.build_windows([(1.0, 1.2), (1.45, 1.6)], rms=rms, hop_s=hop_s)
    assert len(built) == 2, "the two words are far enough apart to stay separate"
    assert built[0].end <= 1.45, "the first window swallowed the next word"


def test_build_window_clamps_at_zero():
    w = win.build_window(0.0, 0.05)
    assert w.start == 0.0
    assert w.end > 0.0


def test_mask_is_zero_where_there_are_no_windows():
    mask = win.build_mask((int(RATE * 3), 2), [win.Window(1.0, 1.4)], RATE)
    assert np.all(mask[: int(0.95 * RATE)] == 0.0)
    assert np.all(mask[int(1.5 * RATE) :] == 0.0)
    assert mask.max() == 1.0