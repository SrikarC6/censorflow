"""LRCLIB lyrics lookup.

Lyrics are a *cross-check*, never the source of truth: ASR owns word timing, and lyrics
only tell us which words were sung. So this module is written to be unable to fail a job.
Every network error, every 404, every malformed payload becomes `None` plus a log line.

Lookup order, cheapest and most exact first:

1. `/api/get` with artist + title + duration. Duration must be within +/-2 s or the call
   404s, which is a useful exact-match filter.
2. `/api/get` again without the duration, for tags whose duration is off (a fade-out, a
   different press).
3. `/api/search` with artist + title, then pick the candidate whose duration is closest.
   This is what rescues pre-masked titles such as `Ni**as In Paris`, where the local tags
   and LRCLIB disagree on every field.

Steps 1 and 2 are retried for each artist credit from the tag, because real tags list
several names and LRCLIB indexes the track under one of them.

The album name is deliberately **not** sent: it is the field tags get wrong most often
(LRCLIB had "The College Dropout" where the file said "Watch The Throne (Deluxe)"), and
`/api/get` treats a mismatch as a reason to 404.

Responses are cached under `config.LYRICS_CACHE_DIR`, which is gitignored. Nothing from a
cached response is ever committed: see `AGENTS.md`'s copyright rule.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .. import config
from ..models import TrackInfo

logger = logging.getLogger(__name__)

# Bump this to invalidate every cached response after a change to the parsing contract.
_CACHE_VERSION = "v1"


@dataclass(slots=True)
class LyricsRecord:
    """One provider record. `raw` is the untouched payload; timing lives in `synced.py`."""

    provider: str
    track_id: int
    title: str | None
    artist: str | None
    album: str | None
    duration: float | None
    instrumental: bool
    has_word_sync: bool
    synced_lyrics: str | None
    plain_lyrics: str | None
    raw: dict[str, Any] = field(default_factory=dict)


def fetch(track: TrackInfo, *, artists: list[str] | None = None) -> LyricsRecord | None:
    """Look a track up. Returns `None` rather than raising, for any reason at all."""
    if not track.title:
        logger.info("no title to look lyrics up with")
        return None

    for artist in (artists or []):
        if not artist:
            continue
        record = _get(track, artist)
        if record is not None:
            return record
    return _search(track, (artists or [None])[0])


def shutdown() -> None:
    """Close the shared client. Safe to call more than once."""
    global _CLIENT
    if _CLIENT is not None:
        _CLIENT.close()
        _CLIENT = None


def _get(track: TrackInfo, artist: str) -> LyricsRecord | None:
    """Exact match, with and without the duration filter."""
    cache = _cache_path("get", artist, track.title)
    record = _read_cache(cache)
    if record is not None:
        return record

    for duration in (track.duration, None):
        params = {"artist_name": artist, "track_name": track.title}
        if duration is not None:
            params["duration"] = str(round(duration))
        payload = _request_json("get", params)
        if payload is None:
            logger.debug(
                "LRCLIB /api/get missed for %r - %r (duration=%s)", artist, track.title, duration
            )
            continue
        record = _to_record(payload)
        if record is None:
            continue
        if duration is not None and not _duration_ok(record.duration, duration):
            logger.debug("LRCLIB record %s is outside the duration tolerance", record.track_id)
            continue
        _write_cache(cache, record)
        logger.info("lyrics found for %r - %r (LRCLIB %s)", artist, track.title, record.track_id)
        return record
    return None


def _search(track: TrackInfo, artist: str | None) -> LyricsRecord | None:
    """Fuzzy match, picking the candidate whose duration is nearest the file."""
    cache = _cache_path("search", artist or "", track.title)
    record = _read_cache(cache)
    if record is not None:
        return record

    params = {"track_name": track.title}
    if artist:
        params["artist_name"] = artist
    payload = _request_json("search", params)
    if payload is None or not isinstance(payload, list):
        logger.info("LRCLIB search failed for %r", track.title)
        return None
    candidates = [item for item in payload if isinstance(item, dict)]
    best = _pick(candidates, track, artist)
    if best is None:
        logger.info("no usable LRCLIB search result for %r", track.title)
        return None
    record = _to_record(best)
    if record is None:
        return None
    _write_cache(cache, record)
    logger.info("lyrics found for %r via LRCLIB search (%s)", track.title, record.track_id)
    return record


def _pick(
    candidates: list[dict[str, Any]], track: TrackInfo, artist: str | None
) -> dict[str, Any] | None:
    """Score search results. Duration dominates; title and artist break ties.

    `/api/search` is not paginated and returns up to 20 rows in relevance order, which
    includes live covers, remixes and *different songs that share a title*. Duration plus a
    title comparison is what stops a 70-second edit being chosen for a 219-second track.
    """
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for position, item in enumerate(candidates):
        duration = item.get("duration")
        if not isinstance(duration, (int, float)):
            continue
        drift = abs(float(duration) - track.duration) if track.duration else 0.0
        score = drift
        if artist and not _artist_matches(item.get("artistName"), artist):
            score += config.LYRICS_SEARCH_ARTIST_PENALTY_S
        if not _title_matches(item.get("trackName"), track.title):
            score += config.LYRICS_SEARCH_TITLE_PENALTY_S
        scored.append((score, position, item))
    if not scored:
        return None
    scored.sort(key=lambda entry: (entry[0], entry[1]))
    score, _, best = scored[0]
    if track.duration and score > config.LYRICS_DURATION_TOLERANCE_S:
        logger.info(
            "no LRCLIB candidate within %.1fs of %.1fs (closest was %.1fs away, too far)",
            config.LYRICS_DURATION_TOLERANCE_S,
            track.duration,
            score,
        )
        return None
    return best


def _duration_ok(record_duration: float | None, wanted: float) -> bool:
    if record_duration is None:
        return True
    return abs(record_duration - wanted) <= config.LYRICS_DURATION_TOLERANCE_S


def _title_matches(candidate: object, title: str | None) -> bool:
    if not isinstance(candidate, str):
        return False
    if not title:
        return True
    return _loose(candidate) == _loose(title)


def _artist_matches(candidate: object, artist: str) -> bool:
    if not isinstance(candidate, str):
        return False
    left, right = _loose(candidate), _loose(artist)
    if not left or not right:
        return True
    return left == right or right in left


def _loose(text: str) -> str:
    """Case- and accent-insensitive comparison key. `JAŸ-Z` must match `JAY-Z`."""
    folded = "".join(
        character
        for character in text.casefold()
        if character.isalnum() or character.isspace()
    )
    return " ".join(folded.split())


def _request_json(endpoint: str, params: dict[str, str]) -> Any:
    url = f"{config.LRCLIB_URL}/{endpoint}"
    try:
        response = client().get(url, params=params)
    except httpx.HTTPError as error:
        logger.info("LRCLIB %s failed: %s", endpoint, error)
        return None
    if response.status_code == 404:
        logger.debug("LRCLIB %s: not found", endpoint)
        return None
    if response.status_code != 200:
        logger.info("LRCLIB %s returned HTTP %d", endpoint, response.status_code)
        return None
    try:
        return response.json()
    except ValueError:
        logger.info("LRCLIB %s returned a body that is not JSON", endpoint)
        return None


def _to_record(payload: dict[str, Any]) -> LyricsRecord | None:
    track_id = payload.get("id")
    if not isinstance(track_id, int):
        logger.debug("provider payload has no integer id")
        return None
    duration = payload.get("duration")
    return LyricsRecord(
        provider="lrclib",
        track_id=track_id,
        title=_text(payload.get("trackName")),
        artist=_text(payload.get("artistName")),
        album=_text(payload.get("albumName")),
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        instrumental=bool(payload.get("instrumental")),
        has_word_sync=bool(payload.get("hasWordSync")),
        synced_lyrics=_text(payload.get("syncedLyrics")),
        plain_lyrics=_text(payload.get("plainLyrics")),
        raw=payload,
    )


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _cache_path(endpoint: str, artist: str, title: str) -> Path:
    key = f"{_CACHE_VERSION}\x1f{endpoint}\x1f{artist}\x1f{title}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return config.LYRICS_CACHE_DIR / f"{digest}.json"


def _read_cache(path: Path) -> LyricsRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return _to_record(payload)


def _write_cache(path: Path, record: LyricsRecord) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record.raw), encoding="utf-8")
    except OSError as error:
        logger.info("could not write the lyrics cache (%s)", error)


def client() -> httpx.Client:
    """One lazily-opened client, reused across the lookups of a single job."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(
            headers={"User-Agent": config.HTTP_USER_AGENT},
            timeout=config.LYRICS_TIMEOUT_S,
            follow_redirects=True,
        )
    return _CLIENT


_CLIENT: httpx.Client | None = None