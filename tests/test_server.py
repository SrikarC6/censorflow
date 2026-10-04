"""The HTTP surface, driven end to end with a scripted client.

Uses `fastapi.testclient.TestClient` (httpx under the hood) against a real `JobStore` with a
synthetic backend, so the routes, the SSE stream and the review round trip are all exercised
without model weights.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from censorflow import config, jobs, server
from censorflow.models import SOURCE_LYRICS, TrackInfo
from censorflow.server import _media_type

from .conftest import RATE, FakeBackend

EXPECTED_DETAIL = {"detail": "not implemented"}


@pytest.fixture
def store(tmp_path: Path) -> jobs.JobStore:
    return jobs.JobStore(root=tmp_path / "jobs", backend_factory=FakeBackend)


@pytest.fixture
def client(store: jobs.JobStore) -> Iterator[TestClient]:
    app = server.create_app(store=store)
    with TestClient(app) as test_client:
        # The lifespan starts the worker thread, but these tests run each job inline so
        # there is no polling and no sleeping.
        yield test_client


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, test_wordlist: frozenset[str]) -> None:
    """No network, and only placeholder words on the profanity list."""
    monkeypatch.setattr("censorflow.profanity.detect._cached_wordlist", _stub_wordlist)
    monkeypatch.setattr("censorflow.lyrics.fetch", lambda track, artists=None: None)


def _stub_wordlist(extra: str | None = None, allow: str | None = None):
    from .conftest import TEST_ALLOWED, TEST_PROFANE

    return TEST_PROFANE, TEST_ALLOWED


def _upload(client: TestClient, song: Path) -> dict:
    with song.open("rb") as handle:
        response = client.post("/api/upload", files={"file": (song.name, handle)})
    assert response.status_code == 200, response.text
    return response.json()


def _run(store: jobs.JobStore, job_id: str) -> jobs.Job:
    job = store.get(job_id)
    store.run(job)
    return job


# --- upload -------------------------------------------------------------------------


def test_upload_returns_a_usable_source(client: TestClient, song: Path) -> None:
    payload = _upload(client, song)
    assert Path(payload["source"]).is_file()
    assert payload["bytes"] > 0
    assert payload["duration"] == pytest.approx(4.0, abs=0.2)


def test_an_upload_keeps_its_name_so_untagged_files_still_have_a_title(
    client: TestClient, tmp_path: Path, song: Path
) -> None:
    """Regression: saving every upload as `original.m4a` reported the title "original"."""
    named = tmp_path / "1-03 BROTHER STONE.m4a"
    named.write_bytes(song.read_bytes())
    with named.open("rb") as handle:
        payload = client.post("/api/upload", files={"file": (named.name, handle)}).json()
    assert Path(payload["source"]).name == "1-03 BROTHER STONE.m4a"
    assert payload["title"] == "BROTHER STONE"


def test_two_uploads_of_the_same_name_do_not_collide(client: TestClient, song: Path) -> None:
    first = _upload(client, song)
    second = _upload(client, song)
    assert first["source"] != second["source"]


def test_uploading_a_file_with_no_audio_is_refused(client: TestClient, tmp_path: Path) -> None:
    not_audio = tmp_path / "notes.txt"
    not_audio.write_text("just some text")
    with not_audio.open("rb") as handle:
        response = client.post("/api/upload", files={"file": (not_audio.name, handle)})
    assert response.status_code == 400
    assert "audio" in response.json()["detail"]


def test_uploading_an_empty_file_is_refused(client: TestClient, tmp_path: Path) -> None:
    empty = tmp_path / "empty.m4a"
    empty.touch()
    with empty.open("rb") as handle:
        response = client.post("/api/upload", files={"file": (empty.name, handle)})
    assert response.status_code == 400


def test_a_refused_upload_leaves_nothing_behind(
    client: TestClient, store: jobs.JobStore, tmp_path: Path
) -> None:
    not_audio = tmp_path / "notes.mp3"
    not_audio.write_text("still not audio")
    before = set(store.upload_dir.glob("*"))
    with not_audio.open("rb") as handle:
        client.post("/api/upload", files={"file": (not_audio.name, handle)})
    assert set(store.upload_dir.glob("*")) == before


# --- starting a job ------------------------------------------------------------------


def test_starting_a_job_returns_a_snapshot(client: TestClient, song: Path) -> None:
    uploaded = _upload(client, song)
    response = client.post("/api/jobs", json={"source": uploaded["source"]})
    assert response.status_code == 202
    assert response.json()["state"] in {"queued", "decoding"}


def test_starting_a_job_for_a_missing_file_is_a_404(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/jobs", json={"source": str(tmp_path / "ghost.m4a")})
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"export_format": "aiff-ish"}, "format"),
        ({"quality": "ultra"}, "quality"),
        ({"clip_seconds": 0.1}, None),
    ],
)
def test_bad_job_options_are_refused(client: TestClient, song: Path, body: dict, message: str | None) -> None:
    uploaded = _upload(client, song)
    response = client.post("/api/jobs", json={"source": uploaded["source"], **body})
    assert response.status_code in {400, 422}
    if message:
        assert message in response.json()["detail"]


def test_stem_mode_is_not_implemented(client: TestClient, song: Path) -> None:
    uploaded = _upload(client, song)
    response = client.post("/api/jobs", json={"source": uploaded["source"], "mode": "stems"})
    assert response.status_code == 501
    assert response.json() == EXPECTED_DETAIL


def test_listing_jobs(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    uploaded = _upload(client, song)
    first = client.post("/api/jobs", json={"source": uploaded["source"]}).json()
    second = client.post("/api/jobs", json={"source": uploaded["source"]}).json()
    listed = client.get("/api/jobs").json()["jobs"]
    assert len(listed) == 2
    listed_by_id = {job["id"]: job for job in listed}
    assert listed_by_id[first["id"]]["state"] == first["state"]
    assert listed_by_id[second["id"]]["state"] == second["state"]
    # newest first
    assert listed[0]["created_at"] >= listed[1]["created_at"]


def test_an_unknown_job_is_a_404(client: TestClient) -> None:
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/review").status_code == 404
    assert client.get("/api/jobs/nope/output").status_code == 404
    assert client.get("/api/jobs/nope/original").status_code == 404


# --- events ---------------------------------------------------------------------------


def test_the_event_stream_opens_with_a_snapshot_and_closes_when_the_job_is_done(
    client: TestClient, store: jobs.JobStore, song: Path
) -> None:
    """The job is finished first on purpose.

    Streaming while a job is still running would mean racing a background thread against the
    ASGI test portal; reading a finished job is deterministic and still proves the snapshot
    contract and that the generator terminates instead of leaking a subscriber.
    """
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = _run(store, store.list()[0].id)
    _confirm(client, job)
    assert job.state is jobs.State.DONE

    with client.stream("GET", f"/api/jobs/{job.id}/events") as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        body = b"".join(stream.iter_bytes())

    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith(b"data: ")]
    assert len(events) == 1
    assert events[0]["event"] == "snapshot"
    assert events[0]["state"] == "done"
    assert not job._subscribers


def test_the_snapshot_poll_agrees_with_the_stream(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    uploaded = _upload(client, song)
    client.post("/api/jobs", json={"source": uploaded["source"]})
    job = store.list()[0]
    store.run(job)
    payload = client.get(f"/api/jobs/{job.id}").json()
    assert payload["state"] == "awaiting_review"
    assert payload["words"] == len(job.words)
    assert payload["flags"] == len(job.flags)


# --- review ----------------------------------------------------------------------------


def test_the_review_payload_carries_the_transcript(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = _run(store, store.list()[0].id)
    payload = client.get(f"/api/jobs/{job.id}/review").json()
    assert payload["ready"] is True
    assert payload["words"] and payload["flags"]
    assert all("profane" in flag for flag in payload["flags"])
    assert payload["duration"] == pytest.approx(4.0, abs=0.2)


def test_review_before_analysis_says_so(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = store.list()[0]
    payload = client.get(f"/api/jobs/{job.id}/review").json()
    assert payload["ready"] is False


def _confirm(client: TestClient, job: jobs.Job, **overrides: object) -> dict:
    flags = [dataclasses.asdict(flag) for flag in job.flags]
    for flag in flags:
        flag.update(overrides)
    return client.post(f"/api/jobs/{job.id}/review", json={"flags": flags})


def test_confirming_renders_and_reports(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = _run(store, store.list()[0].id)
    payload = _confirm(client, job).json()
    assert payload["render"]["windows"] >= 1
    assert payload["render"]["muted_seconds"] > 0
    assert job.state is jobs.State.DONE


def test_confirming_with_everything_off_still_renders(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = _run(store, store.list()[0].id)
    payload = _confirm(client, job, censor=False).json()
    assert payload["render"]["muted_seconds"] == 0.0


def test_confirming_twice_is_refused(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = _run(store, store.list()[0].id)
    _confirm(client, job)
    assert _confirm(client, job).status_code == 409


def test_a_bad_review_payload_is_a_400(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = _run(store, store.list()[0].id)
    response = client.post(f"/api/jobs/{job.id}/review", json={"flags": [{"text": ""}]})
    assert response.status_code == 400
    assert "word" in response.json()["detail"]


def test_review_survives_a_round_trip(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = _run(store, store.list()[0].id)
    _confirm(client, job)
    stored = json.loads((job.directory / "review.json").read_text(encoding="utf-8"))
    assert len(stored["flags"]) == len(job.flags)


def test_a_lyrics_only_flag_can_be_added_over_http(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    job = _run(store, store.list()[0].id)
    flags = [dataclasses.asdict(flag) for flag in job.flags]
    flags.append(
        {
            "word_index": -1,
            "text": "snork",
            "start": 1.0,
            "end": 1.4,
            "source": SOURCE_LYRICS,
            "approx": True,
            "censor": True,
        }
    )
    payload = client.post(f"/api/jobs/{job.id}/review", json={"flags": flags}).json()
    assert payload["render"]["words_censored"] == len(flags)


# --- clips ------------------------------------------------------------------------------


def _ready_job(client: TestClient, store: jobs.JobStore, song: Path) -> jobs.Job:
    client.post("/api/jobs", json={"source": _upload(client, song)["source"]})
    return _run(store, store.list()[0].id)


def test_a_clip_comes_back_as_wav(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    job = _ready_job(client, store, song)
    response = client.get(f"/api/jobs/{job.id}/clip", params={"kind": "original", "start": 0.5, "end": 1.5})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert len(response.content) > 44


def test_a_clip_has_the_requested_length(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    job = _ready_job(client, store, song)
    response = client.get(f"/api/jobs/{job.id}/clip", params={"kind": "original", "start": 1.0, "end": 2.0})
    body = response.content
    frames = (len(body) - 44) // 4
    assert frames == pytest.approx(RATE, abs=2)


def test_the_censored_clip_differs_from_the_original(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    job = _ready_job(client, store, song)
    flag = job.flags[0]
    params = {"start": flag.start, "end": flag.end}
    original = client.get(f"/api/jobs/{job.id}/clip", params={"kind": "original", **params}).content
    censored = client.get(f"/api/jobs/{job.id}/clip", params={"kind": "censored", **params}).content
    assert original != censored


@pytest.mark.parametrize(
    "params",
    [
        {"kind": "instrumental", "start": 0.5, "end": 1.0},
        {"kind": "original", "start": 2.0, "end": 1.0},
        {"kind": "original", "start": 1.0, "end": 1.001},
    ],
)
def test_bad_clip_requests_are_400(client: TestClient, store: jobs.JobStore, song: Path, params: dict) -> None:
    job = _ready_job(client, store, song)
    assert client.get(f"/api/jobs/{job.id}/clip", params=params).status_code == 400


def test_a_clip_is_not_cached(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    job = _ready_job(client, store, song)
    response = client.get(f"/api/jobs/{job.id}/clip", params={"kind": "original", "start": 0, "end": 1})
    assert response.headers["cache-control"] == "no-store"


# --- output -------------------------------------------------------------------------------


def test_downloading_the_output(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    job = _ready_job(client, store, song)
    _confirm(client, job)
    response = client.get(f"/api/jobs/{job.id}/output")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/flac"
    assert len(response.content) > 1000


def test_downloading_before_rendering_is_a_404(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    job = _ready_job(client, store, song)
    assert client.get(f"/api/jobs/{job.id}/output").status_code == 404


def test_the_download_is_named_after_the_song_not_after_the_job(
    client: TestClient, store: jobs.JobStore, song: Path
) -> None:
    """Two songs must not both arrive as `output.flac`."""
    job = _ready_job(client, store, song)
    job.track = TrackInfo(artist="A Singer", title="A Song")
    _confirm(client, job)
    response = client.get(f"/api/jobs/{job.id}/output")
    disposition = response.headers["content-disposition"]
    # Starlette encodes a name with spaces as RFC 5987 `filename*=utf-8''...`, which is what
    # a browser needs; the point is the name itself, not the exact spelling of the header.
    assert disposition.startswith("attachment;")
    assert unquote(disposition.split("utf-8''", 1)[1]) == "A Singer - A Song_clean.flac"


def test_a_download_name_falls_back_to_the_uploaded_filename(
    client: TestClient, store: jobs.JobStore, song: Path
) -> None:
    job = _ready_job(client, store, song)
    job.track = TrackInfo()
    _confirm(client, job)
    disposition = client.get(f"/api/jobs/{job.id}/output").headers["content-disposition"]
    assert disposition.endswith("_clean.flac")
    assert "output_clean" not in disposition


def test_a_finished_job_can_still_be_rejoined(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    """A refresh must not throw away the download the user came back for."""
    job = _ready_job(client, store, song)
    _confirm(client, job)
    snapshot = client.get(f"/api/jobs/{job.id}").json()
    assert snapshot["state"] == "done"
    render = snapshot["render"]
    assert render["words_censored"] == 1
    assert render["windows"] == 1
    assert render["output"].endswith("/output")
    assert render["filename"].endswith("_clean.flac")


def test_a_job_still_being_analysed_carries_no_render_figures(
    client: TestClient, store: jobs.JobStore, song: Path
) -> None:
    job = _ready_job(client, store, song)
    assert client.get(f"/api/jobs/{job.id}").json()["render"] is None


# --- the original, for the A/B after a reload -------------------------------------------------


def test_the_original_upload_is_served_back(client: TestClient, store: jobs.JobStore, song: Path) -> None:
    job = _ready_job(client, store, song)
    response = client.get(f"/api/jobs/{job.id}/original")
    assert response.status_code == 200
    assert response.content == song.read_bytes()


def test_the_original_is_served_as_audio_not_as_an_opaque_blob(
    client: TestClient, store: jobs.JobStore, song: Path
) -> None:
    """`application/octet-stream` downloads but some browsers will not play it."""
    job = _ready_job(client, store, song)
    response = client.get(f"/api/jobs/{job.id}/original")
    assert response.headers["content-type"].startswith("audio/")
    for suffix in (".flac", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".aiff"):
        assert _media_type(suffix).startswith("audio/")


def test_the_original_of_an_unknown_job_is_a_404(client: TestClient) -> None:
    assert client.get("/api/jobs/nope/original").status_code == 404


# --- stem mode -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/stems/jobs"),
        ("get", "/api/stems/jobs/whatever"),
        ("post", "/api/stems/jobs/whatever/render"),
        ("get", "/api/stems/jobs/whatever/mix.wav"),
        ("get", "/api/stems/jobs/whatever/stems/vocals.wav"),
    ],
)
def test_every_stem_route_is_501(client: TestClient, method: str, path: str) -> None:
    response = getattr(client, method)(path)
    assert response.status_code == 501
    assert response.json() == EXPECTED_DETAIL


# --- misc ------------------------------------------------------------------------------------


def test_the_server_never_binds_a_routable_address() -> None:
    assert config.SERVER_HOST == "127.0.0.1"


def test_the_openapi_schema_advertises_the_review_routes(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/jobs/{job_id}/review" in response.json()["paths"]


def test_a_missing_web_directory_does_not_break_the_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "WEB_DIR", tmp_path / "no-such-web")
    store = jobs.JobStore(root=tmp_path / "jobs", backend_factory=FakeBackend)
    with TestClient(server.create_app(store=store)) as test_client:
        assert test_client.get("/openapi.json").status_code == 200


# --- health ------------------------------------------------------------------------------


def test_health_reports_that_this_install_can_work(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ffmpeg"] is True
    assert payload["server"] == "censorflow"
    assert Path(payload["asr_model_dir"]) == config.MODEL_DIR / config.ASR_MODEL.rsplit("/", 1)[-1]


def test_health_says_when_ffmpeg_is_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from censorflow import audio_io

    def no_ffmpeg() -> None:
        raise audio_io.AudioError("ffmpeg is not installed. Install it with: brew install ffmpeg")

    monkeypatch.setattr(server.audio_io, "check_ffmpeg", no_ffmpeg)
    payload = client.get("/api/health").json()
    assert payload["ffmpeg"] is False
    # The reason is carried, because the welcome screen shows it verbatim.
    assert "brew install ffmpeg" in payload["reason"]


def test_health_does_not_fail_when_the_asr_model_is_absent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "MODEL_DIR", config.MODEL_DIR / "no-such-models")
    payload = client.get("/api/health").json()
    assert payload["asr_model_present"] is False
    assert payload["ffmpeg"] is True


# --- the web files ------------------------------------------------------------------------


def test_web_files_are_served_with_no_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Chrome caches ES modules by URL, so an edit to app.js that the browser
    # replays from disk looks exactly like broken code. `no-cache` revalidates.
    monkeypatch.setattr(config, "WEB_DIR", config.WEB_DIR)
    store = jobs.JobStore(root=tmp_path / "jobs", backend_factory=FakeBackend)
    with TestClient(server.create_app(store=store)) as test_client:
        response = test_client.get("/index.html")
    assert response.status_code == 200, config.WEB_DIR
    assert response.headers["cache-control"] == "no-cache"


def test_the_web_app_files_are_all_served(tmp_path: Path) -> None:
    store = jobs.JobStore(root=tmp_path / "jobs", backend_factory=FakeBackend)
    with TestClient(server.create_app(store=store)) as test_client:
        for name in (
            "index.html",
            "app.js",
            "api.js",
            "ui.js",
            "flipdisc.js",
            "font5x7.js",
            "font-glyphs.js",
            "screens.js",
            "session.js",
            "review.js",
            "review-dom.js",
            "stems.js",
            "model.js",
            "board-paint.js",
            "board-controls.js",
            "board-field.js",
            "style.css",
        ):
            response = test_client.get(f"/{name}")
            assert response.status_code == 200, name
            assert response.content, name
        # ES modules have to arrive as JavaScript or the browser refuses them.
        assert "javascript" in test_client.get("/app.js").headers["content-type"]