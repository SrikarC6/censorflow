"""Speech recognition behind one interface.

Returns `Word` records with measured start and end times. Those times are a first
guess: `lyrics.align_words` warps them onto the lyric-line clock when lyrics exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import ProgressFn, Word

__all__ = ["Transcriber", "TranscriptionError", "make_transcriber"]


class TranscriptionError(RuntimeError):
    """Raised with a message meant to be shown to the user."""


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(
        self, vocal_path: Path, on_progress: ProgressFn | None = None
    ) -> list[Word]:
        """Return every recognised word, in ascending time order."""
        ...


def make_transcriber(model_id: str | None = None) -> Transcriber:
    """Build the configured transcriber. Apple Silicon only for now."""
    from .parakeet import ParakeetTranscriber

    return ParakeetTranscriber(model_id=model_id)