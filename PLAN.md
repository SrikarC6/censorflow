# CensorFlow plan

Living checklist. Update as work proceeds. See `AGENTS.md` for standing rules.

## Phase 0 - environment and spikes

- [x] Verify `ffmpeg -version`, `uv --version`, Apple Silicon, RAM
- [x] `git init` (already a repo), `uv init`, folder tree, `.gitignore`
- [x] Check for `reference/old_version/` (absent - nothing to skim)
- [x] Get a 30-60 s vocal-heavy clip into `samples/` from the user
- [x] Spike A: separation (mlx-audio-separator `htdemucs`, fallback demucs CLI)
- [x] Spike B: ASR (`parakeet-mlx` tdt-0.6b-v3; v2 comparison skipped, see `docs/SPIKE_B_ASR.md`)
- [x] Spike C: lyrics (LRCLIB `/api/get`, `syncedlyrics`) - structure only
- [x] `docs/SPIKE_RESULTS.md`, `docs/DECISIONS.md`

## Phase 1 - core pipeline and CLI

- [x] `config.py` (all named constants)
- [x] `audio_io.py` (ffprobe validate, decode to 44.1k stereo f32, encode, clip)
- [x] `compute/base.py`, `local.py`, `remote.py` stub
- [x] `workers/` one-shot JSON-line entry points
- [x] `separation/` interface + Demucs backend
- [x] `asr/` interface + parakeet-mlx backend
- [x] `profanity/detect.py` + `data/` wordlists
- [x] `censor/windows.py`, `censor/render.py`
- [x] `cli.py` with `censor` (+ `--auto`, `--clip-seconds`)
- [x] Tests: subtraction, windows, detection, format
- [x] `uv run pytest -q` passes; headless run produces `_clean.flac`

## Phase 2 - metadata, lyrics, merging

- [x] `metadata.py` (mutagen + filename fallback + CLI overrides)
- [x] `lyrics/lrclib.py`, `lyrics/synced.py`, `lyrics/merge.py`
- [x] Timeouts, try/except, gitignored cache; lookup failure never fails a job
- [x] Tests: merge with fake lyric data
- [x] Provenance reported per flag; job without lyrics still completes

## Phase 3 - server and jobs

- [x] `jobs.py` state machine + on-disk layout
- [x] `server.py` endpoints, SSE, review read/write, region-only clip
- [x] Stem routes return 501
- [x] Scripted `httpx` client test; bind 127.0.0.1 only

## Phase 4 - web UI

- [x] 4a: `flipdisc.js`, `font5x7.js`, `flip-motion.js`, `flip-sound.js`, `web/style.css`, `web/font-test.html`
  - serif 7x9 default set, denser dots, single dot layer, animation + flip sounds behind toggles
  - sans is the default again (serif opt-in behind FONT: SERIF); buttons verified clickable
  - **awaiting the user's eyeball check**
- [ ] 4b: Welcome, Mode, Processing, Result
- [ ] 4c: Review screen
- [ ] 4d: Stems skeleton + `docs/STEMS_TODO.md`

## Phase 5 - hardening and docs

- [ ] Friendly errors (ffmpeg missing, unreadable, no vocals, model download, disk full)
- [ ] First-run model download progress in the UI
- [ ] `README.md` (install, run, dev flags, layout, troubleshooting)
- [ ] Clean clone: `uv sync && uv run censorflow serve`
- [ ] Re-read `AGENTS.md`, confirm every non-negotiable rule is met and tested