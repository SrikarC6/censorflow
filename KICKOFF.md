# CensorFlow: kickoff prompt

You are building CensorFlow from scratch, locally, on a MacBook Air M2 (16 GB). `AGENTS.md` in the project root holds your standing rules; follow it exactly. Work in the phases below, in order. Do not skip ahead.

## First actions

1. Read `AGENTS.md`.
2. Create `PLAN.md` containing the phases below as checkboxes. Update it as you go.
3. If `reference/old_version/` exists, skim it for message wording and UI ideas only. Its architecture is wrong (see "Lessons from the previous version" in `AGENTS.md`).
4. Start Phase 0.

## What the user can do (the flow)

1. Upload a music file in almost any format (mp3, m4a/AAC/ALAC, ogg, opus, flac, wav, aiff, ...).
2. Choose **Censor** or **Stems**.
3. **Censor:** stems are extracted (vocals vs everything else) -> synced lyrics are fetched if they exist -> the vocals are transcribed -> profane words are detected -> the user reviews and fixes the flags -> only the vocals are silenced at those words -> the result is rendered and returned.
4. **Stems:** skeleton screen only (see "Stem mode" in `AGENTS.md`). Do not implement it.

## Phase 0: environment and spikes (no app code yet)

- Verify `ffmpeg -version`, `uv --version`, and the machine (Apple Silicon).
- `git init`, `uv init`, create the folder tree from `AGENTS.md`, add a `.gitignore` (samples, logs, `.venv`, `.censorflow`, caches, lyrics cache).
- If `samples/` has no audio clip, STOP and ask the user for a 30-60 s vocal-heavy clip. Never download music yourself.
- **Spike A, separation.** On the clip, try `mlx-audio-separator` with `htdemucs` first. If it will not install or run after two attempts, fall back to the `demucs` CLI in a subprocess with pinned compatible torch/torchaudio versions. Record exact commands, package versions, wall time, and rough peak memory (`/usr/bin/time -l`).
- **Spike B, ASR.** Run `parakeet-mlx` on the vocal stem with word-level timestamps. Compare `mlx-community/parakeet-tdt-0.6b-v2` against `...-v3` on the clip and note which transcribes sung words better. Record timings.
- **Spike C, lyrics.** Query LRCLIB (`/api/get` with track, artist, album, duration; send a descriptive User-Agent) and `syncedlyrics`. Record whether results are line-level or word-level. Do not write lyric text into docs or logs: record counts and structure only.
- Write findings to `docs/SPIKE_RESULTS.md` and choices to `docs/DECISIONS.md`.

**Done when:** each spike has a working command or a documented failure with a chosen fallback.

## Phase 1: core pipeline and CLI (headless, no UI)

Implement `audio_io`, `compute` (local only), the worker scripts, the separator and ASR backends, `profanity`, `censor/windows.py`, `censor/render.py`, and the `censorflow censor` command with `--auto` and `--clip-seconds`.

Required tests (all synthetic):

- **Subtraction test.** Build `mix = vocal_tone + instrumental_tone`. Provide both as exact stems. After rendering with one window, the instrumental is still present inside the window, the vocal is gone inside the window, and outside the window the output equals the original within 1e-6.
- **Window tests.** Short word gets padded to at least 150 ms; a stretched word (long high-energy tail after the ASR end) is fully covered; extension stops at the next word; overlapping windows merge; fades are present.
- **Detection tests** using a placeholder wordlist of innocuous words: repeated-letter collapse, suffix handling, whole-token matching only, allowlist respected.
- **Format test.** ffmpeg-generated tiny files in mp3, m4a, ogg, flac, wav all decode to the same working format.

**Done when:** `uv run pytest -q` passes, and `uv run censorflow censor samples/<clip> --auto -o out/` produces a `_clean.flac` where the instrumental is audibly intact. Report the flagged words as masked tokens (first letter plus asterisks), never in full.

## Phase 2: metadata, lyrics, merging

Implement `metadata.py` (mutagen: artist, title, album, duration; fall back to the filename; allow manual entry via CLI flags), `lyrics/lrclib.py`, `lyrics/synced.py`, and `lyrics/merge.py` per "Profanity detection" in `AGENTS.md`. Use timeouts, try/except, and a local gitignored cache. Lookup failure must never fail the job.

Tests: merge logic with fake lyric data (flag found by both, lyrics-only flag with approximate window, ASR-only flag).

**Done when:** a job with lyrics available reports provenance (`asr`, `lyrics`, `both`) per flag, and a job without lyrics still completes.

## Phase 3: server and jobs

Implement `jobs.py` and `server.py` with the endpoints and states in `AGENTS.md`, SSE progress, the review read/write endpoints, and the region-only preview clip endpoint. Stem routes return 501. Pipeline pauses at `awaiting_review`.

**Done when:** a scripted client (use `httpx` in a test or a short script) can upload a clip, watch events, fetch the review JSON, edit one flag, post it back, and download the output. Bind to 127.0.0.1 only.

## Phase 4: web UI

- **4a.** `flipdisc.js` (grid + renderer + hit-testing) and `font5x7.js`, plus `web/font-test.html`. STOP here and ask the user to eyeball the glyphs before continuing.
- **4b.** Welcome, Mode, Processing, and Result screens wired to the API.
- **4c.** Review screen (HTML overlay) with every requirement listed in `AGENTS.md`.
- **4d.** Stems skeleton screen with disabled controls and `docs/STEMS_TODO.md`.

Remember: no animation anywhere, dense dots, the grid fills the entire window.

**Done when:** the whole censor flow works end to end in a browser on the M2, and the user confirms the look matches the amber flip-disc reference.

## Phase 5: hardening and docs

- Friendly errors for: missing ffmpeg, unreadable file, no vocals found, model download failure (show that a first-run download is happening), disk full.
- First-run model download progress surfaced in the UI.
- `README.md`: install (`brew install ffmpeg uv`), run, dev flags, project layout, troubleshooting.
- Confirm a clean clone installs and runs with `uv sync && uv run censorflow serve`.
- Final check: re-read `AGENTS.md` and confirm every non-negotiable rule is met and tested.

**Done when:** a fresh clone works from the README alone.

## Reporting format (end of each phase)

```
Phase N complete
- Works: ...
- Verify with: <exact commands>
- Known issues: ...
- Next: Phase N+1
```

Begin now with the first actions.
