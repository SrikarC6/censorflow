# CensorFlow

CensorFlow removes profanity from a song by silencing only the vocals at the flagged words. The instrumental keeps playing. Everything runs on your machine.

Stem mixing is a skeleton screen. The controls are visible and disabled.

## Install

You need Python 3.11, [uv](https://docs.astral.sh/uv/), and ffmpeg.

```bash
brew install ffmpeg
uv sync
```

Speech and separation weights download on first use into `models/` (gitignored, a few gigabytes). If the speech model is missing, the welcome screen offers GET SPEECH MODEL and shows the download as it runs. A headless censor fetches the same weights during transcription.

## Run

```bash
uv run censorflow serve
```

Open http://127.0.0.1:8765. The server binds to localhost only.

Headless, accepting every flag:

```bash
uv run censorflow censor path/to/song.m4a --auto -o out
```

Useful flags:

- `--clip-seconds 30` processes only the start of the file.
- `--quality fast` or `--quality pro`. Pro uses more overlap and is slower. The Mode screen offers the same choice.
- `--format flac` (default), `wav`, or `mp3`.

Drop a song on the page, choose Censor, review the flags, then render. A server restart drops a job that is still running. A finished job can be reopened with `/?job=<id>` until the process exits.

## Layout

```
src/censorflow/   pipeline, server, CLI
web/              the flip-disc UI
tests/            pytest
data/             profanity lists
docs/             decisions and the stem-mode checklist
samples/          your songs (gitignored)
models/           weights (gitignored)
```

Jobs, logs, and the lyrics cache live under `~/.censorflow/`.

## Troubleshooting

- **ffmpeg is not installed.** `brew install ffmpeg`, then reload the page.
- **The speech model is not downloaded yet.** Press GET SPEECH MODEL on the welcome screen. The bar shows how far the download has got. You need a network connection that one time.
- **No vocals were found.** The separator returned silence, so there is nothing to censor.
- **The disk is full.** Free space and try the upload again.
- **CensorFlow could not find any audio in that file.** ffmpeg could not read a stream. The extension is not what is checked.
- **A stage timed out.** A worker that runs longer than 45 minutes is stopped so the server does not hang. Details are in `~/.censorflow/logs/<job>/`.

```bash
uv run pytest -q
uv run ruff check .
```
