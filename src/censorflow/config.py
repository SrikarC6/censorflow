"""All tunable constants for CensorFlow.

Every magic number in the pipeline lives here and nowhere else, so behaviour can be
changed in one place. Grouped by concern; see `AGENTS.md` for the rationale.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Audio working format -------------------------------------------------------
# The pipeline works entirely in 44.1 kHz stereo float32, whatever the input was.
SAMPLE_RATE = 44_100
CHANNELS = 2
WORKING_DTYPE = "float32"

# ASR runs on the model family's native format: mono 16 kHz.
ASR_SAMPLE_RATE = 16_000
ASR_CHANNELS = 1

# --- Separation -----------------------------------------------------------------
# Censoring subtracts the vocal stem from the mix. A leaky stem leaves a quieter
# copy of the swear, so the default is a vocals-only Mel-Band-RoFormer (Kim Vocal
# 2, UVR filename). Demucs HT stays a named fallback. Override with
# CENSORFLOW_SEPARATOR_MODEL. Both are passed to Separator.load_model.
SEPARATOR_MODEL = os.environ.get(
    "CENSORFLOW_SEPARATOR_MODEL",
    "vocals_mel_band_roformer.ckpt",
)
DEMUCS_MODEL = "htdemucs_ft.yaml"
STEMS_CENSOR = ("vocals", "instrumental")
# Stem mode names, for the later skeleton screen only.
STEMS_FULL = ("vocals", "drums", "bass", "other")

# Separator output is compared against the mix length; pad or trim up to this many
# samples without complaint, warn above it.
STEM_LENGTH_TOLERANCE_SAMPLES = 2048

# Quality presets, passed straight to the separator's architecture parameters. Pro uses
# two shifts and half overlap: slower, cleaner, and only worth it on an export.
QUALITY_FAST = "fast"
QUALITY_PRO = "pro"
DEFAULT_QUALITY = QUALITY_FAST
SEPARATION_QUALITY: dict[str, dict[str, float]] = {
    QUALITY_FAST: {"shifts": 0, "overlap": 0.25},
    QUALITY_PRO: {"shifts": 2, "overlap": 0.50},
}

# --- Censor windows (see "Censor windows" in AGENTS.md) -------------------------
# Apple Music's clean of the same master is a same-mix vocal duck, not a full-mix
# mute and not a rewritten take. Punches are short (median ~130 ms, p25 ~90 ms)
# with the beat left up. We still subtract vocals only; these numbers size the
# punch like that edit instead of a long padded hole.

PAD_PRE_MS = 20
PAD_POST_MS = 40
MIN_WINDOW_MS = 90
# The ASR-plus-lyrics clock lands about a second after the sung onset.
# Every window starts this much earlier than that detection. The end stays,
# so the mute covers the word instead of sliding off the front of it.
CENSOR_LEAD_MS = 1000
# Windows closer than this are merged into one.
MERGE_GAP_MS = 30
FADE_MS = 10

# Short-time RMS used to decide whether the vocal is still sounding.
RMS_WINDOW_MS = 20
RMS_HOP_MS = 10
# Extend while frame RMS >= this fraction of the word's own peak RMS.
RMS_TAIL_FRACTION = 0.30
# Stop extending after this many consecutive frames below the threshold.
RMS_TAIL_QUIET_MS = 30
# Hard cap on tail extension, whatever the energy says.
MAX_TAIL_MS = 200
# Never extend into the next word.
NEXT_WORD_GUARD_MS = 10

# --- ASR ------------------------------------------------------------------------
# parakeet-tdt-0.6b-v3 on Apple Silicon via mlx. Verified present on Hugging Face;
# the ctc-0.6b-v3 repo advertised in the library docs does NOT exist.
ASR_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
ASR_FALLBACK_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
ASR_WEIGHT_SUBTYPE = "bfloat16"

# --- Export ---------------------------------------------------------------------
# Lossless by default; the previous version shipped MP3 only, which was a mistake.
DEFAULT_EXPORT_FORMAT = "flac"
FLAC_SUBTYPE = "PCM_24"
WAV_SUBTYPE = "PCM_16"
MP3_BITRATE = "320k"
SUPPORTED_EXPORT_FORMATS = ("flac", "wav", "mp3")

# --- Profanity detection --------------------------------------------------------
# Normalisation: collapse runs of repeated letters down to one, but never collapse a
# genuine 2-letter token (it, an, as, be, do...) into nothing.
COLLAPSE_MIN_REPEATS = 3
# Suffixes stripped when probing a token against the list. Every suffix that
# fits is applied, not only the first; see detect._inflection_stems.
PEELABLE_SUFFIXES = ("ing", "ings", "ed", "er", "ers", "est", "s")

# --- Lyrics (best effort, never blocking) ---------------------------------------
LRCLIB_URL = "https://lrclib.net/api"
# LRCLIB asks clients to identify themselves.
HTTP_USER_AGENT = os.environ.get(
    "CENSORFLOW_USER_AGENT",
    "CensorFlow/0.1.0 (https://github.com/SrikarC6/censorflow)",
)
LYRICS_TIMEOUT_S = 15
# A candidate is only accepted if its duration is within +/- this many seconds of the file.
LYRICS_DURATION_TOLERANCE_S = 2.0
# Penalties, in seconds, added to a search candidate's score for disagreeing with the tags.
# Large enough to lose to any duration drift, small enough to keep the arithmetic readable.
LYRICS_SEARCH_TITLE_PENALTY_S = 30.0
LYRICS_SEARCH_ARTIST_PENALTY_S = 300.0
# Guard rails for the proportional timing estimate of a lyrics-only flag.
LYRICS_MIN_LINE_S = 0.2
LYRICS_MIN_WORD_S = 0.08
LYRICS_MAX_WORD_S = 2.0
# Sequence-align ASR tokens onto lyric lines. Warp a line onto the lyric clock
# only when the line is about as long as the sung phrase. A line that is much
# longer (a held lyric card over a few bars) must not stretch the phrase across
# the gap: that lands the mute off the syllable.
ALIGN_MATCH_SCORE = 3.0
ALIGN_FAR_SCORE = -1.0
ALIGN_MISMATCH_SCORE = -2.0
ALIGN_GAP_SCORE = -1.0
# Same-text pairs farther apart than this are a "far" match, so a chorus repeat
# is not glued to the wrong verse. A word or two of ASR drift is well inside.
ALIGN_TIME_GATE_S = 6.0
# line_duration / asr_span above this (or below its reciprocal) keeps ASR times.
ALIGN_MAX_STRETCH = 1.25
# A single matched word may slide onto its lyric estimate by at most this much.
ALIGN_MAX_SHIFT_S = 0.75
# A lyrics-only token with no neighbour on one side is this long, packed against
# the neighbour that does exist, instead of being spread across the rest of the card.
ALIGN_PACK_WORD_S = 0.40
# Pull a window onto the vocal peak within this radius when the peak is clearly
# louder than the estimated centre. Wider than a syllable, and it grabs the
# next word. A span already longer than one syllable keeps its own start:
# recentring it lands the mute on a later syllable.
SNAP_RADIUS_MS = 180
SNAP_PEAK_RATIO = 1.4
SNAP_LONG_SPAN_S = 0.25
# A lyrics-only slot often starts on a later syllable. Short ASR fragments
# just before it are the opening syllables of the same word. Walk back across
# them, but stop at a gap or at this cap so the previous word stays audible.
ONSET_FRAGMENT_MAX_S = 0.16
ONSET_FRAGMENT_GAP_S = 0.10
ONSET_PULL_MAX_S = 0.35

# --- Paths ----------------------------------------------------------------------

# Extensions we are willing to keep when saving an upload or stripping a filename. This is
# only a convenience: `audio_io.has_audio_stream` validates with ffprobe, so a file with the
# wrong extension is still accepted and a file with no audio in it is still refused.
AUDIO_EXTENSIONS = frozenset(
    {
        "aac", "aif", "aiff", "alac", "ape", "flac", "m4a", "m4b", "mp3", "mp4", "ogg",
        "oga", "opus", "wav", "wave", "wma", "wv", "mka", "m4r",
    }
)


def _project_root() -> Path:
    """The directory holding this project's pyproject.toml.

    Model weights are kept inside the project tree rather than in a shared cache, so a
    packaged app is one directory to copy. The upward search keeps that true for an
    editable install; a non-editable install falls back to the working directory.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


PROJECT_DIR = _project_root()
# STT weights, downloaded on first run. Not committed: ~2.3 GB.
MODEL_DIR = Path(os.environ.get("CENSORFLOW_MODEL_DIR", PROJECT_DIR / "models"))
# Separator weights (RoFormer ckpt/safetensors and Demucs YAML). The library keeps
# downloads and converted MLX checkpoints in two directories of its own, both
# pointed here by env var in `separation/demucs.py` so all model data lives under
# MODEL_DIR.
SEPARATOR_DIR = MODEL_DIR / "mlx-audio-separator"
SEPARATOR_MODEL_DIR = SEPARATOR_DIR / "models"
SEPARATOR_DEMUCS_CACHE_DIR = SEPARATOR_DIR / "demucs"

# Per-user runtime state: job directories, the lyrics cache, worker logs.
HOME_DIR = Path(os.environ.get("CENSORFLOW_HOME", Path.home() / ".censorflow"))
JOBS_DIR = HOME_DIR / "jobs"
LYRICS_CACHE_DIR = HOME_DIR / "lyrics"
LOG_DIR = HOME_DIR / "logs"

# --- Server ---------------------------------------------------------------------
SERVER_HOST = "127.0.0.1"  # local only, never 0.0.0.0
SERVER_PORT = 8765
# The web app is served from disk; these are the only two things it may reach.
WEB_DIR = PROJECT_DIR / "web"
# How often the event stream emits a comment line so an idle connection is not closed.
SSE_KEEPALIVE_S = 15.0
# Uploads are streamed to disk in chunks and refused above this size, rather than being
# read into memory or silently filling the disk.
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 4 * 1024**3
# Wall-clock cap for one worker subprocess. Separation prints almost nothing on
# stdout until it finishes, so this is not an idle timeout. It only stops a stage
# that has actually hung.
WORKER_TIMEOUT_S = 45 * 60
# A vocal stem quieter than this is treated as "no vocals", not as a successful mute.
VOCAL_MIN_RMS = 1e-4
# Speech-model download. One connection is too slow at 2.5 GB, and the Xet
# transport stalled on this machine, so the file is fetched as parallel HTTP
# ranges from the CDN. See docs/SPIKE_B_ASR.md.
ASR_DOWNLOAD_PARALLEL = 8
ASR_DOWNLOAD_CHUNK_BYTES = 16 * 1024 * 1024

# --- Preview clips --------------------------------------------------------------
# Per-flag A/B preview length either side of the flagged word.
PREVIEW_PAD_S = 1.5