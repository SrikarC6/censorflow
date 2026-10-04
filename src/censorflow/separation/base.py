"""Stem separation behind one interface.

`AGENTS.md` requires that swapping Demucs for a Roformer or any other separator be a config
change, so the pipeline only ever sees `StemSeparator` and never imports a model library.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from .. import config
from ..models import ProgressFn

__all__ = ["SeparationError", "StemSeparator", "make_separator"]


class SeparationError(RuntimeError):
    """Raised with a message meant to be shown to the user."""


@runtime_checkable
class StemSeparator(Protocol):
    def separate(
        self,
        audio_path: Path,
        stems: Sequence[str],
        on_progress: ProgressFn | None = None,
    ) -> dict[str, Path]:
        """Return the requested stems, keyed by stem name, written to disk."""
        ...


def make_separator(quality: str, output_dir: Path) -> StemSeparator:
    """Build the configured separator. Apple Silicon only for now."""
    from .demucs import DemucsSeparator

    if quality not in config.SEPARATION_QUALITY:
        raise SeparationError(
            f"Unknown quality {quality!r}. Use one of: "
            f"{', '.join(config.SEPARATION_QUALITY)}."
        )
    return DemucsSeparator(quality=quality, output_dir=output_dir)