"""FastAPI app: a thin HTTP shell over `jobs.py`, plus the static web app.

Routes from `AGENTS.md`:

    GET  /api/health                  is this install ready to work
    GET  /api/models/asr              speech-model download progress
    POST /api/models/asr              start that download
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
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import audio_io, config, jobs, lyrics, preview, review
from .asr.install import SpeechModelInstall
from .metadata import read_metadata
from .review import JobError
from .server_files import (
    _add_stem_routes,
    _clip,
    _event_stream,
    _job,
    _media_type,
    _mount_web,
    _save_upload,
)

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
    app.state.models = SpeechModelInstall()
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
            "asr_model_present": (model_dir / "config.json").is_file()
            and (model_dir / "model.safetensors").is_file(),
            "asr_model_dir": str(model_dir),
            "server": "censorflow",
        }

    @api.get("/api/models/asr")
    def model_status(request: Request) -> dict[str, Any]:
        """How far the speech-model download has got. Safe to poll."""
        return request.app.state.models.status()

    @api.post("/api/models/asr")
    def model_start(request: Request) -> dict[str, Any]:
        """Start the download if the weights are not on disk yet."""
        return request.app.state.models.start()

    @api.post("/api/upload")
    async def upload(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        saved, size = await _save_upload(app, file)
        # Tags first, filename second. This is the same resolution order the lyrics stage
        # uses, so the name on screen is the name we search LRCLIB for. mutagen and ffprobe
        # both block, hence the thread.
        track = await asyncio.to_thread(read_metadata, saved)
        logger.info("uploaded %s (%d bytes)", saved.name, size)
        return {
            "source": str(saved),
            "filename": file.filename or saved.name,
            "bytes": size,
            "duration": track.duration,
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
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



app = create_app()
