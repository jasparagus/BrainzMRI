"""
Enhanced Enrichment implementation for BrainzMRI.

This module implements:
- Multi-entity enrichment (track / album / artist)
- Multi-provider enrichment (MusicBrainz + Last.fm)
- Provider priority (MusicBrainz → Last.fm)
- Global cache for enriched genres
- Canonicalization and noise filtering
- Depth-based enrichment based on report type
- Cache-only mode and force cache update behavior

It is designed to work with:
- GUI: enrichment modes and Force Cache Update checkbox
- ReportEngine: passes report_type, enrichment_mode, force_cache_update
"""

import json
import os
import time
import unicodedata
from typing import Dict, Any, List, Set, Tuple

import urllib.parse
import urllib.request

import pandas as pd

from user import get_cache_root


# ------------------------------------------------------------
# Constants and modes
# ------------------------------------------------------------

ENRICHMENT_MODE_CACHE_ONLY = "Cache Only"
ENRICHMENT_MODE_MB = "Query MusicBrainz"
ENRICHMENT_MODE_LASTFM = "Query Last.fm"
ENRICHMENT_MODE_ALL = "Query All Sources (Slow)"

# Simple rate limiting between network calls (seconds)
NETWORK_DELAY_SECONDS = 1.0

# Last.fm API endpoint and API key placeholder
LASTFM_API_ROOT = "https://ws.audioscrobbler.com/2.0/"
# NOTE: This is a placeholder. The user must configure a real API key.
LASTFM_API_KEY = os.environ.get("BRAINZMRI_LASTFM_API_KEY", "")


# ------------------------------------------------------------
# Global cache paths and helpers
# ------------------------------------------------------------

def _get_global_dir() -> str:
    cache_root = get_cache_root()
    global_dir = os.path.join(cache_root, "global")
    os.makedirs(global_dir, exist_ok=True)
    return global_dir


def _get_enrichment_cache_path(entity_type: str) -> str:
    """
    Return the path to the enrichment cache file for a given entity type.

    entity_type: "track", "album", or "artist"
    """
    global_dir = _get_global_dir()
    if entity_type == "track":
        filename = "track_enrichment.json"
    elif entity_type == "album":
        filename = "album_enrichment.json"
    elif entity_type == "artist":
        filename = "artist_enrichment.json"
    else:
        raise ValueError(f"Unknown entity_type for enrichment cache: {entity_type}")
    return os.path.join(global_dir, filename)


def _get_noise_tags_path() -> str:
    """
    Return the path to the noise tags configuration file.
    """
    global_dir = _get_global_dir()
    return os.path.join(global_dir, "genres_excluded.json")


def _load_json_dict(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        # If it's not a dict, treat as invalid and reset
        return {}
    except Exception:
        return {}


def _save_json_dict(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------
# Noise tags and canonicalization
# ------------------------------------------------------------

def _load_noise_tags() -> Set[str]:
    """
    Load tags that should be excluded after canonicalization.
    """
    path = _get_noise_tags_path()
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {str(x).strip().lower() for x in data}
        return set()
    except Exception:
        return set()


def _canonicalize_tag(tag: str) -> str:
    """
    Canonicalize a single tag:
    - lowercase
    - unicode normalize and strip accents
    - strip leading/trailing whitespace
    - normalize punctuation (convert non-alnum runs to single space)
    """
    if not tag:
        return ""

    # Lowercase
    t = tag.lower()

    # Unicode normalize and strip accents
    t = unicodedata.normalize("NFD", t)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")

    # Strip whitespace
    t = t.strip()

    # Replace any sequence of non-alphanumeric characters with a single space
    cleaned_chars = []
    prev_was_sep = False
    for ch in t:
        if ch.isalnum():
            cleaned_chars.append(ch)
            prev_was_sep = False
        else:
            if not prev_was_sep:
                cleaned_chars.append(" ")
                prev_was_sep = True
    t = "".join(cleaned_chars).strip()

    return t


def canonicalize_and_filter_tags(raw_tags: List[str], noise_tags: Set[str]) -> List[str]:
    """
    Canonicalize and filter a list of raw tags from providers.
    """
    canon: Set[str] = set()

    for tag in raw_tags:
        c = _canonicalize_tag(tag)
        if not c:
            continue
        if c in noise_tags:
            continue
        canon.add(c)

    return sorted(canon)


# ------------------------------------------------------------
# Enrichment cache structures
# ------------------------------------------------------------

def _load_entity_cache(entity_type: str) -> Dict[str, Any]:
    """
    Load enrichment cache for a given entity type.

    Format:
    {
        "<mbid>": {
            "genres": [...],
            "sources": {
                "musicbrainz": bool,
                "lastfm": bool
            }
        },
        ...
    }
    """
    path = _get_enrichment_cache_path(entity_type)
    return _load_json_dict(path)


def _save_entity_cache(entity_type: str, data: Dict[str, Any]) -> None:
    path = _get_enrichment_cache_path(entity_type)
    _save_json_dict(path, data)


def _get_entity_entry(
    cache: Dict[str, Any],
    mbid: str,
) -> Dict[str, Any]:
    """
    Get or create an entry for a given MBID in the cache.
    """
    entry = cache.get(mbid)
    if entry is None:
        entry = {
            "genres": [],
            "sources": {
                "musicbrainz": False,
                "lastfm": False,
            },
        }
        cache[mbid] = entry
    else:
        # normalize entry to ensure keys exist
        entry.setdefault("genres", [])
        entry.setdefault("sources", {})
        entry["sources"].setdefault("musicbrainz", False)
        entry["sources"].setdefault("lastfm", False)
    return entry


def _update_entity_entry(
    entry: Dict[str, Any],
    new_genres: List[str],
    provider_name: str,
) -> None:
    """
    Merge new genres into an existing entry and mark provider as used.
    """
    existing: Set[str] = set(entry.get("genres") or [])
    for g in new_genres:
        existing.add(g)
    entry["genres"] = sorted(existing)

    sources = entry.get("sources") or {}
    sources[provider_name] = True
    entry["sources"] = sources


def _maybe_clear_entry_for_force_update(
    cache: Dict[str, Any],
    mbid: str,
    force_cache_update: bool,
) -> None:
    """
    If force_cache_update is True, remove the entry for this MBID from cache.
    """
    if force_cache_update and mbid in cache:
        del cache[mbid]


# ------------------------------------------------------------
# Provider: MusicBrainz
# ------------------------------------------------------------

def _mb_request(path: str, params: Dict[str, str]) -> Dict[str, Any]:
    """
    Helper to call MusicBrainz JSON API with query params.
    """
    base = "https://musicbrainz.org/ws/2/"
    query = urllib.parse.urlencode(params)
    url = f"{base}{path}?{query}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "BrainzMRI/1.0 (https://example.org)",  # TODO: customize UA if desired
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _mb_tags_to_list(tags_field: Any) -> List[str]:
    """
    Convert MusicBrainz 'tags' or 'genres' field to list of names.
    """
    if not tags_field:
        return []
    out = []
    for item in tags_field:
        name = item.get("name")
        if name:
            out.append(name)
    return out


def mb_enrich_recording(recording_mbid: str) -> List[str]:
    """
    Fetch tags/genres for a recording (track) from MusicBrainz.
    """
    if not recording_mbid:
        return []

    try:
        data = _mb_request(
            f"recording/{recording_mbid}",
            {"fmt": "json", "inc": "tags+genres"},
        )
        tags = _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
        return tags
    except Exception:
        return []


def mb_enrich_release(release_mbid: str) -> List[str]:
    """
    Fetch tags/genres for a release (album) from MusicBrainz.
    """
    if not release_mbid:
        return []

    try:
        data = _mb_request(
            f"release/{release_mbid}",
            {"fmt": "json", "inc": "tags+genres"},
        )
        tags = _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
        return tags
    except Exception:
        return []


def mb_enrich_artist(artist_mbid: str) -> List[str]:
    """
    Fetch tags/genres for an artist from MusicBrainz.
    """
    if not artist_mbid:
        return []

    try:
        data = _mb_request(
            f"artist/{artist_mbid}",
            {"fmt": "json", "inc": "tags+genres"},
        )
        tags = _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
        return tags
    except Exception:
        return []


# ------------------------------------------------------------
# Provider: Last.fm
# ------------------------------------------------------------

def _lastfm_request(params: Dict[str, str]) -> Dict[str, Any]:
    """
    Helper to call Last.fm JSON API.
    """
    if not LASTFM_API_KEY:
        # No API key configured → no data
        return {}

    params = params.copy()
    params["api_key"] = LASTFM_API_KEY
    params["format"] = "json"

    query = urllib.parse.urlencode(params)
    url = f"{LASTFM_API_ROOT}?{query}"

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _lastfm_tags_from_track(data: Dict[str, Any]) -> List[str]:
    toplevel = data.get("track") or {}
    tags_block = toplevel.get("toptags") or {}
    tags_list = tags_block.get("tag") or []
    out = []
    if isinstance(tags_list, dict):
        tags_list = [tags_list]
    for t in tags_list:
        name = t.get("name")
        if name:
            out.append(name)
    return out


def _lastfm_tags_from_album(data: Dict[str, Any]) -> List[str]:
    toplevel = data.get("album") or {}
    tags_block = toplevel.get("toptags") or {}
    tags_list = tags_block.get("tag") or []
    out = []
    if isinstance(tags_list, dict):
        tags_list = [tags_list]
    for t in tags_list:
        name = t.get("name")
        if name:
            out.append(name)
    return out


def _lastfm_tags_from_artist(data: Dict[str, Any]) -> List[str]:
    toplevel = data.get("artist") or {}
    tags_block = toplevel.get("tags") or {}
    tags_list = tags_block.get("tag") or []
    out = []
    if isinstance(tags_list, dict):
        tags_list = [tags_list]
    for t in tags_list:
        name = t.get("name")
        if name:
            out.append(name)
    return out


def lastfm_enrich_track(artist_name: str, track_name: str) -> List[str]:
    """
    Fetch tags for a track from Last.fm.
    """
    if not artist_name or not track_name:
        return []
    try:
        data = _lastfm_request(
            {
                "method": "track.getInfo",
                "artist": artist_name,
                "track": track_name,
            }
        )
        return _lastfm_tags_from_track(data)
    except Exception:
        return []


def lastfm_enrich_album(artist_name: str, album_name: str) -> List[str]:
    """
    Fetch tags for an album from Last.fm.
    """
    if not artist_name or not album_name:
        return []
    try:
        data = _lastfm_request(
            {
                "method": "album.getInfo",
                "artist": artist_name,
                "album": album_name,
            }
        )
        return _lastfm_tags_from_album(data)
    except Exception:
        return []


def lastfm_enrich_artist(artist_name: str) -> List[str]:
    """
    Fetch tags for an artist from Last.fm.
    """
    if not artist_name:
        return []
    try:
        data = _lastfm_request(
            {
                "method": "artist.getInfo",
                "artist": artist_name,
            }
        )
        return _lastfm_tags_from_artist(data)
    except Exception:
        return []


# ------------------------------------------------------------
# Entity extraction from report DataFrame
# ------------------------------------------------------------

def _collect_mbids_for_report(
    df: pd.DataFrame,
    report_type: str,
) -> Dict[str, Set[str]]:
    """
    Collect MBIDs (recording, release, artist) from the report DataFrame,
    depending on the report type.
    """
    recording_mbids: Set[str] = set()
    release_mbids: Set[str] = set()
    artist_mbids: Set[str] = set()

    if "recording_mbid" in df.columns:
        recording_mbids.update(
            str(x) for x in df["recording_mbid"].dropna().unique() if str(x)
        )

    if "release_mbid" in df.columns:
        release_mbids.update(
            str(x) for x in df["release_mbid"].dropna().unique() if str(x)
        )

    if "artist_mbid" in df.columns:
        artist_mbids.update(
            str(x) for x in df["artist_mbid"].dropna().unique() if str(x)
        )

    # Depth-based pruning based on report type
    if report_type == "track":
        # Use track + album + artist as available
        pass
    elif report_type == "album":
        # Album + artist only: track MBIDs not needed
        recording_mbids.clear()
    elif report_type == "artist":
        # Artist only: no recording or release MBIDs
        recording_mbids.clear()
        release_mbids.clear()
    else:
        # Other report types: default to no enrichment
        recording_mbids.clear()
        release_mbids.clear()
        artist_mbids.clear()

    return {
        "track": recording_mbids,
        "album": release_mbids,
        "artist": artist_mbids,
    }


# ------------------------------------------------------------
# Core enrichment orchestration per entity
# ------------------------------------------------------------

def _enrich_entity_mbid(
    entity_type: str,
    mbid: str,
    *,
    enrichment_mode: str,
    force_cache_update: bool,
    noise_tags: Set[str],
    df: pd.DataFrame,
) -> Tuple[str, List[str]]:
    """
    Enrich a single entity (track/album/artist) identified by MBID.

    Returns (mbid, canonical_genres_for_this_entity).
    """
    cache = _load_entity_cache(entity_type)

    # Respect force cache update
    _maybe_clear_entry_for_force_update(cache, mbid, force_cache_update)

    entry = cache.get(mbid)
    # If mode is Cache Only: just return whatever is cached
    if enrichment_mode == ENRICHMENT_MODE_CACHE_ONLY:
        if entry and entry.get("genres"):
            return mbid, entry.get("genres") or []
        else:
            # No genres in cache → empty list (no provider calls)
            return mbid, []

    # Otherwise, we may call providers
    entry = _get_entity_entry(cache, mbid)
    accumulated_tags: List[str] = []

    # Provider order for "All Sources" is MusicBrainz → Last.fm
    modes_to_call: List[str] = []
    if enrichment_mode == ENRICHMENT_MODE_MB:
        modes_to_call = ["musicbrainz"]
    elif enrichment_mode == ENRICHMENT_MODE_LASTFM:
        modes_to_call = ["lastfm"]
    elif enrichment_mode == ENRICHMENT_MODE_ALL:
        modes_to_call = ["musicbrainz", "lastfm"]

    # Decide provider calls based on entity type
    for provider in modes_to_call:
        provider_tags: List[str] = []

        if provider == "musicbrainz":
            if entity_type == "track":
                provider_tags = mb_enrich_recording(mbid)
            elif entity_type == "album":
                provider_tags = mb_enrich_release(mbid)
            elif entity_type == "artist":
                provider_tags = mb_enrich_artist(mbid)
        elif provider == "lastfm":
            # Last.fm requires names, not MBIDs; use df as lookup
            if entity_type == "track":
                subset = df[df["recording_mbid"] == mbid]
            elif entity_type == "album":
                subset = df[df["release_mbid"] == mbid]
            elif entity_type == "artist":
                subset = df[df["artist_mbid"] == mbid]
            else:
                subset = df.iloc[0:0]


            if entity_type == "track":
                # Need artist + track_name
                artist_name = None
                track_name = None
                if not subset.empty:
                    artist_name = subset["artist"].iloc[0] if "artist" in subset.columns else None
                    track_name = subset["track_name"].iloc[0] if "track_name" in subset.columns else None
                provider_tags = lastfm_enrich_track(artist_name, track_name)
            elif entity_type == "album":
                # Need artist + album name
                artist_name = None
                album_name = None
                if not subset.empty:
                    artist_name = subset["artist"].iloc[0] if "artist" in subset.columns else None
                    album_name = subset["album"].iloc[0] if "album" in subset.columns else None
                provider_tags = lastfm_enrich_album(artist_name, album_name)
            elif entity_type == "artist":
                # Need artist name
                artist_name = None
                if not subset.empty:
                    artist_name = subset["artist"].iloc[0] if "artist" in subset.columns else None
                provider_tags = lastfm_enrich_artist(artist_name)

        if provider_tags:
            accumulated_tags.extend(provider_tags)

        # Rate limiting between provider calls
        if provider_tags:
            time.sleep(NETWORK_DELAY_SECONDS)

    if not accumulated_tags and entry.get("genres"):
        # No new tags from providers; keep existing
        canonical_genres = entry.get("genres") or []
    else:
        # Canonicalize and merge with existing
        canonical_new = canonicalize_and_filter_tags(accumulated_tags, noise_tags)
        existing = entry.get("genres") or []
        merged = set(existing) | set(canonical_new)
        canonical_genres = sorted(merged)

    # Update cache entry if we have any canonical genres
    if canonical_genres:
        for provider in ["musicbrainz", "lastfm"]:
            entry["sources"].setdefault(provider, False)
        # Mark providers we actually used
        if enrichment_mode in (ENRICHMENT_MODE_MB, ENRICHMENT_MODE_ALL):
            entry["sources"]["musicbrainz"] = True
        if enrichment_mode in (ENRICHMENT_MODE_LASTFM, ENRICHMENT_MODE_ALL):
            entry["sources"]["lastfm"] = True

        entry["genres"] = canonical_genres
        cache[mbid] = entry
        _save_entity_cache(entity_type, cache)

    return mbid, canonical_genres


def _enrich_all_entities_for_type(
    entity_type: str,
    mbids: Set[str],
    *,
    enrichment_mode: str,
    force_cache_update: bool,
    noise_tags: Set[str],
    df: pd.DataFrame,
) -> Dict[str, List[str]]:
    """
    Enrich all MBIDs for a given entity type.
    Returns mapping: mbid -> genres.
    """
    result: Dict[str, List[str]] = {}
        
    if not mbids:
        return result

    for mbid in mbids:
        mbid_str = str(mbid)
        _, genres = _enrich_entity_mbid(
            entity_type,
            mbid_str,
            enrichment_mode=enrichment_mode,
            force_cache_update=force_cache_update,
            noise_tags=noise_tags,
            df=df,
        )
        result[mbid_str] = genres

    return result


# ------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------

def enrich_report(
    df: pd.DataFrame,
    report_type: str,
    enrichment_mode: str,
    *,
    force_cache_update: bool = False,
):
    """
    Main entry point for Enhanced Enrichment.

    Parameters
    ----------
    df : DataFrame
        Report DataFrame.
    report_type : str
        Report type key ("artist", "album", "track", etc.).
    enrichment_mode : str
        One of:
            - "Cache Only"
            - "Query MusicBrainz"
            - "Query Last.fm"
            - "Query All Sources (Slow)"
    force_cache_update : bool
        If True, existing entries for the relevant MBIDs will be cleared and recomputed.

    Returns
    -------
    DataFrame
        Report DataFrame with additional genre columns where applicable.
    """
    
    # If there's no artist column, we can't enrich meaningfully
    if ("artist" not in df.columns
            and "artist_mbid" not in df.columns
            and "recording_mbid" not in df.columns
            and "release_mbid" not in df.columns):
        return df

    # Drop helper column injected by ReportEngine, if present
    if "_username" in df.columns:
        df = df.drop(columns=["_username"])

    # Collect MBIDs based on report type
    mbids_by_type = _collect_mbids_for_report(df, report_type)

    # If nothing to enrich, return df unchanged
    if not any(mbids_by_type.values()):
        return df

    # Load noise tags
    noise_tags = _load_noise_tags()

    # Compute enrichment per entity type
    track_genres_map = _enrich_all_entities_for_type(
        "track",
        mbids_by_type["track"],
        enrichment_mode=enrichment_mode,
        force_cache_update=force_cache_update,
        noise_tags=noise_tags,
        df=df,
    )

    album_genres_map = _enrich_all_entities_for_type(
        "album",
        mbids_by_type["album"],
        enrichment_mode=enrichment_mode,
        force_cache_update=force_cache_update,
        noise_tags=noise_tags,
        df=df,
    )

    artist_genres_map = _enrich_all_entities_for_type(
        "artist",
        mbids_by_type["artist"],
        enrichment_mode=enrichment_mode,
        force_cache_update=force_cache_update,
        noise_tags=noise_tags,
        df=df,
    )

    # Join genres back into the DataFrame
    enriched_df = df.copy()

    if "recording_mbid" in enriched_df.columns and track_genres_map:
        enriched_df["track_genres"] = enriched_df["recording_mbid"].map(
            lambda m: "|".join(track_genres_map.get(str(m), [])) if pd.notna(m) else ""
        )

    if "release_mbid" in enriched_df.columns and album_genres_map:
        enriched_df["album_genres"] = enriched_df["release_mbid"].map(
            lambda m: "|".join(album_genres_map.get(str(m), [])) if pd.notna(m) else ""
        )

    if "artist_mbid" in enriched_df.columns and artist_genres_map:
        enriched_df["artist_genres"] = enriched_df["artist_mbid"].map(
            lambda m: "|".join(artist_genres_map.get(str(m), [])) if pd.notna(m) else ""
        )

    return enriched_df
