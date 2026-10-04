"""Speech recognition: the configured transcriber plus the platform rule."""

from .base import Transcriber, TranscriptionError, make_transcriber

__all__ = ["Transcriber", "TranscriptionError", "make_transcriber"]