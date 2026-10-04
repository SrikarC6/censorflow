"""First-run speech-model download, as something the server can poll.

The fetch itself is `asr.fetch`. This only remembers how far it has got, so the
welcome screen can draw a progress bar instead of a static "missing" line.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .fetch import DownloadError, fetch_asr_model, model_is_present

logger = logging.getLogger(__name__)


class SpeechModelInstall:
    """One download at a time. A restart drops it; the next start resumes files."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._pct = 0.0
        self._message = ""
        self._fetch = fetch_asr_model

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._view()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if model_is_present():
                self._state = "done"
                self._pct = 100.0
                self._message = "the speech model is ready"
                return self._view()
            if self._state == "running":
                return self._view()
            self._state = "running"
            self._pct = 0.0
            self._message = "starting the download"
            threading.Thread(target=self._run, name="censorflow-model", daemon=True).start()
            return self._view()

    def _run(self) -> None:
        try:
            self._fetch(self._on_progress)
        except DownloadError as exc:
            self._fail(str(exc))
            return
        except Exception:
            logger.exception("speech model download failed")
            self._fail(
                "CensorFlow could not download the speech model. "
                "Check the internet connection and try again."
            )
            return
        with self._lock:
            self._state = "done"
            self._pct = 100.0
            self._message = "the speech model is ready"

    def _on_progress(self, pct: float, msg: str) -> None:
        with self._lock:
            self._pct = float(pct)
            self._message = msg

    def _fail(self, message: str) -> None:
        with self._lock:
            self._state = "error"
            self._message = message

    def _view(self) -> dict[str, Any]:
        present = model_is_present()
        return {
            "present": present,
            "state": "done" if present and self._state != "running" else self._state,
            "pct": 100.0 if present and self._state != "running" else self._pct,
            "message": self._message,
        }
