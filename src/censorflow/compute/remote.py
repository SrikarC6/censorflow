"""Planned: offloading the two ML stages to a GPU worker in the cloud.

Not implemented, and not to be implemented in this phase (`AGENTS.md`). This file exists so
the contract for that worker is written down before it is needed, and so nothing in the
pipeline can quietly grow a provider-specific shortcut.

The contract, for whoever builds it:

* Input. `separate(audio_path, stems, quality, on_progress)` uploads the decoded mix
  (44.1 kHz stereo FLAC) to S3 under a per-job prefix and enqueues a GPU job that runs the
  same Demucs model as `separation/demucs.py`. `transcribe(vocal_path, on_progress)` enqueues
  parakeet-tdt on the uploaded vocal stem.
* Output. Both calls return local `Path`s: the worker downloads the stems (FLAC, 44.1 kHz
  stereo) and a `words.json` holding the same `Word(text, start, end, confidence, source)`
  records `asr/parakeet.py` produces locally. Key layout and bucket names are its own
  business, but stems must match the mix length within
  `config.STEM_LENGTH_TOLERANCE_SAMPLES`, exactly as the local separator does.
* Progress. `on_progress(percent, message)` is driven by a queue or SNS notification rather
  than by reading a child's stdout.
* Everything else stays local: decoding, window building, rendering, export and the
  review screen never leave the machine, so only audio in and stems out cross the wire.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..models import ProgressFn, Word

_MESSAGE = (
    "Cloud compute is not implemented. CensorFlow runs the separation and transcription "
    "stages on this Mac; a remote GPU worker is a later project."
)


class RemoteBackend:
    """Raises NotImplementedError; see the module docstring for the intended contract."""

    def separate(
        self,
        audio_path: Path,
        stems: Sequence[str],
        quality: str,
        on_progress: ProgressFn | None = None,
    ) -> dict[str, Path]:
        raise NotImplementedError(_MESSAGE)

    def transcribe(
        self, vocal_path: Path, on_progress: ProgressFn | None = None
    ) -> list[Word]:
        raise NotImplementedError(_MESSAGE)