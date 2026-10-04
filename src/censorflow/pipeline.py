"""Headless orchestration of the censor pipeline.

This is the one place the stages run in order, so both the CLI and the server drive exactly
the same code. The job directory layout is the one in `AGENTS.md`:

    <job>/original.<ext>   mix.wav   vocals.wav   instrumental.wav
            words.json     flags.json   windows.json   output.flac

Stages 1-5 of the pipeline contract, then 7-8. Stage 6, the review pause, is the caller's
job: pass `auto=True` to render immediately, or inspect `result.flags` and render later.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import audio_io, config, lyrics
from .censor import render as render_mod
from .censor import windows as win
from .compute.base import ComputeBackend
from .metadata import safe_filename, title_from_filename
from .models import Flag, LyricLine, ProgressFn, StageFn, TrackInfo, Word
from .profanity import detect

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineResult:
    """Everything the caller needs after a run, whether or not it rendered."""

    job_dir: Path
    mix_path: Path
    stems: dict[str, Path]
    track: TrackInfo = field(default_factory=TrackInfo)
    lyric_lines: list[LyricLine] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    windows: list[win.Window] = field(default_factory=list)
    stats: render_mod.RenderStats | None = None
    output_path: Path | None = None

    def censor_spans(self) -> list[tuple[float, float]]:
        """The flagged spans the user has left switched on, in ascending order."""
        spans = sorted(
            (flag.start, flag.end) for flag in self.flags if flag.censor and flag.end > flag.start
        )
        deduped: list[tuple[float, float]] = []
        for span in spans:
            if deduped and abs(span[0] - deduped[-1][0]) < 1e-6:
                continue
            deduped.append(span)
        return deduped


def run_censor(
    source: Path,
    job_dir: Path,
    *,
    backend: ComputeBackend,
    output_dir: Path | None = None,
    clip_seconds: float | None = None,
    export_format: str = config.DEFAULT_EXPORT_FORMAT,
    quality: str = config.DEFAULT_QUALITY,
    auto: bool = False,
    on_progress: ProgressFn | None = None,
    on_stage: StageFn | None = None,
) -> PipelineResult:
    """Decode, separate, transcribe and detect; render when `auto` is set.

    `on_stage` is called once per stage with a name from the job-state vocabulary, so the
    server can show which stage is running without parsing progress messages.
    """
    source = Path(source).expanduser().resolve()
    job_dir = Path(job_dir).expanduser()
    job_dir.mkdir(parents=True, exist_ok=True)

    audio_io.check_ffmpeg()
    if not source.is_file():
        raise audio_io.AudioError(f"No such file: {source}")
    if not audio_io.has_audio_stream(source):
        raise audio_io.AudioError(f"{source.name} has no audio stream ffmpeg can read.")

    _stage(on_stage, "fetching_lyrics")
    lookup = lyrics.lookup(source)
    _write_json(job_dir / "lyrics.json", lookup.to_payload())

    _report(on_progress, 1.0, "reading tags and preparing the job")
    original = job_dir / f"original{source.suffix.lower() or '.audio'}"
    if not original.exists():
        shutil.copy2(source, original)

    _stage(on_stage, "decoding")
    _report(on_progress, 3.0, "decoding audio")
    mix_path = audio_io.decode(
        source, job_dir / "mix.wav", duration=clip_seconds
    )

    _stage(on_stage, "separating")
    _report(on_progress, 8.0, "separating the vocals")
    stems = backend.separate(
        mix_path, config.STEMS_CENSOR, quality, _scaled(on_progress, 8, 70)
    )
    vocals_path = stems.get("vocals")
    if vocals_path is None:
        raise audio_io.AudioError("The separation stage produced no vocal stem.")
    _assert_stem_lengths(mix_path, stems)

    _stage(on_stage, "transcribing")
    _report(on_progress, 72.0, "reading the vocal stem")
    words = backend.transcribe(vocals_path, _scaled(on_progress, 72, 97))
    words = lyrics.align_words(words, lookup.lines)
    _write_json(job_dir / "words.json", [word.to_dict() for word in words])

    _stage(on_stage, "detecting")
    _report(on_progress, 98.0, "checking the transcript")
    region_end = len(audio_io.read(mix_path)[0]) / config.SAMPLE_RATE
    flags = lyrics.merge_flags(words, lookup.lines, region_end=region_end)
    _write_json(job_dir / "lyrics_flags.json", [flag.to_dict() for flag in flags])
    logger.info(
        "job %s: %d words, %d flagged (%s); provenance %s",
        job_dir.name,
        len(words),
        len(flags),
        ", ".join(detect.mask_flags(flags)) or "none",
        _provenance_summary(flags),
    )

    result = PipelineResult(
        job_dir=job_dir,
        mix_path=mix_path,
        stems=stems,
        track=lookup.track,
        lyric_lines=lookup.lines,
        words=words,
        flags=flags,
    )
    if not auto:
        _report(on_progress, 100.0, "ready for review")
        return result

    _stage(on_stage, "rendering")
    output_path = _output_path(source, output_dir or job_dir, export_format, lookup.track)
    stats = render_reviewed(result, output_path, export_format)
    _report(on_progress, 100.0, f"done in {stats.muted_seconds:.1f}s muted")
    return result


def render_reviewed(
    result: PipelineResult, output_path: Path, export_format: str = config.DEFAULT_EXPORT_FORMAT
) -> render_mod.RenderStats:
    """Render a job that has already been through review. Used by the server."""
    stats = _render(result, Path(output_path), export_format)
    result.stats = stats
    result.output_path = stats.output_path
    result.windows = stats.windows
    _write_json(
        result.job_dir / "windows.json", win.windows_to_json(stats.windows)
    )
    return stats


def _render(result: PipelineResult, output_path: Path, export_format: str) -> render_mod.RenderStats:
    started = time.perf_counter()
    stats = render_mod.render_to_file(
        result.mix_path,
        result.stems["vocals"],
        result.censor_spans(),
        output_path,
        export_format=export_format,
        tags_from=_original_audio(result.job_dir),
    )
    logger.info("render took %.1fs", time.perf_counter() - started)
    return stats


def _original_audio(job_dir: Path) -> Path | None:
    """The untouched upload in a job directory, if this job kept one."""
    matches = sorted(Path(job_dir).glob("original.*"))
    return matches[0] if matches else None


def _output_path(
    source: Path, out_dir: Path, export_format: str, track: TrackInfo | None = None
) -> Path:
    """`<song name>_clean.<ext>`: one output file, named after the song rather than the file.

    `Path.stem` is not usable here: `Path("03. Carti.m4a").stem` is `"03"`, because it
    treats `". Carti"` as the suffix. `metadata.title_from_filename` strips only a known
    audio extension, and the track title wins when the tags gave us one.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    name = (track.title if track and track.title else None) or title_from_filename(source)
    if not name:
        name = source.stem
    name = safe_filename(name)
    return out_dir / f"{name}_clean.{export_format.lstrip('.').lower()}"


def _assert_stem_lengths(mix_path: Path, stems: dict[str, Path]) -> None:
    """Every stem must line up with the mix, or the subtraction is wrong."""
    mix_frames = len(audio_io.read(mix_path)[0])
    for name, path in stems.items():
        frames = len(audio_io.read(path)[0])
        drift = abs(frames - mix_frames)
        if drift > config.STEM_LENGTH_TOLERANCE_SAMPLES:
            logger.warning(
                "%s stem is %d samples out (%d vs %d)", name, drift, frames, mix_frames
            )
        else:
            logger.debug("%s stem matches the mix (%d frames)", name, frames)


def _provenance_summary(flags: list[Flag]) -> str:
    """How the flags were found, for the log line. No word text, so it is safe to print."""
    if not flags:
        return "none"
    counts: dict[str, int] = {}
    for flag in flags:
        counts[flag.source] = counts.get(flag.source, 0) + 1
    return ", ".join(f"{counts[key]} {key}" for key in sorted(counts))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _report(on_progress: ProgressFn | None, pct: float, msg: str) -> None:
    if on_progress is not None:
        on_progress(pct, msg)


def _stage(on_stage: StageFn | None, name: str) -> None:
    if on_stage is not None:
        on_stage(name)


def _scaled(on_progress: ProgressFn | None, lo: float, hi: float) -> ProgressFn | None:
    """Re-map a stage's own 0-100 progress onto a slice of the whole job."""
    if on_progress is None:
        return None

    def forward(pct: float, msg: str) -> None:
        on_progress(lo + (hi - lo) * max(0.0, min(100.0, pct)) / 100.0, msg)

    return forward