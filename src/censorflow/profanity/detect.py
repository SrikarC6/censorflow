"""Profanity detection over a word list.

The list is DATA (`data/profanity*.txt`), never code. Matching is whole-token only.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .. import config
from ..models import SOURCE_ASR, Flag, Word

logger = logging.getLogger(__name__)


def _find_data_dir() -> Path:
    """Locate the shipped `data/` directory by walking up from this file."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("censorsflow data/ directory not found")


DATA_DIR = _find_data_dir()

_TOKEN_SPLIT = re.compile(r"[a-z0-9']+")
# Any run of non-alphanumeric characters, i.e. symbol masking.
_SYMBOL_RUN = re.compile(r"[^a-z0-9']+")
# Cap on the spelling cross-product for a pathologically stretched word.
_MAX_RUN_FORMS = 32


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _collapse_runs(text: str, min_repeats: int, keep: int = 1) -> str:
    """Rewrite a run of `min_repeats` or more identical characters down to `keep` copies."""
    out: list[str] = []
    i = 0
    while i < len(text):
        j = i
        while j < len(text) and text[j] == text[i]:
            j += 1
        run = text[i:j]
        out.append(run[0] * keep if len(run) >= min_repeats else run)
        i = j
    return "".join(out)


def _symbol_wildcards(raw: str) -> re.Pattern[str] | None:
    """Regex for a masked token, or None if it has no masking.

    Symbol runs become wildcards of the same length.
    """
    text = _strip_accents(raw).lower()
    if not _SYMBOL_RUN.search(text):
        return None
    parts: list[str] = []
    for chunk in re.split(r"([^a-z0-9']+)", text):
        if not chunk:
            continue
        if chunk[0].isalnum() or chunk[0] == "'":
            parts.append(re.escape(_collapse_runs(chunk, config.COLLAPSE_MIN_REPEATS)))
        else:
            parts.append("." * len(chunk))
    return re.compile("".join(parts))


def _read_words(path: Path) -> set[str]:
    """Read a word-list file: one whole token per line, blanks and # comments skipped."""
    words: set[str] = set()
    if not path.exists():
        return words
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        word = normalise(line)
        if word:
            words.add(word)
    return words


def load_wordlist(
    extra_path: Path | None = None, allowlist_path: Path | None = None
) -> tuple[frozenset[str], frozenset[str]]:
    """Load the profane word list and the allowlist.

    Returns (profane, allowed). Both sets are normalised the same way as input, so
    "Sh!t" in a user's extra file still matches.
    """
    profane = _read_words(DATA_DIR / "profanity.txt") | _read_words(
        extra_path or DATA_DIR / "profanity_extra.txt"
    )
    allowed = _read_words(allowlist_path or DATA_DIR / "allowlist.txt")
    return frozenset(profane), frozenset(allowed)


def _fold(text: str) -> str:
    """Lowercase, de-accent, and drop punctuation, including apostrophes."""
    if not text:
        return ""
    text = _strip_accents(text).lower()
    return "".join(c for c in text if c.isalnum())


def normalise(text: str) -> str:
    """Fold a token to its matching form: lowercase, de-accented, unpunctuated,
    with runs of 3+ repeated letters collapsed.

    "Shiiiit", "shit!" and "SHIT" all land on the same key. A doubled letter such as
    the "ss" in "ass" is preserved, because collapsing it would collide with "as";
    `variants` offers the stretched spellings separately.
    """
    collapsed = _collapse_runs(_fold(text), config.COLLAPSE_MIN_REPEATS)
    return "" if len(collapsed) < 2 else collapsed


def _run_forms(text: str) -> list[str]:
    """Candidate spellings of one token: a doubled letter may be one letter or a pair.

    Sung words are ambiguous. "shiit" may be one stretched vowel or the doubled vowel
    of the word on the list, and only one of those is a real word, so both are offered.
    The two-letter forms a word like "ass" could shrink to are then discarded by
    `variants`, which drops candidates under three letters.
    """
    runs: list[list[str]] = []
    i = 0
    while i < len(text):
        j = i
        while j < len(text) and text[j] == text[i]:
            j += 1
        run = text[i:j]
        runs.append([run[0], run[0] * 2] if len(run) >= 2 else [run])
        i = j
    forms = [""]
    for options in runs:
        forms = [prefix + option for prefix in forms for option in options]
    return forms[:_MAX_RUN_FORMS]


_SIBILANT_ES = ("ches", "shes", "sses", "xes", "zes")


def _surface_stems(token: str) -> set[str]:
    """-ies/-ier and sibilant -es, on the normalised token only.

    Doubled-letter alternates are skipped: "assess" can shrink to "asses".
    """
    stems: set[str] = set()
    for ending, cut, tail, least in (
        ("ies", 3, "y", 5),
        ("ier", 3, "y", 6),
        ("iest", 4, "y", 7),
    ):
        if len(token) >= least and token.endswith(ending):
            stems.add(token[:-cut] + tail)
    for ending in _SIBILANT_ES:
        if token.endswith(ending) and len(token) - 2 >= 3:
            stems.add(token[:-2])
    return stems


def _inflection_stems(token: str) -> set[str]:
    """One peel of -s/-ing/-in/-ed/-er. -ing/-ed also restore a silent e."""
    stems: set[str] = set()
    if token.endswith("in") and len(token) - 2 >= 4:
        stems.add(token[:-2])
    for suffix in config.PEELABLE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            stem = token[: -len(suffix)]
            stems.add(stem)
            if suffix in ("ing", "ed") and not stem.endswith("e"):
                stems.add(stem + "e")
    return stems
    stems: set[str] = set()
    if token.endswith("in") and len(token) - 2 >= 4:
        stems.add(token[:-2])
    for suffix in config.PEELABLE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            stem = token[: -len(suffix)]
            stems.add(stem)
            if suffix in ("ing", "ed") and not stem.endswith("e"):
                stems.add(stem + "e")
    return stems


def variants(token: str) -> set[str]:
    """Candidate list forms: spellings plus peeled inflections, whole tokens only."""
    folded = _fold(token)
    token = normalise(folded)
    if not token:
        return set()
    found: set[str] = set()
    layer: list[str] = []
    for form in [token, *_run_forms(folded), *_surface_stems(token)]:
        if form not in found:
            found.add(form)
            layer.append(form)
    for _ in range(2):
        nxt: list[str] = []
        for current in layer:
            for stem in _inflection_stems(current):
                if stem not in found:
                    found.add(stem)
                    nxt.append(stem)
        layer = nxt
    return {f for f in found if len(f) >= 3}


def tokenise(text: str) -> list[str]:
    """Split lyric or transcript text into alphanumeric tokens."""
    return _TOKEN_SPLIT.findall(text.lower())


def wordlists(
    extra_path: Path | None = None, allowlist_path: Path | None = None
) -> tuple[frozenset[str], frozenset[str]]:
    """The cached (profane, allowed) pair. Use this to pass the lists on to a helper."""
    return _cached_wordlist(
        str(extra_path) if extra_path else None,
        str(allowlist_path) if allowlist_path else None,
    )


@lru_cache(maxsize=4)
def _cached_wordlist(extra: str | None, allow: str | None) -> tuple[frozenset[str], frozenset[str]]:
    return load_wordlist(Path(extra) if extra else None, Path(allow) if allow else None)


def is_profane(
    token: str,
    profane: frozenset[str],
    allowed: frozenset[str],
) -> bool:
    """True if a whole-token form is listed and none of the token's forms is allowlisted."""
    forms = variants(token)
    if forms & allowed:
        return False
    if forms & profane:
        return True
    pattern = _symbol_wildcards(token)
    if pattern is None:
        return False
    if any(pattern.fullmatch(entry) for entry in allowed):
        return False
    return any(pattern.fullmatch(entry) for entry in profane)


def detect(
    words: list[Word],
    *,
    extra_path: Path | None = None,
    allowlist_path: Path | None = None,
    wordlist: tuple[frozenset[str], frozenset[str]] | None = None,
) -> list[Flag]:
    """Flag profane words in a transcript, keeping each word's start/end."""
    profane, allowed = wordlist or _cached_wordlist(
        str(extra_path) if extra_path else None,
        str(allowlist_path) if allowlist_path else None,
    )
    flags: list[Flag] = []
    for index, word in enumerate(words):
        if is_profane(word.text, profane, allowed):
            flags.append(
                Flag(
                    word_index=index,
                    text=word.text,
                    start=word.start,
                    end=word.end,
                    source=SOURCE_ASR,
                    confidence=word.confidence,
                    approx=False,
                    censor=True,
                )
            )
    logger.info("detected %d profane word(s) in %d transcribed words", len(flags), len(words))
    return flags


def mask_word(text: str) -> str:
    """Redact a flagged word for logs and reports: first letter plus asterisks.

    Reports must never contain the full word, even locally.
    """
    cleaned = normalise(text)
    first = cleaned[0] if cleaned else (text.strip()[:1] or "*")
    return first + "*" * max(1, len(cleaned) - 1)


def mask_flags(flags: list[Flag]) -> list[str]:
    return [mask_word(f.text) for f in flags]