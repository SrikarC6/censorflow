# Spike B - ASR on Apple Silicon

Goal: word-level timing accurate enough to place censor windows, fast enough to be usable
on a fanless laptop, and small enough to ship with the app.

**No lyric text appears in this document.** Transcripts of real songs are copyrighted and
stay in the gitignored `tmp/` directory.

## What was tried

| Option | Outcome |
|---|---|
| `mlx-community/parakeet-ctc-0.6b-v3` | Rejected: advertised in the `parakeet-mlx` docs but **404s on Hugging Face**. Only TDT v2 and v3 exist. |
| `mlx-community/parakeet-tdt-0.6b-v2` | Skipped: v3 is newer, faster, and strictly better on the metrics below. Kept as `ASR_FALLBACK_MODEL`. |
| `mlx-community/parakeet-tdt-0.6b-v3` | **Chosen.** |
| Whisper (`whisper.cpp` / `faster-whisper`) | Not installed. Rejected on size and speed: on M2 it is slower than Parakeet and its word timestamps need a forced-aligner pass to be trustworthy. Kept as an optional fallback path only. |

## API actually verified (`inspect.signature` on `parakeet_mlx` 0.5.3)

```python
from parakeet_mlx import from_pretrained
model = from_pretrained(path_or_hf_id, *, dtype=mx.bfloat16, cache_dir=None)
result = model.transcribe(audio_path)      # -> AlignedResult
```

`AlignedResult` exposes `.text`, `.tokens`, `.sentences`. Each token has
`id, text, start, duration, end, confidence`.

Two gotchas that matter:

1. **`.tokens` includes whitespace and punctuation tokens**, and word `text` has a leading
   space. They must be filtered before any profanity matching, or `" "` and `","` become
   tokens. `asr/parakeet.py::_to_words` drops tokens with no alphanumeric content and
   zero-length spans.
2. The docs' claim that the argument can be a Hugging Face id is true, but `from_pretrained`
   also accepts a **local directory** (it falls back to `config.json` + `model.safetensors`).
   We rely on the local path so the app never touches the network at run time.

## Measured, 45 s of vocals from a real song

| Metric | Value |
|---|---|
| Model load (cold, from local dir) | 36.4 s |
| Transcribe | 3.8 s |
| Speed | **11.9x realtime** |
| Sentences | 23 |
| Tokens / word-like tokens | 308 / 257 |
| Start times monotonic | yes |
| Confidence range | 0.71 - 1.00 |
| Word duration range (median) | 0.00 - 0.24 s (median 0.08 s) |

Warm model load is ~2 s, so a second run on the same machine costs almost nothing.

## End-to-end cost

120 s of a real song, headless `--auto`:

| Stage | Seconds |
|---|---|
| Decode (ffmpeg) | 0.6 |
| Separate (Demucs `htdemucs_ft`) | 30.5 |
| Transcribe (incl. cold model load) | 7.0 |
| Render + export | 0.5 |
| **Total** | **39.0** |

Separation, not ASR, is the bottleneck. That is what the `config.SEPARATION_QUALITY` presets
(`fast`: 0 shifts / 0.25 overlap, `pro`: 2 shifts / 0.50 overlap) exist for, and why the UI
reports progress per stage rather than pretending the job is uniform.

## Model download: the real problem

`hf download` with the default **Xet** transport **froze** on this machine at 2,078,986,731
of 2,508,288,736 bytes and stopped advancing; two concurrent downloads made it worse.
`HF_HUB_DISABLE_XET=1` worked but crawled at 0.3-0.5 MB/s.

What worked: 8 parallel resumable HTTP range requests concatenated by a small shell script.
That took ~40 minutes for 2.5 GB.

Consequences for the app:

- The model lives in `<project>/models/parakeet-tdt-0.6b-v3/` (moved out of the
  `~/.cache/huggingface` tree at the user's request so everything ships in one directory).
- **Phase 5 must** provide a first-run downloader with visible progress. The parallel-range
  script is the reference implementation; a single connection is not acceptable at this size.

## Known limitations

- **Word durations have a floor of 0.00 s.** Parakeet sometimes returns a zero-length span
  for a real word. `_to_words` drops those tokens; a hand-written test covers it.
- **No confidence thresholding.** Everything transcribed is returned, including 0.71-confidence
  words. That is deliberate for now: the review screen exists so a human can delete a false
  positive, and a bad threshold would silently hide real words in heavy autotune.
- Hard on clean, melodic, low-rap vocals: this is a rap-oriented model and a falsetto
  hold can come back empty. Phase 2's lyrics cross-check exists precisely to catch that case.