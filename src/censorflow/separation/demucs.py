"""Vocal isolation on Apple Silicon, via mlx-audio-separator.

Two things here are not obvious and both are measured, not assumed:

* `instrumental` is derived as `mix - vocals`, never summed from other stems. On a real
  track Demucs's four stems do not add back up to the mix (RMS error 0.03 against a mix
  RMS of 0.29), so summing them would leave a hole exactly where the instrumental should
  be. Subtracting the vocal stem leaves the mix mathematically untouched everywhere else,
  which is also what `AGENTS.md` rule 1 needs.
* Only the vocal stem is requested from the separator. The default model is a vocals-only
  Mel-Band-RoFormer; writing extra stems would cost disk and time for nothing, and the
  instrumental is free.

Apple-only. The mlx imports are guarded, so this module still imports on Linux and raises a
readable error only when separation is actually attempted.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .. import audio_io, config
from ..models import ProgressFn
from .base import SeparationError

logger = logging.getLogger(__name__)

_VOCALS = "vocals"
_INSTRUMENTAL = "instrumental"
# Demucs writes the stem whose name matches this, whatever order it prefers.
_VOCALS_GLOB = "*vocals*.wav"


def require_apple_silicon() -> None:
    """Fail with an actionable message when the mlx backend cannot run here."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SeparationError(
            "Separation currently needs an Apple Silicon Mac, because the model runs "
            "through MLX. On other machines use the remote GPU worker (planned) or wait "
            "for the CPU backend."
        )


class DemucsSeparator:
    """Two-stem separation: the model supplies vocals, we derive the instrumental."""

    name = "separator"

    def __init__(self, *, quality: str, output_dir: Path, model_filename: str | None = None) -> None:
        self.quality = quality
        self.output_dir = Path(output_dir)
        self.model_filename = model_filename or config.SEPARATOR_MODEL

    def separate(
        self,
        audio_path: Path,
        stems: Sequence[str] = config.STEMS_CENSOR,
        on_progress: ProgressFn | None = None,
    ) -> dict[str, Path]:
        """Return the requested stems as files, deriving the instrumental from the mix."""
        require_apple_silicon()
        wanted = list(stems)
        unknown = [s for s in wanted if s not in config.STEMS_CENSOR]
        if unknown:
            raise SeparationError(
                f"This separator cannot produce {', '.join(unknown)}. "
                f"Censor mode needs {', '.join(config.STEMS_CENSOR)}."
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        vocals_path = self._separate_vocals(audio_path, on_progress)
        if _VOCALS not in wanted:
            vocals_path.unlink(missing_ok=True)
            return {}

        written: dict[str, Path] = {_VOCALS: vocals_path}
        if _INSTRUMENTAL in wanted:
            written[_INSTRUMENTAL] = self._derive_instrumental(audio_path, vocals_path)
        return written

    # -- internals ----------------------------------------------------------------

    def _separate_vocals(self, audio_path: Path, on_progress: ProgressFn | None) -> Path:
        from mlx_audio_separator import Separator

        _point_library_caches_at_project_models()
        kwargs: dict[str, object] = {
            "log_formatter": None,
            "model_file_dir": str(config.SEPARATOR_MODEL_DIR),
            "output_dir": str(self.output_dir),
            "output_format": "WAV",
            "output_single_stem": _VOCALS,
            # Persist the one-time ckpt→safetensors conversion so later runs stay MLX-only.
            "save_converted_safetensors": True,
        }
        if _is_demucs_model(self.model_filename):
            params = {"shifts": 0, "overlap": 0.25, **_quality_overrides(self.quality)}
            kwargs["demucs_params"] = {
                # These four are the library's own defaults; only shifts and overlap are
                # ours, and they are passed explicitly because passing any of them means
                # the library stops filling in its defaults.
                "segment_size": "Default",
                "segments_enabled": True,
                "batch_size": "auto",
                "seed": None,
                **params,
            }
        separator = Separator(**kwargs)
        _report(on_progress, 5.0, f"loading {self.model_filename}")
        try:
            separator.load_model(model_filename=self.model_filename)
        except ImportError as exc:
            raise SeparationError(
                "This vocal model needs a one-time conversion of its checkpoint into MLX "
                "weights (torch is not a project dependency). Run once: "
                f"uv run --with torch python -m censorflow.workers.separate "
                "<mix.wav> <out_dir> after setting CENSORFLOW_SEPARATOR_MODEL="
                f"{self.model_filename}. Later runs load the saved .safetensors and stay "
                "MLX-only."
            ) from exc

        _report(on_progress, 10.0, "separating vocals (this is the slow part)")
        started = time.perf_counter()
        # The name is a stem name, not a filename: the library appends the output format
        # itself, so passing "vocals.wav" would write vocals.wav.wav.
        written = separator.separate(str(audio_path), custom_output_names={_VOCALS: _VOCALS})
        elapsed = time.perf_counter() - started
        path = self._find_vocals(written)
        logger.info("separated %s in %.1fs -> %s", audio_path.name, elapsed, path.name)
        _report(on_progress, 90.0, f"separated vocals in {elapsed:.1f}s")
        return path

    def _find_vocals(self, written: Sequence[str]) -> Path:
        """Locate the vocal stem: the return value first, then the output directory."""
        for candidate in written:
            if _VOCALS in Path(candidate).stem.lower():
                return Path(candidate)
        matches = sorted(self.output_dir.glob(_VOCALS_GLOB))
        if matches:
            return matches[0]
        raise SeparationError(
            "The separation model finished but no vocal stem appeared in "
            f"{self.output_dir}. Full details in the stage log."
        )

    def _derive_instrumental(self, mix_path: Path, vocals_path: Path) -> Path:
        """instrumental = mix - vocals. See the module docstring for why."""
        mix, rate = audio_io.read(mix_path)
        vocals, vrate = audio_io.read(vocals_path)
        if rate != vrate:
            raise SeparationError(
                f"The vocal stem is {vrate} Hz but the mix is {rate} Hz; they must match."
            )
        vocals = audio_io.match_length(vocals, len(mix))
        instrumental = mix - vocals
        out = self.output_dir / f"{_INSTRUMENTAL}.wav"
        audio_io.write(out, instrumental, rate, config.FLAC_SUBTYPE)
        return out


def _is_demucs_model(model_filename: str) -> bool:
    """Demucs checkpoints are YAML wrappers; RoFormer ids are ckpt or catalog names."""
    name = model_filename.lower()
    return name.endswith((".yaml", ".th")) or "htdemucs" in name


def _quality_overrides(quality: str) -> dict[str, float]:
    preset = config.SEPARATION_QUALITY.get(quality)
    if preset is None:
        raise SeparationError(
            f"Unknown separation quality {quality!r}. "
            f"Use one of: {', '.join(config.SEPARATION_QUALITY)}."
        )
    return {"shifts": int(preset["shifts"]), "overlap": float(preset["overlap"])}


def _point_library_caches_at_project_models() -> None:
    """Keep the separator's own caches inside the project, not in ~/.cache.

    The converted MLX checkpoint is the expensive artefact here: rebuilding it needs
    torch, onnx and demucs, which are deliberately not project dependencies.
    """
    config.SEPARATOR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    config.SEPARATOR_DEMUCS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("AUDIO_SEPARATOR_MODEL_DIR", str(config.SEPARATOR_MODEL_DIR))
    os.environ.setdefault("MLX_AUDIO_SEPARATOR_DEMUCS_CACHE_DIR", str(config.SEPARATOR_DEMUCS_CACHE_DIR))


def _report(on_progress: ProgressFn | None, pct: float, msg: str) -> None:
    if on_progress is not None:
        on_progress(pct, msg)