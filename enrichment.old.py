"""
Enhanced Enrichment implementation for BrainzMRI.

This module is responsible for fetching, caching, and applying metadata (specifically genres)
to the reporting DataFrames. It supports multiple providers (MusicBrainz, Last.fm),
robust name-based fallbacks, and threading-friendly progress reporting.
"""

import json
import os
import time
import unicodedata
from typing import Dict, Any, List, Set, Tuple, Optional, Callable

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
LASTFM_API_KEY = os.environ.get("BRAINZMRI_LASTFM_API_KEY", "")


# ------------------------------------------------------------
# Global cache paths and helpers
# ------------------------------------------------------------

def _get_global_dir() -> str:
    """Return the path to the global cache directory."""
    cache_root = get_cache_root()
    global_dir = os.path.join(cache_root, "global")
    os.makedirs(global_dir, exist_ok=True)
    return global_dir


def _get_enrichment_cache_path(entity_type: str) -> str:
    """Return the path to the enrichment cache file for a given entity type."""
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
    """Return the path to the noise tags configuration file."""
    global_dir = _get_global_dir()
    return os.path.join(global_dir, "genres_excluded.json")


def _load_json_dict(path: str) -> Dict[str, Any]:
    """Safely load a JSON file into a dictionary."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _save_json_dict(path: str, data: Dict[str, Any]) -> None:
    """Safely save a dictionary to a JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------
# Noise tags and canonicalization
# ------------------------------------------------------------

def _load_noise_tags() -> Set[str]:
    """Load the set of tags that should be excluded (noise)."""
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
    """Canonicalize a single tag string."""
    if not tag:
        return ""
    t = tag.lower()
    t = unicodedata.normalize("NFD", t)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = t.strip()
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
    """Process a list of raw tags: canonicalize them and remove noise tags."""
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
    """Load the enrichment cache for the specified entity type."""
    path = _get_enrichment_cache_path(entity_type)
    return _load_json_dict(path)


def _save_entity_cache(entity_type: str, data: Dict[str, Any]) -> None:
    """Save the enrichment cache for the specified entity type."""
    path = _get_enrichment_cache_path(entity_type)
    _save_json_dict(path, data)


def _get_entity_entry(cache: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Retrieve or initialize a cache entry for a given key."""
    entry = cache.get(key)
    if entry is None:
        entry = {
            "genres": [],
            "sources": {"musicbrainz": False, "lastfm": False},
        }
        cache[key] = entry
    else:
        entry.setdefault("genres", [])
        entry.setdefault("sources", {})
        entry["sources"].setdefault("musicbrainz", False)
        entry["sources"].setdefault("lastfm", False)
    return entry


# ------------------------------------------------------------
# Provider Logic (Consolidated)
# ------------------------------------------------------------

def _mb_request(path: str, params: Dict[str, str]) -> Dict[str, Any]:
    """Execute a request against the MusicBrainz API."""
    base = "https://musicbrainz.org/ws/2/"
    query = urllib.parse.urlencode(params)
    url = f"{base}{path}?{query}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BrainzMRI/1.0 (https://example.org)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)

def _mb_tags_to_list(tags_field: Any) -> List[str]:
    """Extract tag names from a MusicBrainz tag list response."""
    if not tags_field: return []
    return [item.get("name") for item in tags_field if item.get("name")]

def _mb_fetch_tags(endpoint: str, mbid: str) -> List[str]:
    """Generic helper to fetch tags/genres for any MBID entity type."""
    if not mbid: return []
    try:
        data = _mb_request(f"{endpoint}/{mbid}", {"fmt": "json", "inc": "tags+genres"})
        return _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
    except Exception:
        return []

def mb_enrich_recording(mbid: str) -> List[str]: return _mb_fetch_tags("recording", mbid)
def mb_enrich_release(mbid: str) -> List[str]: return _mb_fetch_tags("release", mbid)
def mb_enrich_artist(mbid: str) -> List[str]: return _mb_fetch_tags("artist", mbid)

# --- MB Search Fallbacks ---

def _mb_search_and_extract(endpoint: str, query: str, list_key: str) -> List[str]:
    """Generic helper to search MB and return tags from the top result."""
    try:
        data = _mb_request(endpoint, {"query": query, "fmt": "json", "limit": "1"})
        results = data.get(list_key, [])
        if results:
            return _mb_tags_to_list(results[0].get("tags"))
        return []
    except Exception:
        return []

def mb_search_artist(artist_name: str) -> List[str]:
    if not artist_name: return []
    return _mb_search_and_extract("artist", f'artist:"{artist_name}"', "artists")

def mb_search_release(artist_name: str, release_name: str) -> List[str]:
    if not artist_name or not release_name: return []
    q = f'release:"{release_name}" AND artist:"{artist_name}"'
    return _mb_search_and_extract("release", q, "releases")

def mb_search_recording(artist_name: str, track_name: str) -> List[str]:
    if not artist_name or not track_name: return []
    q = f'recording:"{track_name}" AND artist:"{artist_name}"'
    return _mb_search_and_extract("recording", q, "recordings")


# --- Last.fm Logic ---

def _lastfm_request(params: Dict[str, str]) -> Dict[str, Any]:
    """Execute a request against the Last.fm API."""
    if not LASTFM_API_KEY: return {}
    params = params.copy()
    params["api_key"] = LASTFM_API_KEY
    params["format"] = "json"
    query = urllib.parse.urlencode(params)
    url = f"{LASTFM_API_ROOT}?{query}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)

def _lastfm_extract_tags(data: Dict[str, Any], toplevel_key: str) -> List[str]:
    """Extract tags from Last.fm response."""
    toplevel = data.get(toplevel_key) or {}
    tags_block = toplevel.get("toptags") or toplevel.get("tags") or {}
    tags_list = tags_block.get("tag") or []
    if isinstance(tags_list, dict): tags_list = [tags_list]
    return [t.get("name") for t in tags_list if t.get("name")]

def _lastfm_fetch_tags(method: str, root_key: str, **kwargs) -> List[str]:
    """Generic helper for Last.fm tag fetching."""
    try:
        params = {"method": method, **kwargs}
        data = _lastfm_request(params)
        return _lastfm_extract_tags(data, root_key)
    except Exception:
        return []

def lastfm_enrich_track(artist: str, track: str) -> List[str]:
    if not artist or not track: return []
    return _lastfm_fetch_tags("track.getInfo", "track", artist=artist, track=track)

def lastfm_enrich_album(artist: str, album: str) -> List[str]:
    if not artist or not album: return []
    return _lastfm_fetch_tags("album.getInfo", "album", artist=artist, album=album)

def lastfm_enrich_artist(artist: str) -> List[str]:
    if not artist: return []
    return _lastfm_fetch_tags("artist.getInfo", "artist", artist=artist)


# ------------------------------------------------------------
# Entity Enrichment Orchestration
# ------------------------------------------------------------

class EnrichmentStats:
    """Helper class to track enrichment performance metrics."""
    def __init__(self):
        self.processed = 0
        self.cache_hits = 0
        self.newly_fetched = 0  # Replaces raw lookups
        self.empty = 0          # Entities with no tags found
        self.fallbacks = 0      # Subset of fetched that required name search
    
    def to_dict(self):
        return self.__dict__.copy()


def _enrich_single_entity(
    entity_type: str,
    mbid: Optional[str],
    name_info: Dict[str, str],
    cache: Dict[str, Any],
    enrichment_mode: str,
    noise_tags: Set[str],
    stats: EnrichmentStats,
    force_update: bool = False
) -> Tuple[str, List[str]]:
    """
    Enrich a single entity.
    Returns (key, genres). Key is MBID (if available) or Name Key.
    """
    
    key = mbid
    if not key:
        # Fallback key construction
        parts = []
        if name_info.get("artist"): parts.append(name_info["artist"])
        if entity_type == "album" and name_info.get("album"): parts.append(name_info["album"])
        if entity_type == "track" and name_info.get("track"): parts.append(name_info["track"])
        key = "|".join(parts)
    
    # 1. Handle Missing Key (Truly Empty)
    if not key: 
        stats.processed += 1
        stats.empty += 1
        return "", []

    # 2. Entry Retrieval
    entry = cache.get(key)
    
    # Apply Force Update: pretend we didn't find it
    if force_update:
        entry = None

    # Check Cache
    if enrichment_mode == ENRICHMENT_MODE_CACHE_ONLY:
        stats.processed += 1
        if entry and entry.get("genres"):
            stats.cache_hits += 1
            return key, entry.get("genres")
        else:
            stats.empty += 1
            return key, []

    if entry and entry.get("genres"):
        stats.processed += 1
        stats.cache_hits += 1
        return key, entry.get("genres")

    # 3. Do Lookup
    stats.processed += 1
    accumulated_tags: List[str] = []
    
    # MusicBrainz
    if enrichment_mode in (ENRICHMENT_MODE_MB, ENRICHMENT_MODE_ALL):
        tags = []
        if mbid:
            if entity_type == "track": tags = mb_enrich_recording(mbid)
            elif entity_type == "album": tags = mb_enrich_release(mbid)
            elif entity_type == "artist": tags = mb_enrich_artist(mbid)
        
        # Fallback
        if not tags and not mbid:
            stats.fallbacks += 1
            if entity_type == "track": 
                tags = mb_search_recording(name_info.get("artist"), name_info.get("track"))
            elif entity_type == "album": 
                tags = mb_search_release(name_info.get("artist"), name_info.get("album"))
            elif entity_type == "artist": 
                tags = mb_search_artist(name_info.get("artist"))
            
        if tags:
            accumulated_tags.extend(tags)
            time.sleep(NETWORK_DELAY_SECONDS)

    # Last.fm
    if enrichment_mode in (ENRICHMENT_MODE_LASTFM, ENRICHMENT_MODE_ALL):
        tags = []
        if entity_type == "track":
            tags = lastfm_enrich_track(name_info.get("artist"), name_info.get("track"))
        elif entity_type == "album":
            tags = lastfm_enrich_album(name_info.get("artist"), name_info.get("album"))
        elif entity_type == "artist":
            tags = lastfm_enrich_artist(name_info.get("artist"))
        
        if tags:
            accumulated_tags.extend(tags)
            time.sleep(NETWORK_DELAY_SECONDS)

    # 4. Finalize
    # Re-retrieve entry from cache to handle the edge case where:
    # force_update=True (so local entry=None), but network failed.
    # In that case, we want to fall back to the old cache data if it exists.
    
    entry = _get_entity_entry(cache, key)
    
    if not accumulated_tags and entry.get("genres"):
        # Network failed, but we have old data. Count as cache hit (rescue).
        canonical_genres = entry.get("genres")
        stats.cache_hits += 1
    else:
        # Standard processing
        canonical_new = canonicalize_and_filter_tags(accumulated_tags, noise_tags)
        existing = entry.get("genres") or []
        merged = set(existing) | set(canonical_new)
        canonical_genres = sorted(merged)

        if canonical_new:
            stats.newly_fetched += 1
        else:
            # We looked, found nothing new.
            if not existing:
                stats.empty += 1
            else:
                # We had existing data and found nothing new.
                stats.cache_hits += 1

    # Update cache
    if canonical_genres:
        entry["genres"] = canonical_genres
        if enrichment_mode in (ENRICHMENT_MODE_MB, ENRICHMENT_MODE_ALL):
            entry["sources"]["musicbrainz"] = True
        if enrichment_mode in (ENRICHMENT_MODE_LASTFM, ENRICHMENT_MODE_ALL):
            entry["sources"]["lastfm"] = True
        
        cache[key] = entry
        _save_entity_cache(entity_type, cache)

    return key, canonical_genres


def enrich_report(
    df: pd.DataFrame,
    report_type: str,
    enrichment_mode: str,
    *,
    force_cache_update: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Main entry point for report enrichment.
    """
    stats = {
        "track": EnrichmentStats(),
        "album": EnrichmentStats(),
        "artist": EnrichmentStats()
    }

    if df.empty:
        return df, {}

    if "_username" in df.columns:
        df = df.drop(columns=["_username"])

    noise_tags = _load_noise_tags()
    
    # Pre-calculate unique entities to process
    unique_tracks = pd.DataFrame()
    unique_albums = pd.DataFrame()
    unique_artists = pd.DataFrame()
    
    do_tracks = False
    do_albums = False
    do_artists = False

    if "recording_mbid" in df.columns or ("track_name" in df.columns and "artist" in df.columns):
        if report_type == "track":
            do_tracks = True
            track_cols = ["artist", "track_name"]
            if "recording_mbid" in df.columns: track_cols.append("recording_mbid")
            unique_tracks = df[track_cols].drop_duplicates()

    if "release_mbid" in df.columns or ("album" in df.columns and "artist" in df.columns):
        if report_type in ("album", "track"):
            do_albums = True
            album_cols = ["artist", "album"]
            if "release_mbid" in df.columns: album_cols.append("release_mbid")
            unique_albums = df[album_cols].drop_duplicates()
            unique_albums = unique_albums[unique_albums["album"] != "Unknown"]

    if "artist" in df.columns:
        do_artists = True
        artist_cols = ["artist"]
        if "artist_mbid" in df.columns: artist_cols.append("artist_mbid")
        unique_artists = df[artist_cols].drop_duplicates()

    total_items = 0
    if do_tracks: total_items += len(unique_tracks)
    if do_albums: total_items += len(unique_albums)
    if do_artists: total_items += len(unique_artists)
    
    current_item = 0
    
    # Maps for results
    track_map, album_map, artist_map = {}, {}, {}

    def check_cancel():
        return is_cancelled() if is_cancelled else False

    # 1. Enrich Tracks
    if do_tracks:
        cache = _load_entity_cache("track")
        for _, row in unique_tracks.iterrows():
            if check_cancel(): break
            
            mbid = str(row["recording_mbid"]) if "recording_mbid" in row and pd.notna(row["recording_mbid"]) else None
            name_info = {
                "artist": row["artist"] if "artist" in row else "",
                "track": row["track_name"] if "track_name" in row else ""
            }
            # PASSING FORCE_UPDATE HERE
            k, g = _enrich_single_entity("track", mbid, name_info, cache, enrichment_mode, noise_tags, stats["track"], force_update=force_cache_update)
            if mbid: track_map[mbid] = g
            
            current_item += 1
            if progress_callback:
                progress_callback(current_item, total_items, f"Enriching Tracks ({current_item}/{total_items})...")

    # 2. Enrich Albums
    if do_albums and not check_cancel():
        cache = _load_entity_cache("album")
        for _, row in unique_albums.iterrows():
            if check_cancel(): break

            mbid = str(row["release_mbid"]) if "release_mbid" in row and pd.notna(row["release_mbid"]) else None
            name_info = {
                "artist": row["artist"] if "artist" in row else "",
                "album": row["album"] if "album" in row else ""
            }
            # PASSING FORCE_UPDATE HERE
            k, g = _enrich_single_entity("album", mbid, name_info, cache, enrichment_mode, noise_tags, stats["album"], force_update=force_cache_update)
            if mbid: album_map[mbid] = g
            
            current_item += 1
            if progress_callback:
                progress_callback(current_item, total_items, f"Enriching Albums ({current_item}/{total_items})...")

    # 3. Enrich Artists
    if do_artists and not check_cancel():
        cache = _load_entity_cache("artist")
        for _, row in unique_artists.iterrows():
            if check_cancel(): break

            mbid = str(row["artist_mbid"]) if "artist_mbid" in row and pd.notna(row["artist_mbid"]) else None
            name_info = {"artist": row["artist"]}
            # PASSING FORCE_UPDATE HERE
            k, g = _enrich_single_entity("artist", mbid, name_info, cache, enrichment_mode, noise_tags, stats["artist"], force_update=force_cache_update)
            if mbid: artist_map[mbid] = g
            
            current_item += 1
            if progress_callback:
                progress_callback(current_item, total_items, f"Enriching Artists ({current_item}/{total_items})...")

    # Apply maps
    enriched_df = df.copy()

    if track_map and "recording_mbid" in enriched_df.columns:
        enriched_df["track_genres"] = enriched_df["recording_mbid"].map(
            lambda m: "|".join(track_map.get(str(m), [])) if pd.notna(m) else ""
        )

    if album_map and "release_mbid" in enriched_df.columns:
        enriched_df["album_genres"] = enriched_df["release_mbid"].map(
            lambda m: "|".join(album_map.get(str(m), [])) if pd.notna(m) else ""
        )
        
    if artist_map and "artist_mbid" in enriched_df.columns:
        enriched_df["artist_genres"] = enriched_df["artist_mbid"].map(
            lambda m: "|".join(artist_map.get(str(m), [])) if pd.notna(m) else ""
        )
        
    # Consolidate 'Genres' column
    genre_cols = [c for c in ["artist_genres", "album_genres", "track_genres"] if c in enriched_df.columns]
    
    if genre_cols:
        def unify_genres(row):
            tags = set()
            for c in genre_cols:
                val = row[c]
                if isinstance(val, str) and val:
                    for t in val.split("|"):
                        t = t.strip()
                        if t: tags.add(t)
            return "|".join(sorted(tags))

        if progress_callback:
            progress_callback(total_items, total_items, "Finalizing genre consolidation...")
            
        enriched_df["Genres"] = enriched_df.apply(unify_genres, axis=1)

    final_stats = {
        "artists": stats["artist"].to_dict(),
        "albums": stats["album"].to_dict(),
        "tracks": stats["track"].to_dict()
    }
    
    return enriched_df, final_stats