"""Rule 1: `final = mix - vocals * mask`. Only the vocals inside a window go away.

This is the test AGENTS.md requires. It fails loudly if anyone ever silences the mix,
or starts muting audio outside the censor windows.
"""

from __future__ import annotations

import numpy as np

from censorflow import audio_io, config
from censorflow.censor import render as censor_render
from censorflow.censor import windows as win

from .conftest import RATE, rms

SPANS = [(1.0, 1.5), (3.0, 3.7)]


def _render(stems: dict[str, np.ndarray], spans=SPANS):
    """The production path: spans -> windows -> mask -> subtraction."""
    built, mask = censor_render.build_from_flags(spans, stems["vocals"], RATE)
    return built, mask, win.render(stems["mix"], stems["vocals"], mask)


def test_output_outside_windows_is_identical_to_the_mix(stems):
    _, mask, final = _render(stems)
    outside = mask == 0.0
    assert outside.any(), "the mask left nothing outside the windows"
    # Bit-identical, not merely close: subtracting a zero mask is exact.
    assert np.array_equal(final[outside], stems["mix"][outside])


def test_instrumental_keeps_playing_inside_the_window(stems):
    _, _, final = _render(stems)
    for start, end in SPANS:
        before = rms(stems["mix"], start, end)
        after = rms(final, start, end)
        assert after > 0.5 * before, f"music was silenced between {start}s and {end}s"


def test_vocal_is_gone_inside_the_window(stems):
    _, _, final = _render(stems)
    for start, end in SPANS:
        assert rms(stems["vocals"], start, end) > 0.1, "fixture has no vocal there to remove"
        leftover = rms(final, start, end) - rms(stems["instrumentals"], start, end)
        assert leftover < 0.01, f"vocal still audible between {start}s and {end}s"


def test_inside_window_equals_the_instrumental_alone(stems):
    """Subtraction must not touch the instrumental, only the vocal."""
    built, _, final = _render(stems)
    s = int(built[0].start * RATE) + 2000
    e = int(built[0].end * RATE) - 2000
    residual = np.abs(final[s:e] - stems["instrumentals"][s:e])
    assert np.max(residual) < 1e-6, "render changed the instrumental"


def test_mask_edges_are_smooth_ramps(stems):
    built, mask, _ = _render(stems)
    fade = max(1, int(config.FADE_MS / 1000 * RATE))
    s = round(built[0].start * RATE)
    assert mask[s] == 0.0, "mask jumps straight to full depth"
    assert np.all(np.diff(mask[s : s + fade]) >= 0), "attack is not monotonic"
    assert np.all(np.diff(mask[s + fade : s + 2 * fade]) <= 0), "release is not monotonic"
    assert mask[s + 2 * fade] == 1.0, "mask never reaches full depth"


def test_render_rejects_mismatched_lengths(stems):
    mask = np.zeros(len(stems["mix"]), dtype=np.float32)
    with np.testing.assert_raises(ValueError):
        win.render(stems["mix"], stems["vocals"][:-10], mask)


def test_render_of_no_windows_is_the_mix(stems):
    mask = win.build_mask(stems["mix"].shape, [], RATE)
    final = win.render(stems["mix"], stems["vocals"], mask)
    assert np.array_equal(final, stems["mix"])


def test_clamping_leaves_an_in_range_signal_untouched(stems):
    clamped, count = censor_render.clamp_to_full_scale(stems["mix"])
    assert count == 0
    assert np.array_equal(clamped, stems["mix"])


def test_clamping_bounds_an_over_full_scale_signal(stems):
    """FLAC 24-bit cannot hold a sample above 1.0; it must clamp, not wrap."""
    loud = stems["mix"] * 1.5
    clamped, count = censor_render.clamp_to_full_scale(loud)
    assert count > 0
    assert float(np.abs(clamped).max()) <= 1.0
    # Clamping, not wrap-around: the loud samples keep their sign.
    assert np.array_equal(np.sign(clamped), np.sign(loud))


def test_export_of_an_over_full_scale_mix_stays_close_to_the_mix(tmp_path, stems):
    """Outside the windows the exported file differs only by the clamp, never by more."""
    mix_path = tmp_path / "mix.wav"
    vocals_path = tmp_path / "vocals.wav"
    out_path = tmp_path / "clean.flac"
    # Peaks above full scale, as a decoded AAC mix really has. Scale by the peak *outside*
    # the windows, otherwise the loudest sample is the one the subtraction removes.
    outside = np.ones(len(stems["mix"]), dtype=bool)
    # The mute starts CENSOR_LEAD_MS before each detected span. That region is
    # inside the window, so it cannot be part of the "outside" comparison.
    lead = int(config.CENSOR_LEAD_MS / 1000 * RATE)
    for start, end in SPANS:
        outside[max(0, int(start * RATE) - lead) : int(end * RATE)] = False
    peak = float(np.abs(stems["mix"][outside]).max())
    loud = (stems["mix"] / peak * 1.2).astype(np.float32)
    assert float(np.abs(loud).max()) > 1.0
    audio_io.write(mix_path, loud, RATE, "FLOAT")
    audio_io.write(vocals_path, stems["vocals"], RATE, "FLOAT")

    stats = censor_render.render_to_file(mix_path, vocals_path, SPANS, out_path)
    assert stats.clipped_samples > 0, "the clamp never ran, so this test proves nothing"

    exported, rate = audio_io.read(out_path)
    assert rate == RATE
    # Outside the windows the export must equal the input, bar the clamp the test itself
    # introduced. Inside them the vocal has been subtracted, so sign there is meaningless.
    assert np.max(np.abs(exported[outside] - np.clip(loud, -1.0, 1.0)[outside])) < 1e-6
    # Clamping, not wrap-around: loud samples keep their sign. Compared only where the
    # value is well clear of the 24-bit step, since quantising a near-zero sample to
    # exactly zero legitimately changes its sign bit.
    check = outside & (np.abs(loud).max(axis=1) > 1e-4)
    assert np.array_equal(
        np.sign(exported[check]), np.sign(loud[check])
    ), "the export wrapped around"
    # Inside the windows the vocal is gone but the music is not.
    for start, end in SPANS:
        assert (
            rms(exported, start + 0.1, end - 0.1)
            > 0.5 * rms(loud, start + 0.1, end - 0.1)
        ), "the export silenced the music too"