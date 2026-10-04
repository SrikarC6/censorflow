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

import errno
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import audio_io, config, pipeline
from .censor import render as render_mod
from .compute.base import ComputeBackend, ComputeError
from .compute.local import LocalBackend
from .job import Job, State
from .profanity import detect
from .review import JobError

logger = logging.getLogger(__name__)


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
        # One job at a time, and only ever once. See `run`.
        self._run_lock = threading.Lock()
        self._ran: set[str] = set()
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
        """Run one job to completion, inline. This is what the worker thread calls.

        A job runs exactly once. `create` enqueues it, so the worker thread will pick
        it up; if anything else calls this first - a test driving a job by hand, an
        operator retrying one - it takes the lock and does the work, and the worker's
        later attempt finds the job already run and returns. Without the claim the two
        would run two pipelines over one directory at the same time, which is how a
        test ends up asserting on a half-written `words.json`.

        The claim is recorded before the work, so a job that crashes is not retried:
        the job has failed, and failing it again would hide the first error. It is
        keyed on "has run" rather than `State.finished`, because the pipeline stops at
        `awaiting_review` - not finished, but emphatically not to be analysed again.

        The lock is store-wide rather than per job because this is a fanless laptop:
        one job at a time is the point. It is held for the whole run, so a second
        caller waits for the first to finish rather than being told to go away, and it
        is not reentrant - nothing under it calls `run`.
        """
        with self._run_lock:
            with self._lock:
                if job.id in self._ran:
                    return
                self._ran.add(job.id)
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
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "The disk is full, so CensorFlow could not write the song."
    return f"Something went wrong: {type(exc).__name__}."