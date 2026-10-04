"""Separator config: RoFormer default, Demucs as a named fallback."""

from __future__ import annotations

from pathlib import Path

from censorflow import config
from censorflow.separation.base import make_separator
from censorflow.separation.demucs import DemucsSeparator, _is_demucs_model


def test_censor_default_is_kim_vocal_roformer() -> None:
    assert config.SEPARATOR_MODEL == "vocals_mel_band_roformer.ckpt"
    assert config.DEMUCS_MODEL == "htdemucs_ft.yaml"
    assert config.SEPARATOR_MODEL != config.DEMUCS_MODEL


def test_make_separator_uses_configured_model(tmp_path: Path) -> None:
    sep = make_separator(quality=config.QUALITY_FAST, output_dir=tmp_path)
    assert isinstance(sep, DemucsSeparator)
    assert sep.model_filename == config.SEPARATOR_MODEL


def test_demucs_fallback_is_still_selectable(tmp_path: Path) -> None:
    sep = DemucsSeparator(
        quality=config.QUALITY_FAST,
        output_dir=tmp_path,
        model_filename=config.DEMUCS_MODEL,
    )
    assert sep.model_filename == config.DEMUCS_MODEL
    assert _is_demucs_model(config.DEMUCS_MODEL)
    assert not _is_demucs_model(config.SEPARATOR_MODEL)
    assert not _is_demucs_model("mel-roformer-zfturbo-vocals-v1-mlx")
