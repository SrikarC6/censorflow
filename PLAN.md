# CensorFlow plan

Living checklist. Update as work proceeds. See `AGENTS.md` for standing rules.

Note for anyone editing the web UI: `web/` is served with `Cache-Control: no-cache` only by a
server started at or after commit `e6aab12`. Restart the server and hard-reload the page after
pulling JS changes, or the browser will quietly run the previous build.

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
  - **the look: the board paints no dot field at all; dots are ink, and every label and button
    sits on a floating plate, so the display reads as physical signs. Wipes and idle flips
    removed from the page, flip sounds kept behind a SOUND toggle. Plates take a 1px hairline
    border like the HTML chips, green/red semantic borders with the lettering in the same
    colour, and a hover inverts the plate while knocking the label out of it. The banner
    scrolls the whole caption continuously with a wide gap between repeats.** Specimen tiles
    keep their unlit field, because a glyph is only legible against the full matrix.
    **Approved by the user.**
- [x] 4b: Welcome, Mode, Processing, Result
  - `web/api.js` (the server as functions), `web/ui.js` (screen registry, `state`, sign/meter/
    buttonRow/notice helpers), `web/index.html`, `web/app.js`, `tests/test_web_app.py`
  - `GET /api/health` so the welcome screen can say *why* this install cannot work; static files
    served `no-cache` so an edited ES module is not replayed from Chrome's cache
  - verified in headless Chrome against the real server: Welcome, Processing (real Demucs +
    Parakeet subprocesses over SSE) and Awaiting; Result by injecting render stats, since only
    the 4c review POST produces them
  - Result is reached by 4c's review POST, and `tests/test_web_app.py` no longer carries any
    pending-screen exemptions
  - fixed a real race found while writing the tests: `create` enqueues the job, so the worker
    thread and any inline `run()` executed it twice over one directory. `JobStore.run` now claims
    each job once
- [x] 4c: Review screen
  - `web/review.js` owns the transcript, the flag table and the Render button; `app.js` registers
    it and hands it the status line and the way out. The panel is sized in whole dots between the
    last sign and the buttons so it can never cover either
  - every word in the transcript is a button, so a miss is one click; a flagged word switches
    censoring instead of duplicating
  - rows carry a censor checkbox, an editable word, ±10 ms nudges on both edges (clamped so a
    window cannot invert), a source badge, a VERIFY marker for estimated timing, and both
    previews
  - the verdict column says `?` after an edit rather than guessing: judging profanity in the
    browser would mean shipping the word list and reimplementing detection
  - `rendering` is its own screen because the POST blocks for as long as the render takes
  - verified in headless Chrome against the real server: 239 words, 5 flags (2 ASR, 3 LYRICS with
    VERIFY), word toggling adds and removes flags, nudges move the edge, Render wrote a 9 MB FLAC
    and the job went to `done`
- [x] 4c fix: dead buttons on a short window
  - the user reported buttons that could not be clicked. Two causes: their browser was replaying a
    cached `app.js` from before `no-cache` was added (a stale string from an earlier screen gave
    it away), and a real layout bug that only shows on a window around 1000x420
  - every button row is now clamped above the status notice, centred from the handles' real widths
    instead of a guessed half-label, and `helpers.tight()` drops whole rows rather than stacking
    two rows in one space - stacked rows overlap and only the top one is ever hit
  - a row too wide for the window now says *this window is too narrow - make it wider* instead of
    presenting controls that cannot work
- [ ] 4d: Stems skeleton + `docs/STEMS_TODO.md`
  - the UI-element cleanup the user asked for after 4c ("fix up the UI elements") lands here or
    just before it

## Phase 5 - hardening and docs

- [ ] Friendly errors (ffmpeg missing, unreadable, no vocals, model download, disk full)
- [ ] First-run model download progress in the UI
- [ ] `README.md` (install, run, dev flags, layout, troubleshooting)
- [ ] Clean clone: `uv sync && uv run censorflow serve`
- [ ] Re-read `AGENTS.md`, confirm every non-negotiable rule is met and tested
- [ ] A JavaScript test harness (a DOM stub driven by `node`) so `flipdisc.js` and the screens are
      executed, not only asserted on as text - two dead-button bugs got through static checks
- [ ] A timeout on the worker subprocesses in `compute/local.py`
- [ ] Break up the oversized files: `flipdisc.js` (~700 lines), `review.js` (~430), `app.js` (401),
      `font5x7.js` (~435). `AGENTS.md` asks for roughly 300
- [ ] Offer Fast/Pro quality on the Mode screen instead of hardcoding `quality: 'fast'`
- [ ] Persist `JobStore` state, or say plainly in the UI that a server restart loses in-flight jobs

## Cosmetic loose ends

- [ ] Serif `7` has a foot serif on the wrong side
- [ ] A hovered plate becomes a solid block of colour (the label is still dots, but it is not a
      sign any more) - may yet be rejected
- [ ] The HTML transport is Chrome's default audio widget recoloured by a CSS filter

## Note for the coming Cursor / cloud phase

The user plans to move this project into Cursor soon so that **AWS cloud deployment and the public
website** are built there. Not started here, deliberately: `AGENTS.md` keeps AWS out of scope for
now. Two consequences to respect while the local work continues:

- Leave `ComputeBackend` (`compute/base.py`) and `compute/remote.py`'s documented contract intact.
  They are the seam the remote worker plugs into, so nothing local should be allowed to leak the
  LocalBackend's assumptions into the interface.
- Re-read `AGENTS.md`'s "Local first" and "Out of scope" sections when that work starts rather
  than trusting this note; the rules will likely need updating first.
