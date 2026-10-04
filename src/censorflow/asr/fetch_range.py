"""Parallel range downloads for one speech-model file.

The listing and the lock live in `fetch.py`. This is only the slicing: a CDN
address expires, so a failed slice refreshes it and tries once more.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .fetch import _HEADERS, _TIMEOUT, DownloadError, RemoteFile


def _download_one(
    client: httpx.Client,
    item: RemoteFile,
    target: Path,
    parallel: int,
    chunk: int,
    advance: Callable[[int], None],
) -> None:
    source = _Source(client, item.url)
    partial = target.with_name(target.name + ".partial")
    parts_path = target.with_name(target.name + ".parts")
    finished = _load_parts(parts_path)
    fd = os.open(partial, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        os.ftruncate(fd, item.size)
        spans = _spans(item.size, chunk)
        pending = [(start, end) for start, end in spans if start not in finished]
        for start, end in spans:
            if start in finished:
                advance(end - start + 1)
        part_lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            futures = [
                pool.submit(_slice, source, fd, start, end, advance, parts_path, part_lock)
                for start, end in pending
            ]
            for future in futures:
                future.result()
    except Exception:
        os.close(fd)
        raise
    os.close(fd)
    partial.replace(target)
    parts_path.unlink(missing_ok=True)


def _slice(
    source: _Source,
    fd: int,
    start: int,
    end: int,
    advance: Callable[[int], None],
    parts_path: Path,
    part_lock: threading.Lock,
) -> None:
    expected = end - start + 1
    last: Exception | None = None
    for _ in range(2):
        try:
            data = _read_range(source.url, start, end)
        except httpx.HTTPError as exc:
            last = exc
            source.refresh()
            continue
        if len(data) != expected:
            source.refresh()
            continue
        os.pwrite(fd, data, start)
        _remember(parts_path, start, part_lock)
        advance(expected)
        return
    raise DownloadError(
        "CensorFlow could not download the speech model. "
        "Check the internet connection and try again."
    ) from last


def _read_range(url: str, start: int, end: int) -> bytes:
    headers = {**_HEADERS, "Range": f"bytes={start}-{end}"}
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=False, headers=headers) as client:
        response = client.get(url)
    if response.status_code != 206:
        return b""
    return response.content


class _Source:
    """The CDN address for one file. It expires, so a failed slice can refresh it."""

    def __init__(self, client: httpx.Client, page: str) -> None:
        self._client = client
        self._page = page
        self._lock = threading.Lock()
        self.url = _cdn_url(client, page)

    def refresh(self) -> None:
        with self._lock:
            self.url = _cdn_url(self._client, self._page)


def _cdn_url(client: httpx.Client, page: str) -> str:
    response = client.head(page)
    location = response.headers.get("location")
    if response.status_code in {301, 302, 303, 307, 308} and location:
        return urljoin(page, location)
    if response.status_code == 200:
        return page
    raise DownloadError(
        "CensorFlow could not download the speech model. "
        "Check the internet connection and try again."
    )


def _spans(size: int, chunk: int) -> list[tuple[int, int]]:
    if size <= 0:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    while start < size:
        end = min(size, start + chunk) - 1
        spans.append((start, end))
        start = end + 1
    return spans


def _load_parts(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {int(item) for item in raw} if isinstance(raw, list) else set()


def _remember(path: Path, start: int, lock: threading.Lock) -> None:
    with lock:
        done = _load_parts(path)
        done.add(start)
        path.write_text(json.dumps(sorted(done)), encoding="utf-8")
