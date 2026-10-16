"""Pick the YouTube result that best matches a known track.

`ytsearch1:"Artist - Track"` often returns the music video or a live take
instead of the album version. When the expected duration is known (Spotify
API, Exportify CSV), we fetch a few candidates and choose the one whose
length matches, so downloads line up with the release they are tagged as.
"""

import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from utils.logger import log_info, log_warning
from utils.ytdlp_args import build_extra_ytdlp_args


DEFAULT_CANDIDATES = 5
DURATION_TOLERANCE_SEC = 10
# Length differences below this are noise (rounding, a second of silence), so
# the artist's own upload wins over a closer re-upload.
NEAR_EQUAL_SEC = 2

# Titles with these words are a different rendition of the song; they are only
# accepted when the expected track title contains the same word.
_VARIANT_WORDS = re.compile(
    r"\b(live|cover|remix|karaoke|instrumental|sped up|slowed|nightcore|8d|reverb)\b",
    re.IGNORECASE,
)

_EDITION_WORDS = r"(edition|deluxe|remaster(?:ed)?|expanded|anniversary|bonus|version)"
_EDITION_BRACKETS = re.compile(rf"\s*[\(\[][^\)\]]*\b{_EDITION_WORDS}\b[^\)\]]*[\)\]]", re.IGNORECASE)
_EDITION_SUFFIX = re.compile(rf"\s+-\s+[^-]*\b{_EDITION_WORDS}\b.*$", re.IGNORECASE)


def _to_seconds(duration_ms: Any) -> Optional[float]:
    try:
        seconds = float(duration_ms) / 1000.0
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _variant_words(text: str) -> set:
    return {m.lower() for m in _VARIANT_WORDS.findall(text or "")}


def _is_artist_channel(cand: Dict[str, Any], artist: str) -> bool:
    channel = str(cand.get("channel") or cand.get("uploader") or "").strip().casefold()
    if not channel:
        return False
    names = [a.strip().casefold() for a in (artist or "").split(",") if a.strip()]
    return any(channel in (name, f"{name} - topic") for name in names)


def pick_best(
    candidates: List[Dict[str, Any]], duration_ms: Any, title: str, artist: str = ""
) -> Optional[Dict[str, Any]]:
    """Return the candidate closest to duration_ms, or None if none qualifies.

    Candidates must be within DURATION_TOLERANCE_SEC and must not be a variant
    (live, remix, ...) unless `title` asks for it. Lengths within
    NEAR_EQUAL_SEC count as equal; then the artist's channel wins, then rank.
    """
    expected = _to_seconds(duration_ms)
    if expected is None:
        return None

    wanted_variants = _variant_words(title)
    best = None
    best_key = None
    for rank, cand in enumerate(candidates):
        try:
            diff = abs(float(cand.get("duration")) - expected)
        except (TypeError, ValueError):
            continue
        if diff > DURATION_TOLERANCE_SEC:
            continue
        if _variant_words(cand.get("title", "")) - wanted_variants:
            continue
        key = (max(diff, NEAR_EQUAL_SEC), not _is_artist_channel(cand, artist), rank)
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return best


def strip_edition(album: str) -> str:
    """Drop edition noise ("(Special Edition)", "- 2004 Remaster") from an album name."""
    stripped = _EDITION_SUFFIX.sub("", _EDITION_BRACKETS.sub("", album or "")).strip()
    return stripped or (album or "").strip()


def _search(query: str, count: int, config: dict) -> List[Dict[str, Any]]:
    cmd = [
        "yt-dlp",
        f"ytsearch{count}:{query}",
        "--flat-playlist",
        "-J",
        "--no-warnings",
    ]
    cmd.extend(build_extra_ytdlp_args(config))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if proc.returncode != 0:
            log_warning(f"YouTube candidate search failed for {query}: {(proc.stderr or '').strip()}")
            return []
        entries = (json.loads(proc.stdout or "{}") or {}).get("entries") or []
    except Exception as e:
        log_warning(f"YouTube candidate search failed for {query}: {e}")
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("id")]


def resolve_target(artist: str, track: str, track_data: Optional[Dict[str, Any]], config: Optional[dict]) -> str:
    """Return what to pass to yt-dlp for this track: a video URL or a ytsearch1 query.

    Falls back to today's `ytsearch1:"Artist - Track"` when the duration is
    unknown, matching is disabled (youtube_search_candidates <= 1), or no
    candidate matches in either the plain or the album-qualified search.
    """
    config = config or {}
    track_data = track_data or {}
    query = f"{artist} - {track}"
    fallback = f"ytsearch1:{query}"

    try:
        count = int(config.get("youtube_search_candidates", DEFAULT_CANDIDATES))
    except (TypeError, ValueError):
        count = DEFAULT_CANDIDATES
    duration_ms = track_data.get("duration_ms")
    if count <= 1 or _to_seconds(duration_ms) is None:
        return fallback

    queries = [query]
    # The album name pulls in other songs from the album, so it is only a
    # second try for when the plain search has no length match.
    album = strip_edition(str(track_data.get("album") or ""))
    if album:
        queries.append(f"{query} {album}")

    for q in queries:
        best = pick_best(_search(q, count, config), duration_ms, track, artist)
        if best:
            log_info(f"Matched {query} to YouTube {best['id']} ({best.get('duration')}s): {best.get('title')}")
            return f"https://www.youtube.com/watch?v={best['id']}"

    log_info(f"No length match for {query}; using top search result")
    return fallback
