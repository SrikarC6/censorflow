"""FastAPI app: a thin HTTP shell over `jobs.py`, plus the static web app.

Routes from `AGENTS.md`:

    GET  /api/health                  is this install ready to work
    POST /api/upload                  save a song, return a job id
    POST /api/jobs                    start analysing it
    GET  /api/jobs/{id}               poll for state
    GET  /api/jobs/{id}/events        server-sent events
    GET  /api/jobs/{id}/review        transcript and flags
    POST /api/jobs/{id}/review        apply edits, then render
    GET  /api/jobs/{id}/clip          region-only preview, original or censored
    GET  /api/jobs/{id}/output        download the finished file

Stem mode is a skeleton: its routes exist and return 501 so the UI can show the screen
without pretending the feature works.

No ML runs here. `LocalBackend` spawns the heavy stages as subprocesses, so the event loop
only ever waits on pipes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audio_io, config, jobs, lyrics, preview, review
from .metadata import title_from_filename
from .review import JobError

logger = logging.getLogger(__name__)

STORE = jobs.JobStore()


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Only start whatever store the app was built with. Assigning here would silently
    # replace the injected store a test just handed in.
    app.state.store.start()
    logger.info("job store ready at %s", app.state.store.root)
    yield
    lyrics.shutdown()


def create_app(store: jobs.JobStore | None = None) -> FastAPI:
    """Build the app. Tests pass their own store so they never touch the real home."""
    app = FastAPI(title="CensorFlow", lifespan=_lifespan)
    app.state.store = store if store is not None else STORE
    _add_api(app)
    _mount_web(app)
    return app


# --- request bodies ---------------------------------------------------------------


class StartJob(BaseModel):
    source: str = Field(description="path of a previously uploaded song")
    clip_seconds: float | None = Field(default=None, ge=1.0, le=3600.0)
    quality: str = Field(default=config.DEFAULT_QUALITY)
    export_format: str = Field(default=config.DEFAULT_EXPORT_FORMAT)
    mode: str = Field(default="censor")


# --- api ---------------------------------------------------------------------------


def _add_api(app: FastAPI) -> None:
    api = app.router

    @api.get("/api/health")
    async def health() -> dict[str, Any]:
        """What the front end needs to know before it offers to do anything.

        ffmpeg is the one hard requirement, and it is worth checking before a user
        picks a song rather than after. The model check is informational: on a first
        run the models are not there yet, and the UI says so instead of failing
        three stages in.
        """
        try:
            audio_io.check_ffmpeg()
            ffmpeg = True
            reason = ""
        except audio_io.AudioError as error:
            ffmpeg = False
            # Carried, not logged: the welcome screen shows this string as it is,
            # because "it does not work" with no reason is not an answer.
            reason = str(error)
        model_dir = config.MODEL_DIR / config.ASR_MODEL.rsplit("/", 1)[-1]
        return {
            "ffmpeg": ffmpeg,
            "reason": reason,
            "asr_model_present": (model_dir / "config.json").is_file(),
            "asr_model_dir": str(model_dir),
            "server": "censorflow",
        }

    @api.post("/api/upload")
    async def upload(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        saved, size = await _save_upload(app, file)
        duration = _duration_or_none(saved)
        logger.info("uploaded %s (%d bytes)", saved.name, size)
        return {
            "source": str(saved),
            "filename": file.filename or saved.name,
            "bytes": size,
            "duration": duration,
            "title": title_from_filename(saved),
        }

    @api.post("/api/jobs", status_code=202)
    async def start_job(body: Annotated[StartJob, Body()]) -> dict[str, Any]:
        if body.mode != "censor":
            raise HTTPException(status_code=501, detail="not implemented")
        source = Path(body.source).expanduser()
        if not source.is_file():
            raise HTTPException(status_code=404, detail="that song is no longer on disk")
        if body.export_format not in config.SUPPORTED_EXPORT_FORMATS:
            raise HTTPException(status_code=400, detail="unsupported export format")
        if body.quality not in config.SEPARATION_QUALITY:
            raise HTTPException(status_code=400, detail="unsupported quality")
        job = app.state.store.create(
            source,
            clip_seconds=body.clip_seconds,
            quality=body.quality,
            export_format=body.export_format,
        )
        return job.snapshot()

    @api.get("/api/jobs")
    async def list_jobs() -> dict[str, Any]:
        return {"jobs": [job.snapshot() for job in app.state.store.list()]}

    @api.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        return _job(app, job_id).snapshot()

    @api.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request) -> StreamingResponse:
        job = _job(app, job_id)
        return StreamingResponse(
            _event_stream(job, request), media_type="text/event-stream"
        )

    @api.get("/api/jobs/{job_id}/review")
    async def get_review(job_id: str) -> dict[str, Any]:
        return review.payload(_job(app, job_id))

    @api.post("/api/jobs/{job_id}/review")
    async def post_review(job_id: str, payload: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        job = _job(app, job_id)
        if job.state.finished:
            raise HTTPException(status_code=409, detail="this job has already finished")
        try:
            review.apply_review(job, payload)
        except JobError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            await asyncio.to_thread(app.state.store.confirm, job)
        except JobError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        payload_out = review.payload(job)
        payload_out["render"] = review.render_payload(job)
        return payload_out

    @api.get("/api/jobs/{job_id}/clip")
    async def job_clip(
        job_id: str,
        kind: str = "original",
        start: float = 0.0,
        end: float = 0.0,
    ) -> Response:
        job = _job(app, job_id)
        if job.result is None:
            raise HTTPException(status_code=409, detail="this job is not ready yet")
        try:
            lo, hi = preview.resolve_region(job, start, end)
            body, media = await asyncio.to_thread(
                _clip, job, kind, lo, hi
            )
        except JobError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(body, media_type=media, headers={"Cache-Control": "no-store"})

    @api.get("/api/jobs/{job_id}/output")
    async def job_output(job_id: str) -> FileResponse:
        job = _job(app, job_id)
        path = job.output_path
        if not path.is_file():
            raise HTTPException(status_code=404, detail="nothing has been rendered yet")
        return FileResponse(
            path, media_type=_media_type(path.suffix), filename=job.download_name
        )

    @api.get("/api/jobs/{job_id}/original")
    async def job_original(job_id: str) -> FileResponse:
        """The untouched upload, so the A/B comparison survives a page reload.

        While the page is alive it plays the browser's own copy of the file, which costs
        nothing. After a reload that copy is gone, and without this route the ORIGINAL button
        would silently play nothing while looking perfectly healthy.
        """
        job = _job(app, job_id)
        path = job.original_path
        if not path.is_file():
            raise HTTPException(status_code=404, detail="the original file is not available")
        return FileResponse(path, media_type=_media_type(path.suffix), filename=path.name)

    _add_stem_routes(app)


# Stem mode is a skeleton (`docs/STEMS_TODO.md`). The routes exist so the screen loads and
# can say "coming soon" over HTTP, rather than 404ing and looking like a bug.
_STEM_ROUTES: tuple[tuple[str, list[str]], ...] = (
    ("/api/stems/jobs", ["POST"]),
    ("/api/stems/jobs/{job_id}", ["GET"]),
    ("/api/stems/jobs/{job_id}/render", ["POST"]),
    ("/api/stems/jobs/{job_id}/mix.wav", ["GET"]),
    ("/api/stems/jobs/{job_id}/stems/{stem}.wav", ["GET"]),
)


def _add_stem_routes(app: FastAPI) -> None:
    async def not_implemented() -> JSONResponse:
        return JSONResponse(status_code=501, content={"detail": "not implemented"})

    for path, methods in _STEM_ROUTES:
        app.add_api_route(path, not_implemented, methods=methods, include_in_schema=False)


def _job(app: FastAPI, job_id: str) -> jobs.Job:
    try:
        return app.state.store.get(job_id)  # type: ignore[no-any-return]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such job") from exc


# --- upload -----------------------------------------------------------------------


async def _save_upload(app: FastAPI, file: UploadFile) -> tuple[Path, int]:
    """Stream an upload into `uploads/<random>/<original name>`. Never loads the whole file.

    The original filename is kept because it is a real source of the track title for files with
    no tags, and `title` is what gets sent to LRCLIB. Saving everything as `original.m4a` made
    every untagged upload look like a song called "original". Each upload gets its own
    directory so two uploads of `song.mp3` cannot collide.
    """
    name = _safe_name(file.filename)
    scratch = app.state.store.upload_dir / secrets.token_hex(4)
    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / name
    size = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(config.UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="that file is too large")
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="that file is empty")
        try:
            audio_io.check_ffmpeg()
        except audio_io.AudioError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if not audio_io.has_audio_stream(target):
            raise HTTPException(
                status_code=400,
                detail="CensorFlow could not find any audio in that file.",
            )
    except BaseException:
        _discard(scratch)
        raise
    return target, size


def _discard(directory: Path) -> None:
    """Remove a refused upload: the file if it got written, then its directory."""
    for path in directory.glob("*"):
        path.unlink(missing_ok=True)
    directory.rmdir()


def _safe_name(filename: str | None) -> str:
    """A safe file name that keeps the caller's title and a believable audio extension.

    The extension is a convenience, not a decision: the real validation is ffprobe, so a wrong
    name cannot smuggle an unreadable file through.
    """
    original = Path(filename or "").name.strip()
    cleaned = re.sub(r"[^\w.()\[\] ' -]", "_", original).strip(" .") or "upload"
    if Path(cleaned).suffix.lower().lstrip(".") not in config.AUDIO_EXTENSIONS:
        cleaned = f"{cleaned}.audio"
    return cleaned[:120]


def _duration_or_none(path: Path) -> float | None:
    try:
        return audio_io.duration_seconds(path)
    except audio_io.AudioError:
        return None


# --- events -----------------------------------------------------------------------


async def _event_stream(job: jobs.Job, request: Request) -> AsyncIterator[bytes]:
    """Server-sent events for one job, closing when the job does.

    A keepalive comment goes out on an idle timer so an intermediate proxy cannot close a
    quiet connection, and `await request.is_disconnected()` ends the generator the moment
    the browser goes away rather than leaking a subscriber.
    """
    subscriber = job.subscribe()
    try:
        yield _sse({"event": "snapshot", **job.snapshot()})
        if job.state.finished:
            # A client that attaches late still gets the current state, but there is nothing
            # left to wait for, so do not sit here burning keepalives.
            return
        while True:
            try:
                payload = await asyncio.wait_for(
                    subscriber.channel.get(), timeout=config.SSE_KEEPALIVE_S
                )
            except TimeoutError:
                yield b": keepalive\n\n"
                continue
            yield _sse(payload)
            if payload.get("event") in {"done", "error"}:
                break
            if await request.is_disconnected():
                break
    finally:
        job.unsubscribe(subscriber)


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


# --- review -----------------------------------------------------------------------


def _clip(job: jobs.Job, kind: str, start: float, end: float) -> tuple[bytes, str]:
    """Blocking half of the clip route: render the region and encode it as WAV."""
    return preview.wav_response(preview.region_audio(job, kind, start, end), config.SAMPLE_RATE)


# The original upload is served back for the A/B comparison, so the formats a user is likely
# to drop in have to arrive as audio. `application/octet-stream` still downloads, but some
# browsers refuse to play it, which would look like a broken ORIGINAL button.
_MEDIA_TYPES = {
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".wma": "audio/x-ms-wma",
}


def _media_type(suffix: str) -> str:
    return _MEDIA_TYPES.get(suffix.lower(), "application/octet-stream")


# --- static web app ---------------------------------------------------------------


class _WebFiles(StaticFiles):
    """Static files that are always revalidated.

    The web app is served from the source tree and has no hashed asset names, so a
    browser that cached `app.js` yesterday would keep running yesterday's screens
    after a change - which during development looks exactly like a change that did
    not work. `no-cache` still allows a 304, so it costs one conditional request.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _mount_web(app: FastAPI) -> None:
    web_dir = config.WEB_DIR
    if not web_dir.is_dir():
        logger.info("no web directory at %s yet; the UI arrives with the next phase", web_dir)
        return

    # Mounted last, at the root, so `web/index.html` and its ES modules are served from
    # their natural paths. Every /api route is registered before this and therefore wins.
    app.mount("/", _WebFiles(directory=web_dir, html=True), name="web")


app = create_app()