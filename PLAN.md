# CensorFlow plan

Living checklist. Update as work proceeds. See `AGENTS.md` for standing rules.

## Phase 0 - environment and spikes

- [x] Verify `ffmpeg -version`, `uv --version`, Apple Silicon, RAM
- [x] `git init` (already a repo), `uv init`, folder tree, `.gitignore`
- [x] Check for `reference/old_version/` (absent - nothing to skim)
- [ ] Get a 30-60 s vocal-heavy clip into `samples/` from the user
- [ ] Spike A: separation (mlx-audio-separator `htdemucs`, fallback demucs CLI)
- [ ] Spike B: ASR (`parakeet-mlx`, tdt-0.6b-v2 vs v3, word timestamps)
- [ ] Spike C: lyrics (LRCLIB `/api/get`, `syncedlyrics`) - structure only
- [ ] `docs/SPIKE_RESULTS.md`, `docs/DECISIONS.md`

## Phase 1 - core pipeline and CLI

- [ ] `config.py` (all named constants)
- [ ] `audio_io.py` (ffprobe validate, decode to 44.1k stereo f32, encode, clip)
- [ ] `compute/base.py`, `local.py`, `remote.py` stub
- [ ] `workers/` one-shot JSON-line entry points
- [ ] `separation/` interface + Demucs backend
- [ ] `asr/` interface + parakeet-mlx backend
- [ ] `profanity/detect.py` + `data/` wordlists
- [ ] `censor/windows.py`, `censor/render.py`
- [ ] `cli.py` with `censor` (+ `--auto`, `--clip-seconds`)
- [ ] Tests: subtraction, windows, detection, format
- [ ] `uv run pytest -q` passes; headless run produces `_clean.flac`

## Phase 2 - metadata, lyrics, merging

- [ ] `metadata.py` (mutagen + filename fallback + CLI overrides)
- [ ] `lyrics/lrclib.py`, `lyrics/synced.py`, `lyrics/merge.py`
- [ ] Timeouts, try/except, gitignored cache; lookup failure never fails a job
- [ ] Tests: merge with fake lyric data
- [ ] Provenance reported per flag; job without lyrics still completes

## Phase 3 - server and jobs

- [ ] `jobs.py` state machine + on-disk layout
- [ ] `server.py` endpoints, SSE, review read/write, region-only clip
- [ ] Stem routes return 501
- [ ] Scripted `httpx` client test; bind 127.0.0.1 only

## Phase 4 - web UI

- [ ] 4a: `flipdisc.js`, `font5x7.js`, `web/font-test.html` - STOP, user eyeballs glyphs
- [ ] 4b: Welcome, Mode, Processing, Result
- [ ] 4c: Review screen
- [ ] 4d: Stems skeleton + `docs/STEMS_TODO.md`

## Phase 5 - hardening and docs

- [ ] Friendly errors (ffmpeg missing, unreadable, no vocals, model download, disk full)
- [ ] First-run model download progress in the UI
- [ ] `README.md` (install, run, dev flags, layout, troubleshooting)
- [ ] Clean clone: `uv sync && uv run censorflow serve`
- [ ] Re-read `AGENTS.md`, confirm every non-negotiable rule is met and tested