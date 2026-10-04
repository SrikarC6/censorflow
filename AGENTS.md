# CensorFlow: agent rules

Read this file at the start of every session, then read `PLAN.md` (your living checklist). If you ever lose context, re-read both before doing anything.

## Product

CensorFlow removes profanity from songs by silencing ONLY the vocals at flagged words. The instrumental keeps playing. A secondary mode, a four-stem mixer, is a skeleton for now.

## Non-negotiable rules

1. **Vocals only.** `final = original_mix - (vocal_stem * mask)`. The mask is 1 inside censor windows (with short fades) and 0 everywhere else. Never silence the full mix. Outside the windows the output must equal the original within float tolerance; a test enforces this.
2. **Silence, not a bleep tone.**
3. **Local first.** Everything must run offline on a MacBook Air M2 (16 GB RAM). Keep Linux compatibility (Arch, AMD ROCm GPU later): guard Apple-only imports behind platform checks. AWS offload is a LATER project. Do not build it now; only keep the `ComputeBackend` seam described below.
4. **Never guess APIs.** Before calling any library function you have not verified in this session, check Context7, `--help`, or `python -c "help(...)"`.
5. **Two failures, then search.** If the same error survives two fix attempts, search Exa for the exact error text before a third attempt.
6. **Small, reversible steps.** Use targeted edits; never rewrite a whole file to tweak it. Keep files under ~300 lines. Add no dependency without a one-line note in `docs/DECISIONS.md`.
7. **Copyright hygiene.** Never download copyrighted audio. Tests use synthetic audio. Real songs come only from the user's `samples/` folder (gitignored). Lyrics are used locally to cross-check detection only: never commit, ship, or redistribute them; cache them in a gitignored folder.
8. **Do not push to any remote.** Commit locally only.

## Lessons from the previous version (do not repeat)

- It loaded the original file and spliced silence into the whole mix, so the music went silent too. There was no stem separation at all.
- It had no review step, so users could not fix misheard or missed words.
- Whisper ran inside a UI worker thread and crashed in tqdm's multiprocessing lock (`bad value(s) in fds_to_keep`). ML stages must run as subprocesses.
- `requirements.txt` was missing its key packages. Use `pyproject.toml` and `uv`, and verify a clean install works.
- It exported lossy MP3 only. Default to lossless output.

## MCP tools

Follow each tool's own description for its parameters.

- **Context7**: current library docs. Use it BEFORE writing code against FastAPI, uvicorn, mutagen, numpy, soundfile, scipy, parakeet-mlx, mlx-audio-separator (or demucs), syncedlyrics, better-profanity, and pytest. Resolve the library first, then request docs for the specific topic you need.
- **Exa**: web and code search. Use it to (a) find current Apple Silicon install instructions and known issues, (b) look up exact error messages, (c) find real usage examples, (d) check a package is maintained, (e) read the LRCLIB API docs. Prefer official docs, READMEs, and GitHub issues over blog posts.
- Log every decision you make from a lookup in `docs/DECISIONS.md`: one line with the decision, the reason, and the source URL.

## Environment and commands

- Python 3.11 managed by **uv** (`uv init`, `uv add`, `uv run`). No global pip. Use dependency markers for platform-specific packages (for example `sys_platform == 'darwin' and platform_machine == 'arm64'` for MLX packages).
- System dependency: `ffmpeg` (`brew install ffmpeg`). Check on startup and show a friendly error if missing.
- Frontend: plain HTML + vanilla JS ES modules + canvas, served by FastAPI as static files. No Node, no bundler, no framework.
- These commands must keep working once they exist:
  - `uv run censorflow serve` (starts the web app on 127.0.0.1)
  - `uv run censorflow censor <file> --auto -o <dir>` (headless, accepts all flags)
  - `uv run pytest -q`
  - `uv run ruff check .`
- Dev shortcut: `--clip-seconds 30` processes only the first 30 s so iteration is fast.
- The machine is a fanless laptop: run one heavy stage at a time, never load two models at once.

## Architecture

```
src/censorflow/
  config.py          all tunable constants (padding, thresholds, model names, export format)
  audio_io.py        ffprobe/ffmpeg decode, encode, clip extraction
  metadata.py        mutagen tag reading (artist, title, album, duration)
  compute/
    base.py          ComputeBackend protocol: separate(), transcribe()
    local.py         LocalBackend: runs workers as subprocesses
    remote.py        RemoteBackend stub: raises NotImplementedError("planned: AWS GPU worker")
  workers/           one-shot entry points: python -m censorflow.workers.<name>
  separation/        separator backends behind one interface (first: Mel-Band-RoFormer vocals; Demucs fallback)
  asr/               parakeet-mlx first; Whisper only as an optional fallback
  lyrics/            lrclib.py, synced.py, align.py, merge.py
  profanity/         detect.py, wordlists in data/
  censor/            windows.py (mask building), render.py (subtract + export)
  jobs.py            job state machine and on-disk layout
  server.py          FastAPI app + SSE events
  cli.py             `censorflow serve` and `censorflow censor`
web/                 index.html, app.js, api.js, flipdisc.js, font5x7.js, ui.js, review.js
tests/  docs/  data/  samples/ (gitignored)  logs/ (gitignored)
```

### Subprocess workers

Every ML stage runs as `sys.executable -m censorflow.workers.<name>`. Workers print one JSON object per line on stdout and nothing else:

```
{"event":"progress","stage":"separating","pct":42.0,"msg":"..."}
{"event":"result","data":{...}}
{"event":"error","message":"..."}
```

stderr is captured to `logs/<job>/<stage>.log`. The parent only reads stdout. This keeps ML out of the server process, frees memory after each stage, and avoids the thread crash above.

### ComputeBackend seam (for the later AWS phase)

`ComputeBackend` has `separate(audio_path, stems, quality, on_progress) -> dict[str, Path]` and `transcribe(vocal_path, on_progress) -> list[Word]`. Only `LocalBackend` is implemented. `remote.py` documents the future contract in its docstring: upload audio to S3, run the same two stages on a GPU worker, download a vocal stem (FLAC) and `words.json`. Do not implement it.

## Pipeline contract (censor mode)

1. **Decode.** ffmpeg decodes any input to 44.1 kHz stereo float32 (`mix`). Validate with ffprobe, not the file extension. Support everything ffmpeg can read: mp3, m4a (AAC and ALAC), ogg, opus, flac, wav, aiff, wma, and so on.
2. **Separate.** Two stems, `vocals` and `instrumental`, via the separator interface. Assert stem length matches `mix` (pad or trim up to 2048 samples; warn above that).
3. **Transcribe.** Run ASR on the vocal stem (mono, 16 kHz as the model needs). ASR is the source of truth for *which* tokens were sung (and for words the lyrics omit). Output `Word(text, start, end, confidence, source)`.
4. **Lyrics (best effort, never blocking).** Read tags with mutagen. Query LRCLIB and `syncedlyrics`. When a lyric line is about as long as the sung phrase, `align_words` warps ASR start/end onto that line. A much longer line keeps the ASR times, so a mute is not stretched into the gap. Lyrics also add tokens ASR missed, placed between the neighbouring sung words. If lookup fails, continue with ASR alone.
5. **Detect.** Normalize words and match against the profanity list. Output `Flag(word_index, start, end, source, confidence, approx, censor=True)`.
6. **Review (pause).** The job stops in state `awaiting_review` until the user confirms. `--auto` skips the pause.
7. **Windows, mask, render.** Build windows, build the mask, compute `final = mix - vocals * mask`, export.
8. **Export.** FLAC 24-bit by default; WAV and MP3 320k selectable. Default output name `<name>_clean.<ext>`.

Job directory: `~/.censorflow/jobs/<id>/` holding `original.*`, `mix.wav`, `vocals.flac`, `words.json`, `lyrics_flags.json`, `review.json`, `output.*`.

## Censor windows (constants live in `config.py`)

Windows cover the sung syllable, then stop. An official Apple Music clean of the
same master ducks only the vocal for ~90–170 ms (median ~130 ms) and leaves the
beat up; we match that punch size. A modest tail still covers a stretched vowel.

- Start from the word's `start`/`end`.
- **Tail extension:** compute short-time RMS of the vocal stem (20 ms window, 10 ms hop, mono). `word_peak` = max RMS inside the word. Extend the end forward in 10 ms steps while RMS >= `0.30 * word_peak`; stop after 30 ms of consecutive frames below that, at a hard cap of +200 ms, or at `next_word.start - 10 ms`, whichever comes first.
- **Padding:** `PAD_PRE_MS = 20`, `PAD_POST_MS = 40`.
- **Minimum length:** `MIN_WINDOW_MS = 90`. If shorter, grow it symmetrically around the word centre.
- **Merge** windows that are closer than 30 ms.
- **Fades:** `FADE_MS = 10` raised-cosine ramps at both edges, inside the padded window.
- Everything above is a named constant, not a magic number.

## Profanity detection

- Word list lives in `data/profanity.txt`. Severe swears and insults only: the fuck / shit / bitch / n-word / pussy / ass / cum / cunt / whore family, close compounds and spellings, and insults of that severity. Mild words, drug names, and clinical terms stay off it. User additions go in `data/profanity_extra.txt`; exceptions in `data/allowlist.txt`. The list is DATA, not code.
- Normalize before matching: lowercase, strip punctuation, collapse runs of repeated letters (also test the 2-letter collapse), expand obvious asterisk or symbol masking, handle common suffixes (`-s`, `-ing`, `-in'`, `-er`, `-ed`). Match on whole tokens only; no substring matching.
- Unit tests must use innocuous placeholder words in a test-only list. Do not put profanity in test files.
- Cross-check from lyrics: any lyric token on the list that has no matching ASR flag becomes a flag with `source="lyrics"`, `approx=True`, and a window estimated from word-level lyric times if available, otherwise interpolated between neighbouring aligned words or proportionally inside its lyric line. Flags found by both get `source="both"` and keep the aligned (lyric-clock) timing. Default `censor=True` for all flags; approximate ones are marked "verify" in the UI.

## Stem mode (skeleton ONLY, do not implement behaviour)

Four stems named Vocals, Drums, Bass, Melody (Demucs "other"). Create the screen, the routes (return HTTP 501 with `{"detail":"not implemented"}`), and `docs/STEMS_TODO.md` containing this checklist, and nothing else:

- Four per-stem controls changing volume during playback; 0-200 % per stem (100 % = unity)
- Per-stem mute and isolate buttons
- Keys 1-4 select a stem, arrow keys or scroll adjust its volume
- Waveform scrubber with draggable playhead
- Snippet mode: bracket handles, snap to whole seconds, gapless loop
- Export the full song or a snippet at the chosen volumes (WAV, source sample rate)
- Quality modes: Fast and Pro (Pro = 2 shifts, 0.50 overlap)
- Batch folder separation; open a pre-separated stems folder
- Independent stem download

## UI spec: flip-disc dot display

- The whole browser window is one dot grid on a `<canvas>`. Lit dots are amber, unlit dots are a dim blue-grey, as in a transit flip-disc or LED sign.
- Colours (CSS variables): `--on: #FFB800`, `--off: #1C2030`, `--bg: #05080D`. Dots are circles with diameter about 60 % of the pitch.
- Dense: default pitch 6 CSS px (clamp 4 to 12, override with `?pitch=`). Grid size = `floor(window / pitch)` in both axes; recompute on resize (ResizeObserver, debounced) and respect `devicePixelRatio`.
- **NO ANIMATION.** No transitions, no `requestAnimationFrame` loops, no blinking, no scrolling marquee, no easing. State changes redraw instantly. Progress bars simply update when an event arrives.
- Glyphs: a 5x7 bitmap font in `font5x7.js` covering A-Z, a-z, 0-9, and the punctuation/symbols `! ? ( ) < > _ = / + - . , ; : @ # $ % & x ÷` plus arrows. 1 dot gap between glyphs. Support integer text scales (1x to 4x).
- Build `web/font-test.html` that renders every glyph so the user can eyeball it.
- Dot-matrix is for titles, buttons, status, progress and stem labels. Dense interactive content (review table, transcript) uses real HTML elements styled amber-on-black with a monospace font, overlaid on the canvas.
- Buttons are dot-drawn rectangles with hit-testing in grid coordinates. Hover/press inverts lit and unlit instantly.

## Screens

1. **Welcome:** title, choose-file / drag-and-drop (hidden `<input type=file>` triggered by a dot button), supported-format hint.
2. **Mode:** CENSOR or STEMS.
3. **Processing:** stage list (decode, separate, transcribe, lyrics, detect) with a dot progress bar and status line.
4. **Review:** see below.
5. **Result:** stats (words censored, seconds muted), A/B playback of original vs clean (swap source while keeping position), download button.
6. **Stems:** skeleton only (labels, disabled controls, "coming soon").

### Review screen requirements

- Transcript view with flagged words highlighted; click any word to toggle censoring (so misses can be added).
- Table of flags: censor checkbox, word text, start/end with +/-10 ms nudge buttons, source badge (ASR / LYRICS / BOTH), "verify" marker for approximate ones.
- Edit a word's text (to fix a mishearing); this re-evaluates whether it is profane but never changes its timing.
- Per-flag preview buttons play a +/-1.5 s clip, original vs censored, rendered server-side for that region only.
- "Render" button confirms and continues.

## Server (FastAPI, bind 127.0.0.1)

`POST /api/upload`, `POST /api/jobs`, `GET /api/jobs/{id}` (poll), `GET /api/jobs/{id}/events` (SSE), `GET /api/jobs/{id}/review`, `POST /api/jobs/{id}/review`, `GET /api/jobs/{id}/clip?kind=original|censored&start=&end=`, `GET /api/jobs/{id}/output`. Stem routes return 501.

Job states: `queued, decoding, separating, transcribing, fetching_lyrics, detecting, awaiting_review, rendering, done, error`.

## Conventions

- Type hints everywhere; `logging`, never `print`; small functions; short docstrings.
- Friendly user-facing errors; full details go to `logs/`.
- Tests: pytest, synthetic audio generated with numpy. Required tests are listed in the kickoff prompt.
- End of every phase: tick `PLAN.md`, run tests and lint, `git commit -m "phase N: <summary>"`, then post a short report (what works, how to verify, known issues).
- Ask the user a question only when genuinely blocked.

## Out of scope for now

AWS or any remote compute, dereverb, four-stem / mixer RoFormer, implementing stem mixing, Electron packaging, accounts or auth, bleep tones, a terminal UI. Vocal Mel-Band-RoFormer for censor isolation is in scope (config swap).
