"""Track metadata from tags, with a filename fallback.

Metadata is used for exactly one thing: looking lyrics up. Nothing here can fail a job.
If mutagen cannot read the file, or the tags are empty, or the filename is a bare name, the
result is simply less specific and the lyrics stage falls back to a fuzzy search.

The important detail is `primary_artist`. Real-world tags almost always list several
credits (`Don Toliver, Kodak Black`), and LRCLIB's `/api/get` wants the *one* artist it
indexed the track under. Feeding it the full multi-artist string matched **zero** of the
five songs in the spike; taking the first credit matched all five.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from mutagen import File, MutagenError

from . import audio_io, config
from .models import TrackInfo

logger = logging.getLogger(__name__)

# Credits are separated by any of these. Ordered longest-first so "feat." wins over "f".
_CREDIT_SEPARATORS = re.compile(
    r"\s*(?:,|;|/|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\bvs\.?|&|\bx\b)\s*",
    re.IGNORECASE,
)

# "01 All Day", "1-03 BROTHER STONE", "03.(Oh No) What You Got" -> a leading track number.
# The first alternative is a disc-track prefix, which must be consumed as a whole or the
# track half is left behind ("1-03 BROTHER STONE" must not become "03 BROTHER STONE").
_TRACK_NUMBER = re.compile(
    r"^[\s._-]*(?:\d{1,2}[\s._-]\d{1,3}[\s._-]+|\d{1,3}[\s._-]+|[A-Za-z]{1,2}\d{1,3}[\s._-]+)"
)

# Anything that is not a letter, digit or space is not part of a name.
_UNSAFE = re.compile(r"[\\/:*?\"<>|]")
# Leading/trailing decoration that survives the unsafe-character strip.
_DECORATION = re.compile(r"^[\s'\"()\[\]&+.,_-]+|[\s'\"()\[\]&+.,_-]+$")
# Extensions worth stripping when guessing a title from a filename. `Path.stem` cannot be
# trusted for this: it reads "3. Carti.m4a" as stem "3. Carti" -> "3", because it treats
# ". Carti" as the suffix.


def artist_candidates(artist: str | None) -> list[str]:
    """Split a possibly multi-artist tag into individual credits, best guess first.

    `None` and blank strings give an empty list. The original string is never returned on
    its own when it splits, because that combination is what makes `/api/get` fail.
    """
    if not artist:
        return []
    parts = _CREDIT_SEPARATORS.split(artist)
    # Strip unsafe characters *after* splitting: `_UNSAFE` contains "/", which is also a
    # credit separator, so sanitising first would erase the separator instead of splitting.
    cleaned = [_DECORATION.sub("", _UNSAFE.sub(" ", part).strip()) for part in parts]
    credits = [part for part in cleaned if len(part) > 1 and any(c.isalnum() for c in part)]
    if credits:
        return credits
    whole = _DECORATION.sub("", _UNSAFE.sub(" ", artist).strip())
    return [whole] if len(whole) > 1 and any(c.isalnum() for c in whole) else []


def primary_artist(artist: str | None) -> str | None:
    """The single credit LRCLIB is most likely to have indexed the track under.

    Known limitation: a genuine two-word act name containing an ampersand, such as
    "Simon & Garfunkel", is split. `artist_candidates` keeps the whole string out of the
    result only when the split produces a fragment too short to be a credit.
    """
    candidates = artist_candidates(artist)
    return candidates[0] if candidates else None


def title_from_filename(path: Path) -> str | None:
    """Guess a title from a filename by dropping any leading track number.

    Handles the common rips: `01 All Day.m4a`, `1-03 BROTHER STONE.m4a`,
    `03 Ni**as In Paris.m4a`, `06 - Carti (M3tamorphosis).m4a`.
    """
    name = _UNSAFE.sub(" ", Path(path).name).strip()
    stem = _strip_audio_extension(name)
    if not stem:
        return None
    trimmed = _TRACK_NUMBER.sub("", stem).strip(" ._-")
    # A filename that is nothing but a track number ("01.mp3") carries no title at all.
    # Returning the number would send "01" to the lyrics provider as a track name.
    if len(trimmed) >= 2 and not trimmed.isdigit():
        return trimmed
    return None


def _strip_audio_extension(name: str) -> str:
    """Drop a trailing audio extension by name, leaving dots inside the title alone."""
    head, dot, tail = name.rpartition(".")
    if dot and tail.lower() in config.AUDIO_EXTENSIONS:
        return head.strip()
    return name


def read_metadata(
    path: Path,
    *,
    artist: str | None = None,
    title: str | None = None,
    album: str | None = None,
) -> TrackInfo:
    """Best-effort `TrackInfo`: tags first, filename second, command-line last.

    Never raises for a missing or malformed tag block: a file with no tags and a useless
    filename yields whatever is available.
    """
    path = Path(path)
    tags = _read_tags(path)

    def pick(tag_value: str | None, *fallbacks: str | None) -> str | None:
        for candidate in (tag_value, *fallbacks):
            if candidate and candidate.strip():
                return candidate.strip()
        return None

    duration = None
    try:
        duration = audio_io.duration_seconds(path)
    except audio_io.AudioError:
        logger.debug("could not read a duration from %s", path.name)

    return TrackInfo(
        artist=pick(artist, tags.get("artist"), primary_artist(tags.get("artist"))),
        title=pick(title, tags.get("title"), title_from_filename(path)),
        album=pick(album, tags.get("album")),
        duration=duration,
    )


_TAG_KEYS = {
    "©art": "artist", "artist": "artist", "tpe1": "artist",
    "©nam": "title", "title": "title", "tit2": "title",
    "©alb": "album", "album": "album", "talb": "album",
}


def _read_tags(path: Path) -> dict[str, str]:
    """Artist, title and album as flat strings.

    Keys are mapped by hand rather than with `File(path, easy=True)`, because `easy` is not
    supported by every backend: mutagen raises `TypeError: ID3.load() got an unexpected
    keyword argument 'easy'` for the WAV and AIFF files mutagen reads through ID3. Since
    `read_metadata` must never raise, the raw keys are normalised here instead.

    Values are joined when a tag carries several of them: MP4/M4A legitimately does, and a
    multi-artist string is what `artist_candidates` exists to split.
    """
    try:
        audio = File(path)
    except (MutagenError, OSError, ValueError, TypeError) as error:
        logger.info("no readable tags in %s (%s)", path.name, error)
        return {}
    if audio is None or audio.tags is None:
        logger.info("%s carries no tag block", path.name)
        return {}

    tags: dict[str, str] = {}
    for key, value in audio.tags.items():
        name = _TAG_KEYS.get(str(key).strip().lower())
        if name is None:
            continue
        text = _tag_text(value)
        if text:
            tags.setdefault(name, text)
    return tags


def _tag_text(value: object) -> str:
    """One tag value as a string: a list is joined, an ID3 frame is unwrapped."""
    if isinstance(value, (list, tuple)):
        parts = [_tag_text(item) for item in value]
        return ", ".join(part for part in parts if part)
    frame_text = getattr(value, "text", None)
    if frame_text is not None:
        return _tag_text(frame_text)
    return str(value).strip()