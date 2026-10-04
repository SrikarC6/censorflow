"""What the pipeline needs from a compute provider, and nothing more.

Two stages, both of which take minutes on a song and both of which must stay out of the
server process (see `AGENTS.md`): split the mix into stems, then read the vocal stem into
timed words. A later AWS GPU worker implements the same two methods, so the pipeline must
never grow a third one.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import ProgressFn, Word

__all__ = ["ComputeBackend", "ComputeError", "ProgressFn"]


class ComputeError(RuntimeError):
    """Raised with a message meant to be shown to the user."""


@runtime_checkable
class ComputeBackend(Protocol):
    """Separation and transcription, and the stages between them."""

    def separate(
        self,
        audio_path: Path,
        stems: Sequence[str],
        quality: str,
        on_progress: ProgressFn | None = None,
    ) -> dict[str, Path]:
        """Split `audio_path`, returning the requested stems keyed by stem name."""
        ...

    def transcribe(
        self, vocal_path: Path, on_progress: ProgressFn | None = None
    ) -> list[Word]:
        """Return every recognised word with its timing. Timing is authoritative."""
        ...