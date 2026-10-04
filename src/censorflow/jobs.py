"""Job state machine and the on-disk layout the server hands out.

One job is one directory under `config.JOBS_DIR`, holding everything the pipeline
produced, in the layout `AGENTS.md` specifies:

    <job>/original.<ext>   mix.wav   vocals.wav   instrumental.wav
            words.json     lyrics.json   lyrics_flags.json
            review.json    windows.json   output.<ext>

The states are the ones named in `AGENTS.md`. They are set by `pipeline.run_censor` through
its `on_stage` callback rather than guessed from progress percentages.

Nothing here imports FastAPI: the server is a thin HTTP shell over this module, so the
state machine can be tested without a client.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import audio_io, config, pipeline
from .censor import render as render_mod
from .compute.base import ComputeBackend, ComputeError
from .compute.local import LocalBackend
from .models import Flag, TrackInfo, Word
from .pipeline import PipelineResult
from .profanity import detect
from .review import JobError

logger = logging.getLogger(__name__)


class State(StrEnum):
    """The job states from `AGENTS.md`, in the order a healthy job passes through them."""

    QUEUED = "queued"
    DECODING = "decoding"
    SEPARATING = "separating"
    TRANSCRIBING = "transcribing"
    FETCHING_LYRICS = "fetching_lyrics"
    DETECTING = "detecting"
    AWAITING_REVIEW = "awaiting_review"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"

    @property
    def finished(self) -> bool:
        return self in {State.DONE, State.ERROR}


@dataclass(slots=True)
class Subscriber:
    """One connected event stream."""

    loop: asyncio.AbstractEventLoop
    channel: asyncio.Queue[dict[str, Any]]


@dataclass(slots=True)
class Job:
    """Everything known about one job. Mutated from the worker thread, read from handlers."""

    id: str
    source: Path
    directory: Path
    clip_seconds: float | None = None
    quality: str = config.DEFAULT_QUALITY
    export_format: str = config.DEFAULT_EXPORT_FORMAT
    created_at: float = field(default_factory=time.time)
    state: State = State.QUEUED
    pct: float = 0.0
    message: str = "waiting to start"
    error: str | None = None
    track: TrackInfo = field(default_factory=TrackInfo)
    words: list[Word] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    stats: render_mod.RenderStats | None = None
    result: PipelineResult | None = None
    review: dict[str, Any] = field(default_factory=dict)
    _subscribers: list[Subscriber] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # --- state -------------------------------------------------------------------

    def set_progress(self, pct: float, message: str) -> None:
        self.pct = max(0.0, min(100.0, pct))
        self.message = message
        self._publish("progress", pct=round(self.pct, 1), message=message)

    def set_stage(self, name: str) -> None:
        try:
            self.state = State(name)
        except ValueError:
            logger.warning("job %s: unknown stage %r, ignoring", self.id, name)
            return
        self._publish("stage", state=str(self.state))

    def fail(self, message: str) -> None:
        self.state = State.ERROR
        self.error = message
        self._publish("error", message=message)

    # --- events ------------------------------------------------------------------

    def subscribe(self) -> Subscriber:
        """Register an event stream. Safe to call from the event loop only."""
        subscriber = Subscriber(loop=asyncio.get_running_loop(), channel=asyncio.Queue())
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def _publish(self, event: str, **fields: Any) -> None:
        """Fan an event out to every stream. Called from the worker thread."""
        payload: dict[str, Any] = {"event": event, "job": self.id, **self.snapshot_fields(),
                                   **fields}
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(
                _offer, subscriber.channel, payload
            )

    # --- serialisation -----------------------------------------------------------

    def snapshot_fields(self) -> dict[str, Any]:
        return {
            "state": str(self.state),
            "pct": round(self.pct, 1),
            "message": self.message,
            "error": self.error,
            "track": self.track.to_dict(),
        }

    def snapshot(self) -> dict[str, Any]:
        payload = self.snapshot_fields()
        # The listing is only useful if a client can tell the jobs apart and pick one.
        payload["id"] = self.id
        payload["created_at"] = self.created_at
        payload["filename"] = self.source.name
        payload["flags"] = len(self.flags)
        payload["words"] = len(self.words)
        return payload

    @property
    def output_path(self) -> Path:
        return self.directory / f"output.{self.export_format.lstrip('.').lower()}"

    @property
    def mix_path(self) -> Path:
        return self.directory / "mix.wav"

    @property
    def vocals_path(self) -> Path:
        return self.directory / "vocals.wav"


def _offer(channel: asyncio.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
    """Non-blocking put: a slow reader drops events rather than stalling the job."""
    try:
        channel.put_nowait(payload)
    except asyncio.QueueFull:
        logger.debug("dropping event for a slow subscriber: %s", payload.get("event"))


class JobStore:
    """Owns the job registry and runs one job at a time.

    One at a time is not a simplification, it is the hardware: `AGENTS.md` says the machine
    is a fanless laptop and forbids loading two models at once. Separation alone takes about
    a gigabyte of resident memory per running stage.
    """

    def __init__(
        self,
        root: Path | None = None,
        backend_factory: Callable[[Path], ComputeBackend] | None = None,
    ) -> None:
        self._root = Path(root) if root is not None else config.JOBS_DIR
        # Injectable so tests can drive the whole state machine with a synthetic backend
        # instead of loading two gigabytes of model weights.
        self._backend_factory = backend_factory or LocalBackend
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pending: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

    @property
    def root(self) -> Path:
        """Where job directories live."""
        return self._root

    @property
    def upload_dir(self) -> Path:
        """Where `POST /api/upload` puts files before a job is created for them.

        Under the store rather than a global, so a test's store never writes into the real
        CensorFlow home.
        """
        return self._root / "uploads"

    # --- registry ----------------------------------------------------------------

    def create(self, source: Path, **options: Any) -> Job:
        job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        directory = self._root / job_id
        directory.mkdir(parents=True, exist_ok=True)
        job = Job(
            id=job_id,
            source=Path(source).resolve(),
            directory=directory,
            **options,
        )
        with self._lock:
            self._jobs[job_id] = job
        self._pending.put(job_id)
        logger.info("queued job %s for %s", job_id, job.source.name)
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    # --- execution ---------------------------------------------------------------

    def start(self) -> None:
        """Begin draining the queue on a daemon thread. Idempotent."""
        if self._worker is not None:
            return
        self._root.mkdir(parents=True, exist_ok=True)
        self._worker = threading.Thread(target=self._drain, name="censorflow-jobs", daemon=True)
        self._worker.start()

    def run(self, job: Job) -> None:
        """Run one job to completion, inline. This is what the worker thread calls."""
        try:
            self._execute(job)
        except Exception as exc:  # the job must always reach a terminal state
            logger.exception("job %s crashed", job.id)
            job.fail(_friendly(exc))

    def _drain(self) -> None:
        while True:
            job_id = self._pending.get()
            try:
                self.run(self.get(job_id))
            except KeyError:  # pragma: no cover - a job deleted while queued
                continue

    def _execute(self, job: Job) -> None:
        started = time.perf_counter()
        backend = self._backend_factory(job.directory)
        try:
            result = pipeline.run_censor(
                job.source,
                job.directory,
                backend=backend,
                clip_seconds=job.clip_seconds,
                export_format=job.export_format,
                quality=job.quality,
                auto=False,
                on_progress=job.set_progress,
                on_stage=job.set_stage,
            )
        except (audio_io.AudioError, ComputeError, JobError) as exc:
            job.fail(_friendly(exc))
            return

        job.result = result
        job.track = result.track
        job.words = result.words
        job.flags = result.flags
        job.set_progress(100.0, "ready for review")
        job.state = State.AWAITING_REVIEW
        job._publish("stage", state=str(State.AWAITING_REVIEW))
        logger.info(
            "job %s analysed in %.1fs: %d words, %d flagged (%s)",
            job.id,
            time.perf_counter() - started,
            len(job.words),
            len(job.flags),
            ", ".join(detect.mask_flags(job.flags)) or "none",
        )

    def confirm(self, job: Job) -> render_mod.RenderStats:
        """Apply the reviewed flags and render. The only way out of `awaiting_review`."""
        if job.result is None:
            raise JobError("this job has nothing to render yet")
        job.state = State.RENDERING
        job.set_progress(0.0, "rendering the censored file")
        job._publish("stage", state=str(State.RENDERING))
        try:
            stats = pipeline.render_reviewed(job.result, job.output_path, job.export_format)
        except (audio_io.AudioError, ComputeError) as exc:
            job.fail(_friendly(exc))
            raise
        job.stats = stats
        job.state = State.DONE
        job.set_progress(100.0, "done")
        job._publish("stage", state=str(State.DONE))
        return stats


def _friendly(exc: BaseException) -> str:
    """One sentence for the user. The traceback is already in `logs/`."""
    if isinstance(exc, audio_io.AudioError):
        return str(exc)
    if isinstance(exc, ComputeError):
        return f"A compute stage failed: {exc}"
    if isinstance(exc, JobError):
        return str(exc)
    if isinstance(exc, FileNotFoundError):
        return "That file could not be found."
    if isinstance(exc, PermissionError):
        return "CensorFlow does not have permission to write that file."
    return f"Something went wrong: {type(exc).__name__}."