"""parakeet-tdt-0.6b-v3 on Apple Silicon, via parakeet-mlx.

The weights live in `config.MODEL_DIR` (~2.3 GB) rather than a Hugging Face cache, so the
whole application is one directory that can be copied or packaged. They are fetched on
first run; `hf download` stalls over the Xet transport, so the downloader issues parallel
resumable range requests instead (see the download stage).

Measured on an M2 with a 45 s vocal stem: 36 s to load, 3.8 s to transcribe, i.e. about
12x realtime, with word confidences between 0.7 and 1.0. That load cost is why this runs
in a subprocess (`AGENTS.md`): it must not be paid inside the server process.
"""

from __future__ import annotations

import logging
import platform
import sys
import tempfile
import time
from pathlib import Path

from .. import audio_io, config
from ..models import SOURCE_ASR, ProgressFn, Word
from .base import TranscriptionError

logger = logging.getLogger(__name__)


def require_apple_silicon() -> None:
    """Fail with an actionable message when the mlx backend cannot run here."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise TranscriptionError(
            "Speech recognition currently needs an Apple Silicon Mac, because the model "
            "runs through MLX. On other machines use the remote GPU worker (planned)."
        )


def model_dir(model_id: str) -> Path:
    """Where the weights for `model_id` should be on disk."""
    return config.MODEL_DIR / model_id.rsplit("/", 1)[-1]


class ParakeetTranscriber:
    """Transcribe a vocal stem into timed words."""

    name = "parakeet"

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or config.ASR_MODEL
        self.dir = model_dir(self.model_id)

    def transcribe(
        self, vocal_path: Path, on_progress: ProgressFn | None = None
    ) -> list[Word]:
        require_apple_silicon()
        import mlx.core as mx
        from parakeet_mlx import from_pretrained

        if not (self.dir / "config.json").is_file():
            # The welcome screen downloads this with a progress bar. The headless
            # path has no screen, so the same fetch runs here and reports through
            # the transcribe progress line.
            from .fetch import DownloadError, fetch_asr_model

            _report(on_progress, 2.0, "downloading the speech model")
            try:
                fetch_asr_model(on_progress, dest=self.dir, model_id=self.model_id)
            except DownloadError as exc:
                raise TranscriptionError(str(exc)) from exc

        with tempfile.TemporaryDirectory(prefix="censorflow-asr-") as scratch:
            speech = audio_io.to_mono16k(Path(vocal_path), Path(scratch) / "speech.wav")
            _report(on_progress, 20.0, "loading the model")
            started = time.perf_counter()
            model = from_pretrained(str(self.dir), dtype=mx.bfloat16)
            logger.info("loaded %s in %.1fs", self.model_id, time.perf_counter() - started)

            _report(on_progress, 40.0, "reading the vocal stem")
            result = model.transcribe(str(speech))

        words = _to_words(result)
        logger.info(
            "transcribed %d words in %.1fs", len(words), time.perf_counter() - started
        )
        _report(on_progress, 100.0, f"read {len(words)} words")
        return words


def _to_words(result: object) -> list[Word]:
    """Flatten the alignment into clean word records.

    The token stream also carries spaces, punctuation and sentence markers, and every token
    text carries a leading space, so those are dropped here. Zero-length tokens are dropped
    too: a censor window built on them would be a window at a point rather than over a word.
    """
    words: list[Word] = []
    for token in getattr(result, "tokens", []):
        text = token.text.strip()
        if not text or not any(character.isalnum() for character in text):
            continue
        start = float(token.start)
        end = float(token.end)
        if end <= start:
            continue
        words.append(
            Word(
                text=text,
                start=start,
                end=end,
                confidence=float(getattr(token, "confidence", 1.0) or 0.0),
                source=SOURCE_ASR,
            )
        )
    words.sort(key=lambda word: word.start)
    return words


def _report(on_progress: ProgressFn | None, pct: float, msg: str) -> None:
    if on_progress is not None:
        on_progress(pct, msg)