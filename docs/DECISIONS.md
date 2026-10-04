# CensorFlow: decisions

One line per decision: what, why, and where the information came from.
Sources are either a verified local API (`python -c "help(...)"`, `--help`) or a URL.

## Dependencies

- `numpy`, `scipy`, `soundfile` - decoding, FLAC/WAV IO, short-time RMS.
- `mutagen` - tag reading (`©nam`/`\xa9nam`, `©ART`, `©alb`); `a.tags` on MP4/M4A.
- `fastapi`, `uvicorn[standard]`, `python-multipart` - local server, SSE, file upload.
- `httpx` - LRCLIB lookups and the scripted-client test.
- `requests` - kept alongside httpx because `syncedlyrics` pulls it in transitively anyway.
- `mlx-audio-separator` 0.1.20 (marker: darwin + arm64) - stem separation on Apple Silicon,
  no PyTorch/ONNX at inference. https://github.com/ssmall256/mlx-audio-separator
- `parakeet-mlx` 0.5.3 (marker: darwin + arm64) - ASR with word-level timestamps.
  https://github.com/senstella/parakeet-mlx
- `ruff`, `pytest` - lint and tests.

## Environment

- Python 3.11 via `uv` (project `requires-python = ">=3.11"`); system `python3` is 3.14 and is not used.
- ffmpeg 9.0.2 and ffprobe present at `/opt/homebrew/bin`.
- Machine: Apple M2, arm64, 16 GB.

## Library behaviour verified (not guessed)

- `parakeet-mlx`: `from_pretrained(repo_id)` returns `ParakeetTDT`; `model.transcribe(path)`
  returns an `AlignedResult` with `.text`, `.tokens` (flattened `AlignedToken`), `.sentences`,
  and each `AlignedSentence` has `.start/.end/.duration/.confidence`.
  Source: https://github.com/senstella/parakeet-mlx (`_autodocs/api-reference/alignment.md`)
- The Context7 docs for parakeet-mlx show `mlx-community/parakeet-ctc-0.6b-v3` as a valid repo.
  **It does not exist** on Hugging Face (checked the HF API: 404). Only the TDT v2/v3 repos exist.
  Decision: pin to `parakeet-tdt-0.6b-v3` and verify the repo id exists before use.
  Source: https://huggingface.co/api/models/mlx-community/parakeet-ctc-0.6b-v3 (404)
- `mlx-audio-separator`: `Separator(log_level, model_file_dir, output_dir, output_format, ...)`,
  then `load_model(model_filename)` and `separate(audio_file_path, custom_output_names=None) -> list[str]`.
  `separate()` returns file paths. Verified via `inspect.signature` on the installed 0.1.20.
- `mlx-audio-separator` Demucs weights need the `[convert]` extra (torch + onnx + demucs) the first
  time, to convert the official checkpoint into `~/.cache/mlx-audio-separator/demucs/*.safetensors`.
  Decision: install torch/demucs as a **throwaway `uv run --with` overlay**, never as a project
  dependency - it is a one-time build step and the resulting cache is reused forever.
  Source: https://github.com/ssmall256/mlx-audio-separator (README, "Demucs cache security and migration")
- `mlx-audio-separator` requires `mlx-audio-io>=1.3.23` or MLX native-symbol import fails.
  `uv` resolved 1.3.23 automatically; do not pin it lower.
  Source: https://github.com/ssmall256/mlx-audio-separator (README, Troubleshooting)
- `syncedlyrics` exports `search(search_term, plain_only, synced_only, save_path, providers, lang, enhanced)`
  and per-provider classes. There is **no** `get()` export; `from syncedlyrics import get` raises ImportError.
  It bundles its own `Lrclib` provider with `ROOT_URL=https://lrclib.net`.
  Verified via `inspect.signature` on the installed version.
- LRCLIB `/api/get` needs `track_name` + `artist_name` (required), `album_name` + `duration` (recommended).
  Duration is in **seconds**, range 1-3600, with a **+/-2 s** tolerance, otherwise it returns 404.
  LRCLIB requires a descriptive `User-Agent` (name, version, project link or email); `X-User-Agent`
  and `Lrclib-Client` are accepted alternatives.
  Source: https://lrclib.net/docs
- LRCLIB records expose `hasWordSync` and a raw `lyricsfile` (Lyricsfile YAML, always present).
  Verified schema: `version`, `metadata{title,artist,album,duration_ms,instrumental,start_ms,end_ms}`,
  `plain`, and `lines[]` with `text`, `start_ms`, `end_ms`.
  Decision: parse `lyricsfile` for line timing because it gives **both** `start_ms` and `end_ms`,
  which makes the "proportional position inside a line" estimate for lyrics-only flags much tighter than
  an LRC line-start timestamp alone.
  Source: https://lrclib.net/docs
- HF model downloads stalled (frozen at 2.08 GB of 2.51 GB) with the default Xet transport on this
  machine. Recovery: `HF_HUB_DISABLE_XET=1` falls back to plain resumable HTTP range requests.
  Decision: set `HF_HUB_DISABLE_XET=1` for large model fetches here.
  Source: local observation, no external doc.

## Project layout

- `lyricsfile` YAML parsed with `pyyaml`, which `mlx-audio-separator` already requires, so no new
  dependency is added just for lyrics.

## Rendering

- Instrumental is derived as `mix - vocals`, **not** as `drums + bass + other`.
  Reason: measured on a real clip, the four Demucs stems sum to the mix with RMS error 0.030 and a peak
  sample error of 0.88, so a 3-stem sum is not faithful enough to be the reference "instrumental".
- The render only ever needs the `vocals` stem: `final = mix - vocals * mask`. The instrumental stem is
  kept for the "are there vocals at all?" check and for future stem mode.