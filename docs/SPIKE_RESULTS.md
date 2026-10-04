# Phase 0 spike results

Machine: MacBook Air M2, 16 GB, arm64, macOS. ffmpeg 9.0.2, uv 0.9.22, Python 3.11 via uv.
Wall times are single runs on an idle machine. No lyric text appears in this file (rule 7);
only match status, counts and structure are recorded.

## Test material

Five full tracks supplied by the user in `samples/` (gitignored). All AAC 256 kbps, 44.1 kHz stereo.
Spikes ran on a 45 s excerpt cut at t=30 s (`tmp/spike/*.excerpt.wav`).

| File | Artist tag | Album tag | Duration |
|---|---|---|---|
| `01 All Day.m4a` | multi-artist (5 names) | All Day | 310.95 s |
| `03 (Oh No) What You Got.m4a` | multi-artist | Justified | 271 s |
| `03 Ni__as In Paris.m4a` | multi-artist (2) | Watch The Throne (Deluxe) | 219.38 s |
| `06 M3tamorphosis.m4a` | multi-artist (2) | Whole Lotta Red | 312 s |
| `1-03 BROTHER STONE.m4a` | multi-artist (2) | HARDSTONE PSYCHO | 202.8 s |

Chosen to cover: mainstream rap with clear diction (All Day), a clean non-explicit track for
false-positive checks (Oh No), heavily auto-tuned falsetto plus mumbling (BROTHER STONE),
and extreme auto-tune and ad-libs (M3tamorphosis).

Two spikes uncovered real problems with the naive approach:

- **Every artist tag is multi-artist** (`Kanye West, Theophilus London, Allan Kingdom, Paul McCartney`).
  LRCLIB needs one artist, so `primary_artist()` must reduce the tag by splitting on
  `feat.`, `ft.`, `featuring`, `,`, `;`, ` & ` and taking the first credit. Without this, 0/5 matched.
- **Two titles ship pre-censored** (`Ni**as In Paris`, `M3tamorphosis`). This is direct evidence that the
  "expand asterisk / symbol masking" normalization rule in `AGENTS.md` is required, not theoretical.

## Spike A: separation - WORKS

Backend: `mlx-audio-separator` 0.1.20, model `htdemucs_ft.yaml`.

```
uv run --with "mlx-audio-separator[convert]" python -c "
from mlx_audio_separator import Separator
sep = Separator(output_dir='tmp/spike/sep_nia', output_format='FLAC')
sep.load_model('htdemucs_ft.yaml')
print(sep.separate('tmp/spike/03 Ni__as In Paris.excerpt.wav'))"
```

First attempt failed: `ImportError: Model conversion requires the [convert] extras`.
Fix was the documented one-time conversion step. The `[convert]` extra pulls
`torch>=2.6`, `onnx>=1.15`, `demucs>=4.0`. It is installed as a **throwaway overlay**
(`uv run --with`), never as a project dependency, and only to build the cache at
`~/.cache/mlx-audio-separator/demucs/htdemucs_ft.safetensors`. Every later run is pure MLX
with no torch in the process.

| Measurement | Value |
|---|---|
| Model load + convert (cold) | 18.05 s (includes one-time conversion) |
| Separate 45 s of audio | 31.76 s |
| Throughput | ~1.4x realtime |
| Peak RSS (full subprocess) | ~59 MB before model load; MLX weights are GPU-resident |
| Output | 4 FLAC stems: drums, bass, other, vocals |

Quality checks on the separated stems:

- All four stems are **exactly** the mix length (1 982 444 samples), so no pad/trim is needed
  in practice, though the pipeline still guards it.
- Vocal stem RMS 0.1366 vs mix RMS 0.2891; vocals carry ~22 % of mix energy - plausible.
- At the loudest vocal frame (25.27 s) the vocal stem peaks at **0.900** while the mix peaks at
  **0.785**. The vocal is louder than the mix at its own peak, which is the signature of a genuine
  mask-based isolation rather than an attenuation.
- **The four stems do not sum back to the mix exactly**: RMS error 0.0305, peak sample error 0.88.

That last point is a design decision, not a defect to fix: the render only ever needs the vocal stem
(`final = mix - vocals * mask`). Where an instrumental reference is needed it is derived as
`mix - vocals`, never as `drums + bass + other`, because a 3-stem sum carries that 0.03 RMS error.

## Spike B: ASR - see `docs/SPIKE_B_ASR.md`

Model weights are 2.5 GB each for `parakeet-tdt-0.6b-v2` and `-v3`.

Tooling verified: `from_pretrained(repo_or_local_dir, *, dtype, cache_dir) -> BaseParakeet`,
and `model.transcribe(path)` returning an `AlignedResult` with `.text`, `.tokens`, `.sentences`.

Blocker found: Hugging Face downloads **stall** on this machine with the default Xet transport.
`hf download` froze at 2.08 GB of 2.51 GB and stopped advancing; two concurrent downloads made it worse.
Retrying with `HF_HUB_DISABLE_XET=1` also crawled (~0.3-0.5 MB/s).
Workaround that works: fetch the repo with 8 parallel resumable HTTP range requests
(`tmp/spike/fetch_hf_repo.sh`) and pass the **local directory** to `from_pretrained`, which is documented
to accept "Hugging Face or local directory" and falls back to `Path(x)/model.safetensors`.

Note the Context7 docs for parakeet-mlx advertise `mlx-community/parakeet-ctc-0.6b-v3`; that repo
**does not exist** on Hugging Face (HTTP 404). Verified before use.

## Spike C: lyrics - WORKS (5/5)

Backend: LRCLIB `/api/get` with a descriptive `User-Agent`, plus `syncedlyrics` as a second source.

```
uv run python tmp/spike/lrclib_spike.py samples/*.m4a
```

| Track | HTTP | Match | Duration file/LRCLIB | Synced | `hasWordSync` |
|---|---|---|---|---|---|
| All Day | 200 | id 2483587 | 311 / 311.0 | yes | **false** |
| (Oh No) What You Got | 200 | id 529394 | 271 / 271.0 | yes | **false** |
| Ni**as In Paris | 200 | id 972408 | 219 / 219.0 | yes | **false** |
| M3tamorphosis | 200 | id 2452253 | 312 / 312.0 | yes | **false** |
| BROTHER STONE | 200 | id 11504207 | 203 / 202.84 | yes | **false** |

Key structural findings:

- **Duration matching works, but the +/-2 s tolerance is real.** BROTHER STONE matched at
  202.84 s against a 203 s file. A wrong duration silently returns 404, so the duration passed to
  LRCLIB must come from the decoded file, and a 404 must be retried without it rather than fatal.
- **Results are line-level, never word-level.** All 5 records have `hasWordSync=false` and zero
  inline `<mm:ss.xx>` word tags. So the "word-level lyric times if available" branch in `AGENTS.md`
  will effectively always take the fallback: estimate proportionally inside the lyric line.
- **`lyricsfile` is better than `syncedLyrics` for that fallback.** Its schema is
  `version`, `metadata{title,artist,album,duration_ms,instrumental,start_ms,end_ms}`, `plain`,
  `lines[]` where each line has `text`, `start_ms` **and** `end_ms`. An LRC line gives only a start
  time, so with `end_ms` the proportional estimate for a lyrics-only flag can be much tighter.
  It is a YAML document, parsed with `pyyaml`, which is already a transitive dependency.
- `syncedlyrics` matched 4/4 on the same tracks with its bundled LRCLIB provider in 1.0-2.2 s per
  query, and returns identical line counts, confirming both paths hit the same records. Its value is
  the extra providers (Genius, Musixmatch, Deezer, NetEase, Megalobiz) as a fallback when LRCLIB 404s.
- Lyric text is written only to `tmp/spike/lrclib/` and `.censorflow/` (both gitignored). Nothing
  lyric-shaped is committed.

## Phase 0 status

| Spike | Result |
|---|---|
| A separation | **Works.** `mlx-audio-separator` + `htdemucs_ft`, ~1.4x realtime, exact-length stems. No fallback needed. |
| B ASR | Pending model download; API verified, download workaround found. |
| C lyrics | **Works.** 5/5 LRCLIB, 4/4 syncedlyrics, line-level only. |