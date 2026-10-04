"""The speech-model download: range requests, and the poll the UI reads.

The bytes come from a local server. Nothing here contacts Hugging Face.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from censorflow import config, server
from censorflow.asr.fetch import (
    DownloadError,
    RemoteFile,
    download_files,
    list_asr_files,
)
from censorflow.asr.install import SpeechModelInstall

BLOB = bytes(range(256)) * 200


class _Handler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        if self.path.startswith("/resolve/"):
            port = self.server.server_address[1]
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/cdn/blob")
            self.end_headers()
            return
        self.send_error(404)

    def do_GET(self) -> None:
        if self.path.startswith("/tree"):
            body = json.dumps(
                [
                    {"path": name, "size": len(BLOB)}
                    for name in (
                        "config.json",
                        "model.safetensors",
                        "tokenizer.model",
                        "tokenizer.vocab",
                        "vocab.txt",
                    )
                ]
            ).encode()
            self._send(200, body)
            return
        if self.path.startswith("/cdn/"):
            self.server.hits += 1
            start, end = _range(self.headers.get("Range"), len(BLOB))
            chunk = BLOB[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(BLOB)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_error(404)

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _range(header: str | None, size: int) -> tuple[int, int]:
    assert header is not None
    start_s, end_s = header.removeprefix("bytes=").split("-")
    return int(start_s), int(end_s) if end_s else size - 1


@pytest.fixture
def origin() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.hits = 0
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


def test_a_file_is_reassembled_from_ranges(origin: ThreadingHTTPServer, tmp_path: Path) -> None:
    port = origin.server_address[1]
    seen: list[float] = []
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        download_files(
            client,
            [RemoteFile("config.json", len(BLOB), f"http://127.0.0.1:{port}/resolve/config.json")],
            tmp_path,
            lambda pct, _msg: seen.append(pct),
            parallel=4,
            chunk_bytes=8_000,
        )
    assert (tmp_path / "config.json").read_bytes() == BLOB
    assert seen[-1] == 100.0
    assert origin.hits > 1


def test_a_file_already_the_right_size_is_not_fetched(
    origin: ThreadingHTTPServer, tmp_path: Path
) -> None:
    port = origin.server_address[1]
    (tmp_path / "config.json").write_bytes(BLOB)
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        download_files(
            client,
            [RemoteFile("config.json", len(BLOB), f"http://127.0.0.1:{port}/resolve/config.json")],
            tmp_path,
            parallel=2,
            chunk_bytes=8_000,
        )
    assert origin.hits == 0


def test_the_tree_listing_names_the_weight_files(
    origin: ThreadingHTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = origin.server_address[1]
    monkeypatch.setattr(
        "censorflow.asr.fetch._TREE", f"http://127.0.0.1:{port}/tree?repo={{repo}}"
    )
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        files = list_asr_files(client, "mlx-community/parakeet-tdt-0.6b-v3")
    assert {item.name for item in files} == {
        "config.json",
        "model.safetensors",
        "tokenizer.model",
        "tokenizer.vocab",
        "vocab.txt",
    }
    assert all(item.size == len(BLOB) for item in files)
    assert files[0].url.endswith("/resolve/main/config.json")


def test_list_asr_files_refuses_a_server_that_will_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self: httpx.Client, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(503, request=request)

    monkeypatch.setattr(httpx.Client, "get", refuse)
    with httpx.Client() as client, pytest.raises(DownloadError, match="internet"):
        list_asr_files(client, "mlx-community/parakeet-tdt-0.6b-v3")


def test_the_ui_can_start_a_download_and_read_its_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    app = server.create_app()
    finished = threading.Event()

    def fake(on_progress, dest=None, model_id=None) -> Path:
        on_progress(40.0, "downloading the speech model")
        directory = tmp_path / "parakeet-tdt-0.6b-v3"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "config.json").write_text("{}", encoding="utf-8")
        (directory / "model.safetensors").write_bytes(b"weights")
        on_progress(100.0, "the speech model is ready")
        finished.set()
        return directory

    app.state.models._fetch = fake
    with TestClient(app) as client:
        started = client.post("/api/models/asr")
        assert started.status_code == 200
        assert finished.wait(2.0)
        payload = client.get("/api/models/asr").json()
    assert payload["present"] is True
    assert payload["state"] == "done"
    assert payload["pct"] == 100.0


def test_a_failed_download_is_a_friendly_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    app = server.create_app()
    finished = threading.Event()

    def fake(on_progress, dest=None, model_id=None) -> Path:
        finished.set()
        raise DownloadError(
            "CensorFlow could not download the speech model. "
            "Check the internet connection and try again."
        )

    app.state.models._fetch = fake
    with TestClient(app) as client:
        client.post("/api/models/asr")
        assert finished.wait(2.0)
        # The thread records the error just after the raise. Give it a moment.
        payload = {}
        for _ in range(20):
            payload = client.get("/api/models/asr").json()
            if payload["state"] == "error":
                break
            threading.Event().wait(0.05)
    assert payload["present"] is False
    assert payload["state"] == "error"
    assert "internet" in payload["message"]


def test_a_model_already_on_disk_is_not_downloaded_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    directory = tmp_path / "parakeet-tdt-0.6b-v3"
    directory.mkdir()
    (directory / "config.json").write_text("{}", encoding="utf-8")
    (directory / "model.safetensors").write_bytes(b"weights")
    install = SpeechModelInstall()
    called = False

    def fake(on_progress, dest=None, model_id=None) -> Path:
        nonlocal called
        called = True
        return directory

    install._fetch = fake
    payload = install.start()
    assert called is False
    assert payload["present"] is True
    assert payload["state"] == "done"
