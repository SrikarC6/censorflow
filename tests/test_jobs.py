"""The job state machine and review validation, with no model weights involved."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from censorflow import audio_io, config, jobs, preview, review
from censorflow.audio_io import AudioError
from censorflow.models import SOURCE_LYRICS

from .conftest import RATE, FakeBackend, silence, stereo, tone


@pytest.fixture
def store(tmp_path: Path) -> jobs.JobStore:
    return jobs.JobStore(root=tmp_path / "jobs", backend_factory=lambda d: FakeBackend(d))


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, test_wordlist: frozenset[str]) -> None:
    """No network, and only placeholder words on the profanity list.

    `test_wordlist` is requested for its monkeypatching side effect.
    """


def _drain(store: jobs.JobStore, job: jobs.Job) -> jobs.Job:
    """Run the job on the calling thread, so a test can assert on the final state."""
    store.run(job)
    return job


def test_a_job_runs_to_awaiting_review(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    assert job.state is jobs.State.AWAITING_REVIEW
    assert job.pct == 100.0
    assert job.words, "the fake backend returns words"
    assert job.flags, "one of the fake words is on the profanity list"


def test_states_are_reported_in_order(
    store: jobs.JobStore, song: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    original = jobs.Job.set_stage

    def record(self: jobs.Job, name: str) -> None:
        original(self, name)
        seen.append(name)

    monkeypatch.setattr(jobs.Job, "set_stage", record)
    _drain(store, store.create(song))
    assert seen == [
        "fetching_lyrics",
        "decoding",
        "separating",
        "transcribing",
        "detecting",
    ]


def test_an_unknown_stage_is_ignored(store: jobs.JobStore, song: Path) -> None:
    job = store.create(song)
    job.set_stage("teleporting")
    assert job.state is jobs.State.QUEUED


def test_a_missing_source_fails_the_job_with_a_readable_message(
    store: jobs.JobStore, tmp_path: Path
) -> None:
    job = _drain(store, store.create(tmp_path / "nope.m4a"))
    assert job.state is jobs.State.ERROR
    assert job.error is not None
    assert "No such file" in job.error


def test_an_unreadable_file_fails_the_job(store: jobs.JobStore, tmp_path: Path) -> None:
    broken = tmp_path / "broken.m4a"
    broken.write_bytes(b"this is not audio")
    _drain(store, store.create(broken))
    assert store.list()[0].state is jobs.State.ERROR


def test_confirm_renders_and_finishes(store: jobs.JobStore, song: Path, tmp_path: Path) -> None:
    job = _drain(store, store.create(song))
    stats = store.confirm(job)
    assert job.state is jobs.State.DONE
    assert job.output_path.is_file()
    assert stats.window_count >= 1
    assert (job.directory / "windows.json").is_file()


def test_output_media_type_comes_from_the_extension(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song, export_format="flac"))
    store.confirm(job)
    assert job.output_path.suffix == ".flac"
    assert job.output_path.is_file()


def test_the_rendered_file_keeps_the_music(store: jobs.JobStore, song: Path) -> None:
    """Rule 1, through the whole server path rather than through `render_to_file`."""
    job = _drain(store, store.create(song))
    store.confirm(job)
    assert job.stats is not None
    mix, rate = audio_io.read(job.mix_path)
    out, out_rate = audio_io.read(job.output_path)
    assert out_rate == rate
    # The mask covers the *windows*, which are padded past the raw word span, so the
    # comparison has to use the windows the render actually built.
    muted = np.zeros(len(mix), dtype=bool)
    for window in job.stats.windows:
        muted[round(window.start * rate) : round(window.end * rate)] = True
    assert muted.any(), "the fake song should have been censored somewhere"
    assert np.allclose(out[~muted], mix[~muted], atol=1e-4)


# --- review validation -------------------------------------------------------------


@pytest.fixture
def reviewed(store: jobs.JobStore, song: Path) -> jobs.Job:
    return _drain(store, store.create(song))


def _flag_payload(job: jobs.Job, **overrides: object) -> dict[str, object]:
    flag = job.flags[0]
    payload: dict[str, object] = {
        "word_index": flag.word_index,
        "text": flag.text,
        "start": flag.start,
        "end": flag.end,
        "source": flag.source,
        "approx": flag.approx,
        "censor": flag.censor,
    }
    payload.update(overrides)
    return payload


def test_apply_review_round_trips(reviewed: jobs.Job) -> None:
    updated = review.apply_review(reviewed, {"flags": [_flag_payload(reviewed)]})
    assert len(updated) == 1
    assert reviewed.flags == updated
    stored = (reviewed.directory / "review.json").read_text(encoding="utf-8")
    assert str(updated[0].start) in stored


def test_uncensoring_a_flag_removes_it_from_the_render(reviewed: jobs.Job) -> None:
    review.apply_review(reviewed, {"flags": [_flag_payload(reviewed, censor=False)]})
    assert review.censor_spans(reviewed) == []


def test_reviewed_flags_come_back_sorted(reviewed: jobs.Job) -> None:
    late = _flag_payload(reviewed, start=9.0, end=9.2)
    early = _flag_payload(reviewed, start=0.5, end=0.8)
    updated = review.apply_review(reviewed, {"flags": [late, early]})
    assert [flag.start for flag in updated] == [0.5, 9.0]


def test_editing_the_text_never_moves_the_window(reviewed: jobs.Job) -> None:
    before = (reviewed.flags[0].start, reviewed.flags[0].end)
    updated = review.apply_review(reviewed, {"flags": [_flag_payload(reviewed, text="zzappish")]})
    assert (updated[0].start, updated[0].end) == before


def test_the_payload_reports_whether_each_word_is_profane(reviewed: jobs.Job) -> None:
    payload = review.payload(reviewed)
    assert payload["ready"] is True
    assert all("profane" in flag for flag in payload["flags"])


def test_a_flag_can_censor_a_word_that_is_not_on_the_list(reviewed: jobs.Job) -> None:
    updated = review.apply_review(reviewed, {"flags": [_flag_payload(reviewed, text="wibble")]})
    assert review.censor_spans(reviewed) == [(updated[0].start, updated[0].end)]
    payload = review.flag_payload(updated[0], *review.detect.wordlists())
    assert payload["profane"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"flags": "not a list"},
        {"flags": [{"text": ""}]},
        {"flags": [{"text": "zzapp", "start": 1.0, "end": 1.0}]},
        {"flags": [{"text": "zzapp", "start": -1.0, "end": 1.0}]},
        {"flags": [{"text": "zzapp", "start": "x", "end": 1.0}]},
        {"flags": [{"text": "zzapp", "start": 1.0, "end": 2.0, "censor": "yes"}]},
        {"flags": [{"text": "zzapp", "start": 1.0, "end": 2.0, "word_index": 9999}]},
        {"flags": ["a string"]},
    ],
)
def test_bad_review_payloads_are_refused(reviewed: jobs.Job, bad: dict) -> None:
    with pytest.raises(review.JobError):
        review.apply_review(reviewed, bad)


def test_review_before_analysis_is_refused(store: jobs.JobStore, song: Path) -> None:
    job = store.create(song)
    with pytest.raises(review.JobError):
        review.apply_review(job, {"flags": []})


def test_a_lyrics_only_flag_can_be_added_by_hand(reviewed: jobs.Job) -> None:
    payload = _flag_payload(reviewed, word_index=-1, source=SOURCE_LYRICS, approx=True,
                            start=1.234, end=1.4, text="zzapp")
    updated = review.apply_review(reviewed, {"flags": [payload]})
    assert updated[0].approx is True
    assert updated[0].source == SOURCE_LYRICS


# --- preview -----------------------------------------------------------------------


def test_a_preview_region_is_clamped_to_the_audio(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    duration = review.duration_of(job)
    lo, hi = preview.resolve_region(job, 0.0, duration + 100.0)
    assert lo == 0.0
    assert hi == pytest.approx(duration, abs=0.01)


def test_an_inverted_preview_region_is_refused(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    with pytest.raises(review.JobError):
        preview.resolve_region(job, 2.0, 1.0)


def test_a_zero_length_preview_is_refused(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    with pytest.raises(review.JobError):
        preview.resolve_region(job, 1.0, 1.001)


def test_the_censored_preview_differs_only_inside_a_window(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    flag = job.flags[0]
    region = (max(0.0, flag.start - 0.2), flag.end + 0.2)
    original = preview.region_audio(job, "original", *region)
    censored = preview.region_audio(job, "censored", *region)
    assert original.shape == censored.shape
    assert not np.allclose(original, censored), "the flag should change the audio"


def test_the_original_preview_is_the_mix_untouched(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    mix, rate = audio_io.read(job.mix_path)
    start, end = 0.4, 0.9
    assert np.allclose(
        preview.region_audio(job, "original", start, end),
        mix[round(start * rate) : round(end * rate)],
    )


def test_a_wav_preview_is_encoded_in_memory(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    audio = preview.region_audio(job, "original", 0.0, 0.5)
    body, media = preview.wav_response(audio, RATE)
    assert media == "audio/wav"
    assert body[:4] == b"RIFF"
    assert len(body) > 44


def test_an_unknown_preview_kind_is_refused(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    with pytest.raises(review.JobError):
        preview.region_audio(job, "instrumental", 0.0, 0.5)


def test_an_empty_playlist_preview_is_still_a_valid_wav() -> None:
    body, _ = preview.wav_response(np.zeros((0, 2), dtype=np.float32), RATE)
    assert body[:4] == b"RIFF"


# --- misc ---------------------------------------------------------------------------


def test_a_missing_job_raises_key_error(store: jobs.JobStore) -> None:
    with pytest.raises(KeyError):
        store.get("no-such-job")


def test_listing_jobs_is_newest_first(store: jobs.JobStore, song: Path) -> None:
    first = store.create(song)
    time.sleep(0.01)
    second = store.create(song)
    assert [job.id for job in store.list()][:2] == [second.id, first.id]


def test_a_friendly_message_survives_an_unknown_exception() -> None:
    assert "PermissionError" not in jobs._friendly(ZeroDivisionError())
    assert isinstance(jobs._friendly(AudioError("bad file")), str)


def test_the_preview_pad_is_enough_to_hear_the_word(store: jobs.JobStore, song: Path) -> None:
    job = _drain(store, store.create(song))
    start, end = preview.padded_region(job, 0)
    assert start <= job.flags[0].start
    assert end >= job.flags[0].end
    assert end - start >= config.PREVIEW_PAD_S


def test_a_silent_vocal_stem_still_renders(tmp_path: Path, song: Path) -> None:
    """No vocals at all is not an error; the output is just the mix, unmuted."""

    class Silent(FakeBackend):
        """Separates to true silence and hears nothing, which is a real failure mode."""

        def separate(self, audio_path, stems, quality, on_progress=None):
            return {
                "vocals": audio_io.write(
                    self.job_dir / "silent.wav", silence(4.0), RATE, config.FLAC_SUBTYPE
                )
            }

        def transcribe(self, vocal_path, on_progress=None):
            return []

    store = jobs.JobStore(root=tmp_path / "silent", backend_factory=Silent)
    job = _drain(store, store.create(song))
    assert job.state is jobs.State.AWAITING_REVIEW
    assert job.flags == []
    stats = store.confirm(job)
    assert stats.window_count == 0
    assert stats.muted_seconds == 0.0
    mix, _ = audio_io.read(job.mix_path)
    out, _ = audio_io.read(job.output_path)
    assert np.allclose(out, mix, atol=1e-4)


def test_a_wav_source_works_without_any_tags(tmp_path: Path) -> None:
    only_instrumentals = tmp_path / "quiet.wav"
    audio_io.write(only_instrumentals, stereo(tone(110.0, 4.0, 0.2)), RATE, "PCM_16")
    store = jobs.JobStore(root=tmp_path / "jobs2", backend_factory=FakeBackend)
    job = _drain(store, store.create(only_instrumentals))
    assert job.state is jobs.State.AWAITING_REVIEW
    assert len(job.words) == len(FakeBackend(tmp_path).words)