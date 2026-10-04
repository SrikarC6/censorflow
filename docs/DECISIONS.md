# CensorFlow: decisions

One line per decision: what, why, and where the information came from.
Sources are either a verified local API (`python -c "help(...)"`, `--help`) or a URL.

## Dependencies

- `numpy`, `scipy`, `soundfile` - decoding, FLAC/WAV IO, short-time RMS.
- `mutagen` - tag reading (`©nam`/`\xa9nam`, `©ART`, `©alb`); `a.tags` on MP4/M4A.
- `fastapi`, `uvicorn[standard]`, `python-multipart` - local server, SSE, file upload.
- `httpx` - LRCLIB lookups and the scripted-client test.
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

## New modules not in `AGENTS.md`'s tree

- `src/censorflow/models.py` holds the shared dataclasses (`Word`, `Flag`, `TrackInfo`,
  `LyricLine`) **and** `ProgressFn = Callable[[float, str], None]`.
  Reason: `separation/`, `asr/` and `compute/` all need to name the progress-callback type
  in their signatures. Putting it in `compute/base.py` would make them depend on the backend
  layer, and putting it in each module would duplicate it.
- `src/censorflow/pipeline.py` holds the headless orchestration (`run_censor`, `render_reviewed`).
  Reason: `cli.py` needs the same sequence that the server's job runner will need in Phase 3.
  Keeping it in one module means the CLI and the web app cannot drift apart. It imports
  `compute/base.py` only, so the `ComputeBackend` seam still holds.

## Dependency changes (Phase 1)

- `better-profanity` 0.7.0 used **once, at authoring time**, to seed `data/profanity.txt`
  from its `CENSOR_WORDSET` (916 entries). It is a dev-time source of DATA, not a runtime
  dependency, so it is **not** in `pyproject.toml`. The list is now hand-maintained text.
  Source: https://github.com/odino7/better-profanity
- Dropped `requests` as a direct dependency; `httpx` is already required by FastAPI and the
  tests, and Phase 2's lyrics lookup uses `httpx`. (`requests` remains in the venv
  transitively via `mlx-audio-separator` and `librosa`->`pooch`.)
- No `syncedlyrics` dependency. Decision: **LRCLIB only** (5/5 of the supplied songs matched
  on the first try, it is free with no key and no rate limit). `syncedlyrics` is kept as an
  optional `uv run --with syncedlyrics` overlay for the rare LRCLIB miss; adding it as a hard
  dependency would mean living with Musixmatch's undocumented desktop endpoint and its
  anonymous token handshake, which is brittle and rate-limit prone.
  Source: https://github.com/9DS8/syncedlyrics (README: Genius is plain text only; Deezer
  and Lyricsify marked broken; Musixmatch word sync only via `enhanced=True`)
- `pyyaml` used to parse LRCLIB `lyricsfile` - already a transitive dependency of
  `mlx-audio-separator`, so no new install.
- The separator's converted weights cache needs `mlx-audio-separator[convert]`
  (`torch>=2.6, onnx>=1.15, demucs>=4.0`) to *rebuild* the one-time
  `models/mlx-audio-separator/demucs/htdemucs_ft.safetensors`. It was installed as a
  throwaway overlay (`uv run --with "mlx-audio-separator[convert]"`) and is deliberately not
  a project dependency; ~1 GB of torch would be absurd for a local-only app.

## Model locations

- ASR weights moved from `~/.cache/huggingface` to **`<project>/models/parakeet-tdt-0.6b-v3`**
  (user request: "everything is within one directory... easier to package later").
  Env override `CENSORFLOW_MODEL_DIR`. `models/` is gitignored.
- The separator library's caches are env-overridable
  (`AUDIO_SEPARATOR_MODEL_DIR`, `MLX_AUDIO_SEPARATOR_DEMUCS_CACHE_DIR`) and are pointed at
  `<project>/models/mlx-audio-separator/{models,demucs}`. They are set with
  `os.environ.setdefault` **before** the library is imported, which is the only point at
  which they take effect.
- Job dirs, lyrics cache and logs deliberately stay under `~/.censorflow/` (per-user runtime
  state; writing inside an application bundle directory is wrong once the app is packaged).

## Separation quality

- `config.SEPARATION_QUALITY` presets: `fast` = 0 shifts / 0.25 overlap, `pro` = 2 shifts /
  0.50 overlap. Measured: separation is ~1.3x realtime and is the pipeline's bottleneck
  (30.5 s of a 120 s song, vs 7 s for ASR), so this is the knob that matters for iteration.
  Passed to the separator as a **complete** `demucs_params` dict, because
  `mlx-audio-separator` only fills in its defaults when `demucs_params` is `None`; a partial
  dict leaves the rest unset.

## Rendering

- Instrumental is derived as `mix - vocals`, **not** as `drums + bass + other`.
  Reason: measured on a real clip, the four Demucs stems sum to the mix with RMS error 0.030
  and a peak sample error of 0.88, so a 3-stem sum is not faithful enough to be the
  reference "instrumental".
- The render only ever needs the `vocals` stem: `final = mix - vocals * mask`. The
  instrumental stem is written anyway (cheap) for the "are there vocals at all?" check and
  for future stem mode.
- `clamp_to_full_scale()` clips to +/-1.0 before writing integer PCM.
  Reason: a decoded AAC mix genuinely exceeds full scale (measured peak **1.089**, 0.055 % of
  samples) and libsndfile silently **hard-clamps** when writing FLAC/WAV/MP3. Without an
  explicit clip the exported file differs from the mix outside every censor window by up to
  5.1e-2, which would violate rule 1. The count is reported as `RenderStats.clipped_samples`
  so the CLI can say so out loud rather than hide it.

## Lyrics lookup (Phase 2)

- `album_name` is deliberately **not** sent to LRCLIB `/api/get`.
  Reason: measured, the local album tags are frequently wrong (`06 M3tamorphosis.m4a` says
  "Whole Lotta Red", `03 Ni__as In Paris.m4a` says "Watch The Throne (Deluxe)"), and LRCLIB
  404s when the album does not match. Sending `artist_name` + `track_name` + `duration`
  matched **5 of 5** supplied songs on the first attempt. Withholding a field that is
  often wrong beats trusting it.
  Source: https://lrclib.net/docs
- **Duration is the primary match filter.** LRCLIB has multiple records with the same
  title/artist (live, remix, sped-up), and `duration` is the cheapest reliable discriminator.
  A 404 caused by a duration mismatch is retried **once without `duration`** rather than
  treated as a failure, because a ±2 s tolerance can miss by a second.
- Artist credits are split and tried in order (`primary_artist` first), because every supplied
  song has a multi-artist tag and LRCLIB expects one artist.
  Matching is accent-insensitive and punctuation-insensitive: LRCLIB returns `JAŸ-Z` where
  the file says `JAY-Z`.
- `/api/search` returns at most 20 unpaginated full records, so it is only used as a fallback
  and scored with `config.LYRICS_SEARCH_{TITLE,ARTIST}_PENALTY_S` plus duration drift;
  anything beyond `LYRICS_DURATION_TOLERANCE_S` is rejected outright.
- **Lyrics are deliberately not part of the `ComputeBackend` seam.**
  Reason: `AGENTS.md` defines the seam as exactly `separate()` and `transcribe()` and says a
  future remote worker runs "the same two stages". Adding a lyrics method would change that
  contract. The lookup stays an inline, local `httpx` call in `pipeline.py`, so a remote
  backend still only offloads the two ML stages. `workers/fetch_lyrics.py` exists purely as a
  standalone debugging entry point.
- Raw responses are cached at `config.LYRICS_CACHE_DIR/<24hex>.json` (sha256 of
  version + endpoint + artist + title), which is gitignored. The cache makes re-runs instant
  and keeps the app usable offline after the first fetch.
- A lookup failure **never fails a job**: `lyrics.fetch()` catches `httpx.HTTPError`, 404s,
  non-200 and non-JSON bodies, and returns no record; `lyrics.lookup()` never raises.

## Lyrics timing (Phase 2)

- **`lyricsfile` YAML is parsed, not LRC**, because it carries `start_ms` **and** `end_ms`
  per line, which makes the proportional in-line estimate much tighter. Verified against real
  records: 85 / 132 / 104 / 95 / 60 timed lines across the five supplied songs.
- **`metadata.start_ms` is not used.** Real `lyricsfile` metadata only contains
  `duration_ms`; the code that applied an offset from it was removed rather than left in
  with a guessed sign.
- LRC `[offset:...]` is logged and ignored. The sign convention differs between players and
  could not be verified from a primary source, and a wrong global shift would misplace every
  window. No real LRCLIB record returned an `[offset:]` tag either.
- **Untimed plain lyrics are ignored**, on purpose. A window placed with no timing information
  at all would silence an arbitrary part of the song; missing a word is recoverable in the
  review screen, silencing the wrong 2 seconds is not.
- Word-level timing is accepted in **both** shapes (`[start_ms, end_ms]` pairs and
  `{start_ms, end_ms}` mappings) because no format is specified. In practice
  `hasWordSync` is **false for every real track tested**, so this path is currently dead code
  kept for the day LRCLIB's community word-sync records become common.
- When a line has no word timing, a flagged word's span is estimated **proportionally to word
  length** (`max(len(token), 2)`), clamped to `LYRICS_MIN_WORD_S`/`LYRICS_MAX_WORD_S`.
  Reason: even division systematically under-covers long words and over-covers short ones
  like "a", and an estimate is all that is available here. Those flags are marked
  `approx=True` and shown as "verify" in the UI.

## Metadata (Phase 2)

- `metadata._read_tags` uses a **hand-written key map** (`©art`/`artist`/`tpe1`,
  `©nam`/`title`/`tit2`, `©alb`/`album`/`talb`) instead of `mutagen.File(path, easy=True)`.
  Reason: verified, `easy=True` raises `TypeError: ID3.load() got an unexpected keyword
  argument 'easy'` on ID3-backed formats (WAV, AIFF), and MP4 still returns **lists** even
  with `easy=True`. The hand-rolled reader unwraps ID3 frames' `.text` and joins lists.
  Source: `inspect.signature` + live test on 1.48.1
- Filenames are **not** parsed with `Path.stem`. Verified: `Path("3. Carti.m4a").stem` is
  `"3"`, because pathlib treats `". Carti"` as the suffix. The audio extension is stripped
  from an explicit extension list instead, then track-number prefixes and decorations
  (`Parens`Remastered` etc.) are removed.
- `title_from_filename` returns `None` when nothing but digits remains (`"01.mp3"`), so a
  bare track number is never sent to LRCLIB as a title.
- `primary_artist` splits on `feat.`, `ft.`, `featuring`, `with`, `vs.`, `,`, `;`, `/`, `&`
  and `x`, taking the first credit. Known and accepted limitation: it also splits a genuine
  artist name containing `&` (for example `Simon & Garfunkel`).

## Jobs, review and the server (Phase 3)

- `src/censorflow/review.py` and `src/censorflow/preview.py` are new modules not in `AGENTS.md`'s
  tree. Reason: review editing and region preview are substantial enough to deserve their own files
  and their own tests, and `server.py` would otherwise be unreadable.
- `JobError` lives in `review.py`, not `jobs.py`. Reason: the validation that raises it is the
  review payload's; keeping them together avoids a circular import and means the server has one
  obvious place to catch a bad payload.
- The `censor` switch is honoured **exactly as the user sent it**, while `profane` is recomputed
  server-side from the edited text. Reason: the user's decision is the authority (that is the whole
  point of the review screen); the recomputed `profane` key exists only so the UI can re-highlight
  a word after it was retyped, and it never changes the outcome of the render.
- Lyrics lookup is deliberately **not** in the `ComputeBackend` protocol. `AGENTS.md` defines the
  seam as exactly `separate()` and `transcribe()`, and describes the future remote worker as
  running "the same two stages". Adding lyrics to the seam would mean a GPU worker owes us a
  third method we never specified. `workers/fetch_lyrics.py` exists as a manual entry point only.
- `run_censor` takes an `on_stage(stage_name)` callback in addition to `on_progress(pct, msg)`.
  Reason: the job state machine has ten named states and a percentage cannot be mapped onto them
  honestly (separation reports 2/5/10/90/100). The UI shows the stage list; the percentage is
  only for the bar.
- `JobStore` runs **one job at a time** from a single daemon thread. Reason: the machine is a
  fanless laptop and `AGENTS.md` says run one heavy stage at a time, never two models at once.
- `JobStore` takes an optional `backend_factory` so tests inject a fake and never spawn ML.
- Uploads are written to `uploads/<random>/<original filename>`. Reason: an upload of an untagged
  file has no title, and the filename is the only fallback before LRCLIB is asked. Saving every
  upload as `original.<ext>` made the title literally the string "original", which was then sent
  to LRCLIB as the track name.
- SSE sends an immediate `snapshot` event on connect, a `: keepalive` comment every
  `SSE_KEEPALIVE_S` seconds, and unsubscribes in a `finally`. A client that attaches to an
  already-`done` job gets the snapshot and the stream closes immediately, instead of being held
  open on keepalives until the browser gives up.
- `has_audio_stream` swallows `AudioError` from `probe()`. Reason: the question it answers is
  "is there audio here?", and an unreadable or non-audio file is a legitimate "no", not a crash.
- `AUDIO_EXTENSIONS` moved from `metadata.py` to `config.py`. Reason: the server needs it for the
  upload refusal and the CLI needs it for `--format` validation; `config.py` is the agreed home
  for constants.

## Full-scale clipping, measured on a real track

A 45 s AAC excerpt of a real song decodes with a **peak of 1.558** and **2631 of 3966976 samples
(0.066 %)** above full scale. Verified that this is the source, not our decode: the same peak
appears with and without the resampler. FLAC, WAV and MP3 are all integer PCM and cannot store a
sample above 1.0, so those samples are clipped on export and the output necessarily differs from
the decoded mix **outside every censor window** at exactly those samples.

Decision: keep the explicit `np.clip` in `clamp_to_full_scale()`, report the count as
`RenderStats.clipped_samples` (surfaced in the CLI warning and in the server's `render` payload),
and never normalise the mix. Reason: normalising would alter the whole track to fix 0.066 % of
samples, which is a far bigger deviation than the clamp it replaces.
`tests/test_censor_render.py::test_export_of_an_over_full_scale_mix_stays_close_to_the_mix` pins
this behaviour and asserts the clamp actually ran, so the test cannot pass vacuously.

## Web UI: flip-disc display

- The dot field is drawn on **one canvas covering the browser window**, not as a CSS
  `radial-gradient` behind scrolling content windows like the prototype did.
  Reason: `AGENTS.md` puts the grid on the canvas, and a fixed CSS board behind
  scrolling cards needs scroll-origin tracking to stay aligned. One canvas removes
  that whole class of bug. Both lit and unlit dots are painted there.
- Colours stay in `web/style.css` as CSS variables and `flipdisc.js` reads them with
  `getComputedStyle` at startup, so the stylesheet remains the single source of truth
  and the canvas cannot drift out of sync with the HTML overlay.
- Palette: `AGENTS.md`'s `--on: #FFB800` / `--off: #1C2030` / `--bg: #05080D`, plus the
  prototype's 42 % specular highlight on lit dots (`--on-hi`), which is what makes a dot
  read as a physical flap rather than a flat pixel.
- `DISC_FILL = 0.72` and default pitch 6 (clamped 4-12, `?pitch=` override), per the user's
  choice: the prototype's fill reads much better than `AGENTS.md`'s 60 %, and pitch 6 is
  denser, which suits a processing UI that carries more text than a portfolio page.
- The font is **uppercase-only**, ported from the prototype: transit and LED signage never
  sets lowercase and 5x7 lowercase is unreadable. `glyphFor` tries the literal character
  first and then its uppercase form, so the single deliberate lowercase key (`x`, meaning
  multiply) stays reachable without letting `a`-`z` become their own glyphs.
  Source: the prototype's `lib/flip-font.ts`, extended with `< > _ = ; @ $ ÷` and the four
  arrows, all of which `AGENTS.md` requires and the prototype lacked.
- No animation, per `AGENTS.md`. `tests/test_web_font.py` asserts `flipdisc.js` contains
  neither `requestAnimationFrame` nor `setInterval`, so this cannot creep back in by
  accident. The user may revisit this after seeing what the interface feels like without it.
- The animation seam is explicit: `put` mutates a cell, `paint` draws it, and `set` is both.
  Adding a scheduler later means sitting between `put` and `paint`; no caller changes.
- A fourth cell state `DIM` was added because a disabled button drawn `OFF`-on-`OFF` is
  invisible and reads as a rendering bug. `--on-dim` makes it look present but inert.
- `web/style.css` is a new file: `AGENTS.md`'s file list has no stylesheet, and one is
  unavoidable. It also carries the amber-on-black monospace styling for the HTML overlay
  that the review screen will need.

## Web UI: revisions after the first look

Seven changes were requested on `font-test.html` only, so the look could be judged before
any screen was built. Decisions that outlive the test page:

- **Two font sets in one file.** `web/font5x7.js` now carries `SERIF_GLYPHS` (7 cols x 9 rows,
  the default) and `SANS_GLYPHS` (5 cols x 7 rows, the original set, kept for small print).
  `setFont(name)` / `getFont(font)` switch between them and every API takes an optional
  trailing `font` argument. Reason: a serif does not fit 5x7, and `AGENTS.md` names the file
  `font5x7.js` so the name stayed. `tests/test_web_font.py` parses **both** tables and checks
  each against its own metrics (serif 9 rows of 7 bits, sans 7 rows of 5 bits).
- **Serif house style**, documented at the top of the table: a stem sits at column 1 or 5 and
  flares to three dots at row 0 and row 8; crossbars of A, E, F, H, P and T sit on row 4; round
  letters open their corners into four-dot shoulders so they do not read as the sans scaled up.
  `glyphBitmap`'s cache key carries the set name **and** the raw character, because the sets
  have different widths and `x` must never share an entry with `X`.
- **Denser, smaller dots.** `DISC_FILL` 0.72 -> 0.55 and `DEFAULT_PITCH` 6 -> 4 (`MIN_PITCH` 3).
  Reason: at 0.72 the gaps close and a grid reads as squares rather than dots, which was the
  first thing the eyeball check caught. Denser dots are also what pay for the taller glyph
  cell - a 7x9 serif at pitch 4 is the same physical size as a 5x7 at pitch 6, but far more
  detailed.
- **Exactly one dot layer.** `renderField(..., paintField = false)` draws only lit dots and no
  background, so a glyph tile sits on the board's single field instead of painting a second,
  differently-phased one on top of it. This only works because every CSS box in the page is a
  whole number of dots tall and wide (padding, heading heights, a second identically-sized
  caption row); `.fonttest` sets `--pad` from the board pitch in JS. Anything that is not a
  whole number of dots reintroduces the moire.
- **Floating plates** use `outline`, not `border`, for their 1px frame. Reason: an outline takes
  no part in layout, so the dots inside the plate still land on the global grid; a border would
  push them all off by one dot.
- **A protection mask** (`board.isProtected(col, row)`) is set by `stampText`, `button` and
  `progress`, and cleared by `redraw`. The test page's idle flips use it so a random disc can
  never flicker a word.
- **Animation lives in `web/flip-motion.js` and sound in `web/flip-sound.js`**, ported from the
  prototype, and deliberately *not* in `flipdisc.js`. `flipdisc.js` stays free of
  `requestAnimationFrame` and `setInterval`, which a test asserts; a screen that wants the
  reveal opts in by importing the module. The full wipe (diagonal wave, hold, scatter dissolve,
  then `redraw()`) and the occasional idle flip both respect `prefers-reduced-motion`.
- **Body copy stays monospace** while the dot matrix is serif. Reason: the dense HTML overlay
  (transcript, flag table) has to be selectable and its timestamp columns have to line up;
  a dot-matrix serif cannot do either.

## Web UI: sans restored, buttons fixed

- **Sans is the default again.** The 7x9 serif set was tried because a serif does not fit
  5x7, and it looked handsome at title size - but at reading size its `A` and `W` were hard to
  make out, so it went back to being opt-in behind the `FONT: SERIF` button. It is still in the
  file rather than deleted, because at scale 3-4 it is genuinely handsome for a title; say the
  word and it goes. The sans set gained exactly one change: `W`'s apex now reaches row 2, which
  stops it flattening toward `U` and makes it the vertical mirror of `M`. Nothing else in the
  classic 5x7 face was touched - it is already near-optimal and inventing more changes would
  only make it worse.
- **`glyphFor`'s fallback must come from the active set.** It was `const QUESTION = SERIF_GLYPHS['?']`,
  so with sans active every unmapped character would have stamped a 7x9 glyph into a 5x7 cell.
  It is now `const QUESTION = '?'` and the lookup ends `glyphs[QUESTION]`, which resolves per
  set. A test asserts this, because the bug is invisible until something unmapped is drawn.
- **`.fonttest` must not capture pointer events.** The page is one fixed full-viewport sheet over
  the canvas, and it reserves its top padding as exactly the band the dot-drawn buttons live in.
  Without `pointer-events: none` on the sheet it swallowed every click and the buttons silently
  did nothing. `.fonttest > *` opts back in so the prose stays selectable.
- **`board.handles()` and `board.cellAt(x, y)`** were added. The rects are needed because a
  screen will drive a button from somewhere other than a click on it (the review screen flips a
  checkbox when a word is censored), and `cellAt` lets a press be resolved without synthesising
  a pointer event.
- **There is still no JavaScript test harness.** Two button bugs got through because nothing
  executed `flipdisc.js`; both are now pinned by static assertions in `tests/test_web_font.py`,
  which is a weak substitute. A DOM stub plus Node is Phase 5 work, and it should happen before
  4b adds four screens of interaction.
- **The board paints no background field.** `paint()`'s `OFF` branch used to fill a cell with
  the background *and* draw an unlit disc, which meant the whole window was a grid of dots from
  edge to edge. Measured against the `font-test.html` screenshots, that field is noise: the eye
  reads the texture and not the words on it. It is gone, and the dots are now **ink only** -
  drawn where something is actually written. `DIM` still draws a disc, because that is the ink
  of a disabled label rather than a backdrop.
- **`plate()` is the only container.** With no field, an unlit region is already the background
  colour, so a sign is exactly `fill` plus a one-dot frame. That is `plate({ body, frame })`, and
  both `button` and `progress` were reduced to calling it instead of hand-rolling the same
  fill/stroke/guard loop. A plate is the design's single container: titles, samples, the review
  transcript and every button are plates, which is what makes them read as physical signs.
  `body` exists because a hovered button inverts its *interior* to `ON` and knocks the label out
  to `INV` - hardcoding the interior to `OFF` (the first attempt) made the hovered button vanish
  into a dark-on-dark rectangle.
- **The progress bar now lives inside its frame**, which retires a question left open since 4a.
  The track used to be bare cells lying on a lit field, so an unfilled bar was indistinguishable
  from the background; there was no honest answer while the field existed. It is now a caption on
  a sign with the bar one row above the bottom frame and a row of air between them, so filled and
  unfilled are both plainly visible.
- **No wipes, no idle flips, no flip sound.** All three existed to animate the field, and the
  field is gone - with nothing but signs on a bare board there is not enough to wipe, and a
  random flip would land on a sign. The `ANIMATE`, `WIPE` and `SOUND` buttons are off the demo
  page and `font-test.html` no longer imports `flip-motion.js` or `flip-sound.js`.
  **`flip-motion.js` and `flip-sound.js` are still on disk, imported by nothing.** They are a
  design asset for the processing screen (a wipe has real material to work with once a stage
  list is on the board), and deleting 350 lines of reviewed port would be the more expensive
  mistake. Decide before 4b whether they are used or cut.
- **A lit cell is a disc, never a square.** Regression: `paint()` had been reduced to
  `fillStyle = colours.on; fillRect(...)` with no `drawDisc`, so every lit cell was an amber
  square and `renderField` had the same bug. The dots are the design - a square grid of
  coloured blocks is not a flip-disc display. Both now erase to the background and draw a
  round flap, and `tests/test_web_font.py` pins it.
- **The plate is a remembered box with a hairline border, not a row of dots.** `PLATE_LINE = 1`
  CSS px: `drawPanelEdges` fills the four outer edges of the plate, so the border is a drawn
  line at the resolution of the display, exactly like the HTML `.chip`'s `1px solid`. The plate
  is remembered in a `panels` array rather than baked into the cell buffer, which is what lets
  the marquee re-plate 22 times a second (`key` replaces a record instead of appending) and
  what makes a hover a single `redraw()` pass instead of a partial repaint.
- **Semantic tones carry their colour into the lettering.** `tone: 'go' | 'stop'` sets the
  hairline; `plate({ ink })` sets the colour of the dots inside it, so a green frame holds
  green dots instead of a green frame around amber dots - one object instead of two bolted
  together. `renderField` takes the same `ink` so an HTML chip and a canvas button agree. The
  specular highlight is skipped on a tinted disc: it belongs to the amber flaps and on a green
  dot it reads as a stray light speck. While a toned plate is lit, `ink` is dropped and the
  label is knocked out instead, so the inversion still reads.
- **A disabled sign keeps dim lettering.** `OFF` is toned `stop` but `setEnabled(false)`, so its
  dots stay `DIM` rather than turning red: a disabled control must not look armed.
- **A sound toggle must never be disabled.** Regression: `soundBtn.setEnabled(isSoundEnabled())`
  meant the one control needed to turn sound *on* was not clickable, because a disabled handle
  is skipped by `buttonAt`. It now only changes tone.
- **Prose boxes may grow; tiles may not.** `.note` is `min-height` only. A fixed `height` plus
  `overflow: hidden` silently ate the end of every long paragraph and the board's own dot text
  printed through the gap.
- **The banner is the one deliberate exception to the no-animation rule.** It scrolls the whole
  caption continuously, one column per `setTimeout`, treating the strip as **periodic**: each
  cell is offered at two positions one repeat apart, so the wrap has no seam and nothing
  resets. `prefers-reduced-motion` draws a single static frame. `gap` (14 dots) separates one
  repeat from the next, because the two are the same sentence and without air between them they
  read as one run-on word.

### Phase 4b: the screens

- **`state` lives in `ui.js`, not `app.js`.** `review.js` arrives in 4c and needs the same job,
  the same upload and the same transport element. Two copies of "which job am I on" is how a
  review screen ends up previewing the wrong song, so the one object every screen reads is
  exported from the module that owns the board.
- **Static files are served `Cache-Control: no-cache` (`_WebFiles`).** Chrome caches ES modules
  by URL, so an edit to `app.js` was replayed from disk and looked exactly like broken code.
  Diagnosing that cost more time than the header costs.
- **A button must be created once and *placed* again on every paint.** Creating a handle inside
  a painter appends one to the hit-test list on every redraw. `board.button` now carries a
  `shown` flag that only `place()` sets, and `redraw()` draws the shown handles only - otherwise
  Welcome's CHOOSE A SONG stayed on screen behind the Result screen. `handles()` returns a
  read-only snapshot for inspection; `allButtons()` returns the live handles, because calling
  `hide()` on a snapshot is a `TypeError` that only shows up when a screen changes.
- **`fitText`, not `pickScale`.** `pickScale` answers "what is the largest scale at which this
  wraps" and returns a scale *and* the wrapped lines. Stamping the original string at that scale
  is how a subtitle ends up running off both edges, and it cannot express a line budget at all,
  so a subtitle that needed three rows pushed the button under it. `ui.js` has its own
  `fitText(text, maxCols, maxLines)` over `SCALES = [4, 3, 2, 1]`, and every screen declares its
  own height in `BLOCK` for `h.top(tall)` to centre it.
- **The status line is cut to the window, with the ellipsis counted first.** `fitLine` measures
  `label + "..."` rather than `label`, because appending the ellipsis after the fit grows the
  label past the width it was just measured against and the sign then clips its own last glyphs
  instead of saying less. The sign also sits two dots clear of the bottom edge.
- **`plate` takes a tone twice: `tone` paints the hairline, `ink` the dots.** `sign()`,
  `notice()` and `progress()` pass both. Passing only `tone` gave a red border around amber
  letters, which reads as two opinions rather than one warning.
- **`GET /api/health` carries the reason, and the welcome screen shows it.** ffmpeg is a hard
  requirement and the speech model is a 2.3 GB download; both are cheaper to find before a user
  picks a song than three stages into a job. `checkInstall()` runs on load, and a server that
  will not answer is not a red sign - the page still works if it comes back.
- **A finished job is not resumed from `?job=`.** The render figures only exist in the review
  response, so `resume()` sends a done or errored job back to Welcome with an explanation.
- **The A/B transport is real HTML on the overlay.** A scrub bar and a volume control are dense
  widgets; drawing them as dots would be worse, not better. One `<audio>` element swaps `src`
  between the browser's own object URL (the original, which the server never has to serve back)
  and the output URL, restoring `currentTime` on `loadedmetadata` - swapping elements would lose
  both the position and the play state. It is recoloured with a CSS filter rather than a custom
  control, which is a shortcut worth revisiting.
- **`tests/test_web_app.py` reads the JS as text** - there is still no JS runner. It pins the
  wiring rather than the behaviour: every path `api.js` asks for is a route the app serves, every
  stage the Processing screen lists is a state the pipeline announces, every registered screen
  is reachable, every button handle is declared once and placed by a painter, and every name
  `app.js` imports is something one of the modules exports. Each of those is a mismatch that
  would otherwise surface only as a dead click.
- **A job runs exactly once, and the claim is "has run" not "is finished".** `create` enqueues the
  job, so the worker thread will pick it up; a caller that gets there first - a test driving a
  job by hand - takes a store-wide `_run_lock` and records the id in `_ran` *before* the work.
  Two pipelines over one job directory is how a test asserts on a half-written `words.json`, and
  this was the cause of two separate one-off flakes in `tests/test_server.py` that could never be
  reproduced on demand. Keying the claim on `State.finished` would not have worked: the pipeline
  stops at `awaiting_review`, which is not finished but must never be analysed again. Recording
  it before the work means a crashed job is not silently retried. The lock is store-wide because
  this is a fanless laptop and one job at a time is the point; it is held for the whole run so a
  second caller waits for the first rather than being told to go away, and it is not reentrant.

## Phase 4c: the review screen

- **`web/review.js` is its own module, not more of app.js.** `app.js` was already over the ~300-line
  guidance and the review screen is the one screen that is *not* dot-drawn, so folding dense HTML
  into the flow module would have made both harder to read. It receives the two things it cannot
  own - `say` and `startUpload` - and imports `state` from `ui.js`, which is what `state` is there
  for: two copies of "which song is this" is how a preview ends up playing the wrong clip.
- **The review screen is the one screen with a panel of dense HTML, and its edges are measured in
  whole dots.** `.review` is `position: fixed` with `top` and `bottom` set from
  `panel.style.top = (row + 4) * pitch` and the row the buttons are placed at. The HTML is
  therefore always exactly the gap between the last sign and the button row, whatever the window
  size, and cannot cover either. `NOTICE_ROWS` became an export from `ui.js` for the same reason:
  review.js has to place its buttons clear of the status line without a second copy of that number.
- **The panel is built once in `enter` and rebuilt in `refresh`, never in `paint`.** A painter runs
  on every redraw - including every button hover - so building the table there would throw away the
  scroll position and every checkbox's focus each time the pointer moved. `refresh` saves and
  restores `scrollTop` so the row being worked on stays in view.
- **Clicking any word in the transcript toggles its censoring; an unflagged word gains a flag.**
  That is the only way a miss the model did not hear can be censored, and it is the reason the
  transcript is there rather than a summary. A word that already has a flag switches rather than
  duplicating, which is why `toggleWord` branches on the flag it was handed.
- **A word's text is edited with `change`, not `input`.** The server judges profanity from the
  committed text, and rebuilding the table on every keystroke would eat the caret mid-word.
  Editing never moves `start` or `end` - a mishearing is a mishearing, not a different moment.
- **The verdict column says `?` after an edit rather than guessing.** Deciding profanity in the
  browser would mean shipping `data/profanity.txt` and reimplementing `detect.is_profane` in
  JavaScript, with two word lists that could disagree. Until the next round trip reports back, the
  honest answer is that the client does not know.
- **A nudge cannot invert a window.** `end` is pushed to `start + NUDGE_S` if a nudge would cross
  it, because the server rejects `end <= start` and the user would get a 400 from pressing a button
  that looked harmless.
- **`rendering` is a screen of its own.** `POST /review` applies the edits *and* renders before it
  answers, so on a laptop that is several seconds with nothing to poll. The screen goes up before
  the request and Result only after it, and a failure puts the user back on the review screen with
  the edited flags intact - which is why `submit` never resets `flags`.
- **`resume()` sends an `awaiting_review` job to the review screen, not the stage list.** The
  analysis is over; there are no stages left to show, and the whole point of `?job=` is that a
  refresh does not throw away work.

## Phase 4c fix: buttons that could not be clicked

The user reported buttons doing nothing. Two separate causes, and both were real.

- **A stale browser build.** They quoted a status line that had been deleted a commit earlier, so
  their browser was running the `app.js` from before `Cache-Control: no-cache` was added. Worth
  remembering: for a few commits the served JS was cached by Chrome, so an edited module silently
  did not take effect. `PLAN.md` now says so at the top.
- **The layout really did break on a short window.** `probe_buttons.mjs` (a new CDP script that
  walks every shown handle on every screen and reports its row span, whether it overlaps the status
  notice, whether it hangs off the right edge, and what `document.elementFromPoint` hits at its
  centre) found that at 1000x420 - 250 dots wide, 105 rows - every screen overflowed: rows landed
  on the notice, some buttons sat below the bottom of the window entirely, and the widest ones
  hung off the right. Nothing was covering them; they were simply drawn in places a pointer could
  not reach.

Four changes, all in `ui.js` and `app.js`:

- **A button row is clamped above the status notice.** `buttonRow` computes
  `at = min(row, max(2, bottom() - height))`, where `bottom()` is the first row the notice may
  occupy. A row that cannot be drawn where the screen asked for it is moved rather than dropped,
  because a moved button still works.
- **Rows are centred from the handles' real widths.** Screens used to guess
  `Math.floor(h.cols() / 2) - 13`, which only looks centred for a label of one particular length.
  `helpers.centre(handles)` sums `handle.width` (which already includes the plate margins) and
  centres that. `start` is also clamped to `board.cols - width`, so a row is pulled left rather
  than hanging off the right edge.
- **`helpers.tight(tall)` drops whole rows instead of stacking them.** Two rows clamped onto the
  same space overlap, and only the top one is ever hit, so the second row looks just as dead as a
  button drawn off-screen. A screen that cannot fit shows fewer controls: Mode drops STEMS: SOON
  and CHOOSE ANOTHER, Awaiting shows only REVIEW THE FLAGS, Result folds its four buttons into one
  row and skips the stat signs.
- **A row that cannot fit the width says so.** When `width > board.cols` the status line reads
  *this window is too narrow - make it wider* rather than presenting controls that cannot work. This
  is an honest limit, not a bug: the dot board needs roughly 250 columns, so below about 1000px of
  window there is no sign layout that both fits and reads.

Re-probed at 1000x420 and 1400x900: every screen's buttons are hit-testable, no overlaps, and the
1400x900 layout is byte-for-byte what it was before. Note that `Emulation.setDeviceMetricsOverride`
does not work in this headless Chrome - a window size only takes effect if Chrome itself was
launched with that `--window-size`, so the short window needed a second Chrome on another port.
