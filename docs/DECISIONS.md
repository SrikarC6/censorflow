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
