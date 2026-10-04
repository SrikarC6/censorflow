"""`censorflow` command line.

Two commands, both of which must keep working (`AGENTS.md`):

    censorflow serve                     start the web app on 127.0.0.1
    censorflow censor SONG --auto -o DIR  headless, every flag the UI exposes

`serve` runs the web app on 127.0.0.1 and never on a routable address. Flagged words are
only ever printed redacted.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import config, pipeline
from .audio_io import AudioError
from .compute.base import ComputeError
from .compute.local import LocalBackend
from .profanity import detect

logger = logging.getLogger("censorflow")


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        return _dispatch(args)
    except (AudioError, ComputeError) as exc:
        # The message is written for the user; the detail is already in logs/.
        logger.error("%s", exc)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="censorflow", description="Remove profanity from songs, vocals only."
    )
    subparsers = parser.add_subparsers(dest="command")

    censor = subparsers.add_parser(
        "censor", help="censor a song headlessly, without the web app"
    )
    censor.add_argument("source", type=Path, help="the song to censor")
    censor.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("out"),
        help="where to write the censored file (default: out)",
    )
    censor.add_argument(
        "--format",
        choices=config.SUPPORTED_EXPORT_FORMATS,
        default=config.DEFAULT_EXPORT_FORMAT,
        help="export format (default: %(default)s, lossless)",
    )
    censor.add_argument(
        "--auto",
        action="store_true",
        help="skip the review pause and censor every flagged word",
    )
    censor.add_argument(
        "--clip-seconds",
        type=float,
        default=None,
        metavar="N",
        help="process only the first N seconds, for fast iteration",
    )
    censor.add_argument(
        "--quality",
        choices=sorted(config.SEPARATION_QUALITY),
        default=config.DEFAULT_QUALITY,
        help="separation quality (default: %(default)s)",
    )
    censor.add_argument(
        "--job-dir",
        type=Path,
        default=None,
        help="where to keep intermediate files (default: a fresh directory under the CensorFlow home)",
    )

    serve = subparsers.add_parser("serve", help="start the web app on 127.0.0.1")
    serve.add_argument(
        "--host",
        default=config.SERVER_HOST,
        help=argparse.SUPPRESS,  # local only; overridable for tests, not for users
    )
    serve.add_argument(
        "--port", type=int, default=config.SERVER_PORT, help="default: %(default)s"
    )
    serve.add_argument("--reload", action="store_true", help="restart on code changes")
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "censor":
        return _cmd_censor(args)
    if args.command == "serve":
        return _cmd_serve(args)
    raise AssertionError(f"unhandled command {args.command!r}")


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from . import server

    logger.info("CensorFlow is starting on http://%s:%d", args.host, args.port)
    uvicorn.run(
        server.app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,
    )
    return 0


def _cmd_censor(args: argparse.Namespace) -> int:
    source: Path = args.source
    if not source.is_file():
        logger.error("No such file: %s", source)
        return 1
    if not args.auto:
        logger.error(
            "The review screen does not exist yet, so there is nothing to pause for. "
            "Pass --auto to censor every flagged word without reviewing them."
        )
        return 2

    started = time.perf_counter()
    job_dir = args.job_dir or _new_job_dir(source)
    backend = LocalBackend(job_dir)
    logger.info("job directory: %s", job_dir)

    result = pipeline.run_censor(
        source,
        job_dir,
        backend=backend,
        output_dir=args.output_dir,
        clip_seconds=args.clip_seconds,
        export_format=args.format,
        quality=args.quality,
        auto=True,
        on_progress=_on_progress,
    )
    logger.info(
        "read %d words, flagged %d (%s)",
        len(result.words),
        len(result.flags),
        ", ".join(detect.mask_flags(result.flags)) or "none",
    )
    logger.info(
        "wrote %s: %d censored word(s), %.1fs muted, %d window(s) in %.1fs",
        result.output_path,
        len(result.flags),
        result.stats.muted_seconds if result.stats else 0.0,
        len(result.windows),
        time.perf_counter() - started,
    )
    if result.stats and result.stats.clipped_samples:
        logger.warning(
            "this track peaks above full scale, so %d sample(s) were clipped on export; "
            "FLAC/WAV/MP3 cannot store anything louder than 1.0",
            result.stats.clipped_samples,
        )
    return 0


def _on_progress(pct: float, msg: str) -> None:
    logger.info("[%5.1f%%] %s", pct, msg)


def _new_job_dir(source: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source.stem)[:48]
    return config.JOBS_DIR / f"{stamp}-{safe}"


def _configure_logging() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())