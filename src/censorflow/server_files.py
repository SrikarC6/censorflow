"""Upload, events, clips, and the static pages.

The route table lives in `server.py`. These are the helpers it calls: saving a
file, streaming events, cutting a preview, and serving the web app.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import re
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import audio_io, config, jobs, preview

logger = logging.getLogger(__name__)

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
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise HTTPException(
                status_code=507,
                detail="The disk is full, so the song could not be saved.",
            ) from exc
        raise
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
