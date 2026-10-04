"""One job: its state, its directory, and the events it publishes.

The store that runs jobs lives in `jobs.py`. This is the record that store
hands to the server.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import config, metadata
from .censor import render as render_mod
from .models import Flag, TrackInfo, Word
from .pipeline import PipelineResult
from .review import render_payload

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
        # A finished job has to be able to rebuild the result screen after a reload, or the
        # user loses the download button to a refresh even though the file is sitting there.
        payload["render"] = render_payload(self)
        return payload

    @property
    def output_path(self) -> Path:
        return self.directory / f"output.{self.export_format.lstrip('.').lower()}"

    @property
    def original_path(self) -> Path:
        """The untouched upload, as the pipeline copied it. Never re-encoded."""
        return self.directory / f"original{self.source.suffix.lower() or '.audio'}"

    @property
    def download_name(self) -> str:
        """The name the browser saves the finished file under.

        The file on disk is `output.<ext>` because job directories are disposable and shared
        by every stage. The name the user ends up with is not disposable: two songs must not
        both arrive as `output.flac`. So the served name is `<artist> - <title>_clean.<ext>`,
        falling back through title, then the uploaded filename, then `output`.
        """
        suffix = self.export_format.lstrip(".").lower()
        parts = [self.track.artist, self.track.title]
        label = " - ".join(part for part in parts if part)
        if not label:
            label = metadata.title_from_filename(self.source) or self.source.stem
        return f"{metadata.safe_filename(label)}_clean.{suffix}"

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
