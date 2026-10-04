"""Profanity detection over a word list.

The list is DATA (`data/profanity*.txt`), never code. Matching is whole-token only, so
"class" is never flagged for containing a shorter word; normalisation handles the shapes
singing and tagging actually produce: elongated letters, symbol masking, inflections.

Unit tests use a test-only list of innocuous placeholder words, never real profanity.
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
    """Rewrite runs of a repeated character down to `keep` copies.

    `min_repeats` is the shortest run worth rewriting; shorter runs are left alone
    because collapsing them turns one real word into another. So with `min_repeats=3`,
    "fuuuuck" becomes "fuck" while the doubled s in "ass" survives. `keep=2` and a higher
    `min_repeats` answers the opposite question: is a long run one stretched letter or a
    genuinely doubled one? "wbbbble" can be "wibble".
    """
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

    Symbol runs become wildcards of the *same length*, which is what lets "sh*t" match
    "shit" and "ni**ga" match "nigga" without guessing which letter was hidden.
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
    """Lowercase, de-accented and unpunctuated, without changing any lengths."""
    if not text:
        return ""
    text = _strip_accents(text).lower()
    return "".join(c for c in text if c.isalnum() or c == "'")


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


def variants(token: str) -> set[str]:
    """Candidate list forms for one token: its spellings, plus peeled inflections.

    Whole-token matching only; these are candidate *keys*, each still looked up in the
    word list as a complete word. Candidates shorter than three letters are dropped.
    """
    folded = _fold(token)
    token = normalise(folded)
    if not token:
        return set()
    found: set[str] = set()
    for form in [token, *_run_forms(folded)]:
        found.add(form)
        current = form
        for _ in range(2):  # "snorkings" -> "snorking" -> "snork"
            for suffix in config.PEELABLE_SUFFIXES:
                if current.endswith(suffix) and len(current) - len(suffix) >= 3:
                    current = current[: -len(suffix)]
                    found.add(current)
                    break
            else:
                break
    return {f for f in found if len(f) >= 3}


def tokenise(text: str) -> list[str]:
    """Split lyric or transcript text into alphanumeric tokens."""
    return _TOKEN_SPLIT.findall(text.lower())


@lru_cache(maxsize=4)
def _cached_wordlist(extra: str | None, allow: str | None) -> tuple[frozenset[str], frozenset[str]]:
    return load_wordlist(Path(extra) if extra else None, Path(allow) if allow else None)


def is_profane(
    token: str,
    profane: frozenset[str],
    allowed: frozenset[str],
) -> bool:
    """True if any whole-token form of `token` is on the list and not allowlisted.

    Every spelling of the token is looked up, so "snorrk" and "w*bble" both reach the
    entry they stand in for, and an allowlisted entry silences all of its spellings.
    Every comparison is a full-token match, so a list entry never fires on a substring
    of a longer word.
    """
    if not normalise(token):
        return False
    hits = {form for form in variants(token) if form in profane}
    if not hits:
        pattern = _symbol_wildcards(token)
        if pattern is None:
            return False
        hits = {entry for entry in profane if pattern.fullmatch(entry)}
    return bool(hits) and not (hits & allowed)


def detect(
    words: list[Word],
    *,
    extra_path: Path | None = None,
    allowlist_path: Path | None = None,
) -> list[Flag]:
    """Flag profane words in an ASR transcript. ASR timing is authoritative."""
    profane, allowed = _cached_wordlist(
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