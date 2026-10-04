"""Download the speech model with parallel HTTP range requests.

Hugging Face lists the files at ``/api/models/<repo>/tree/main`` and serves the
bytes from a CDN that answers ``Range``. A single connection crawled, and the
Xet transport stalled, so each large file is fetched as several slices at once.
Verified against the live repo on 2026-10-04: a ``Range: bytes=0-15`` request
returned ``206`` and the safetensors header.
"""

from __future__ import annotations

import errno
import fcntl
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

from .. import config
from ..models import ProgressFn

logger = logging.getLogger(__name__)

# What `from_pretrained` reads. The repo also carries a README, which we skip.
ASR_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.model",
    "tokenizer.vocab",
    "vocab.txt",
)
_TREE = "https://huggingface.co/api/models/{repo}/tree/main"
_RESOLVE = "https://huggingface.co/{repo}/resolve/main/{name}"
_TIMEOUT = httpx.Timeout(30.0, read=120.0)
_HEADERS = {"User-Agent": "censorflow"}


class DownloadError(Exception):
    """A failure the user can act on. The cause is already in the log."""


@dataclass(frozen=True)
class RemoteFile:
    """One weight file: its name, its size, and the page that redirects to the CDN."""

    name: str
    size: int
    url: str


def model_is_present(directory: Path | None = None) -> bool:
    """True when the weights the transcriber loads are on disk."""
    directory = directory or _default_dir()
    return (directory / "config.json").is_file() and (directory / "model.safetensors").is_file()


def fetch_asr_model(
    on_progress: ProgressFn | None = None,
    dest: Path | None = None,
    model_id: str | None = None,
) -> Path:
    """Download whatever is missing into `dest`, then return that directory.

    A second caller blocks on a file lock until the first one finishes, then
    finds the files already there. Finished files are not fetched again.
    """
    dest = dest or _default_dir(model_id)
    dest.mkdir(parents=True, exist_ok=True)
    lock_path = dest / ".download.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        _flock(lock.fileno())
        try:
            if model_is_present(dest):
                _report(on_progress, 100.0, "the speech model is ready")
                return dest
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=False, headers=_HEADERS) as client:
                files = list_asr_files(client, model_id or config.ASR_MODEL)
                download_files(client, files, dest, on_progress)
        except DownloadError:
            raise
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise DownloadError(
                    "The disk is full, so CensorFlow could not save the speech model."
                ) from exc
            logger.exception("speech model download failed")
            raise DownloadError(
                "CensorFlow could not download the speech model. "
                "Check the internet connection and try again."
            ) from exc
        except httpx.HTTPError as exc:
            logger.exception("speech model download failed")
            raise DownloadError(
                "CensorFlow could not download the speech model. "
                "Check the internet connection and try again."
            ) from exc
    return dest


def list_asr_files(client: httpx.Client, model_id: str) -> list[RemoteFile]:
    """The weight files for `model_id`, sizes taken from the Hub tree listing."""
    response = client.get(_TREE.format(repo=model_id))
    if response.status_code != 200:
        raise DownloadError(
            "CensorFlow could not download the speech model. "
            "Check the internet connection and try again."
        )
    wanted = set(ASR_FILES)
    files: list[RemoteFile] = []
    for item in response.json():
        name = item.get("path")
        if name not in wanted:
            continue
        files.append(
            RemoteFile(
                name=name,
                size=int(item["size"]),
                url=_RESOLVE.format(repo=model_id, name=name),
            )
        )
    missing = wanted - {item.name for item in files}
    if missing:
        raise DownloadError(
            "CensorFlow could not download the speech model. "
            "The model page did not list every file it needs."
        )
    return files


def download_files(
    client: httpx.Client,
    files: list[RemoteFile],
    dest: Path,
    on_progress: ProgressFn | None = None,
    *,
    parallel: int | None = None,
    chunk_bytes: int | None = None,
) -> None:
    """Fetch `files` into `dest`. Files already the right size are left alone."""

    from .fetch_range import _download_one

    dest.mkdir(parents=True, exist_ok=True)
    total = sum(item.size for item in files)
    done = 0
    lock = threading.Lock()

    def advance(count: int, name: str) -> None:
        nonlocal done
        with lock:
            done += count
            pct = 100.0 if total == 0 else min(100.0, 100.0 * done / total)
        _report(on_progress, pct, f"downloading the speech model ({name})")

    workers = parallel or config.ASR_DOWNLOAD_PARALLEL
    chunk = chunk_bytes or config.ASR_DOWNLOAD_CHUNK_BYTES
    for item in files:
        target = dest / item.name
        if item.size == 0:
            target.write_bytes(b"")
            advance(0, item.name)
            continue
        if target.is_file() and target.stat().st_size == item.size:
            advance(item.size, item.name)
            continue
        _download_one(
            client,
            item,
            target,
            workers,
            chunk,
            lambda count, name=item.name: advance(count, name),
        )
    _report(on_progress, 100.0, "the speech model is ready")


def _default_dir(model_id: str | None = None) -> Path:
    repo = model_id or config.ASR_MODEL
    return config.MODEL_DIR / repo.rsplit("/", 1)[-1]


def _report(on_progress: ProgressFn | None, pct: float, msg: str) -> None:
    if on_progress is not None:
        on_progress(pct, msg)


def _flock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_EX)
