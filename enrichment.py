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
# NOTE: This is a placeholder. The user must configure a real API key in environment or config.
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
    """
    Return the path to the enrichment cache file for a given entity type.

    Parameters
    ----------
    entity_type : str
        One of "track", "album", or "artist".
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
    """
    Canonicalize a single tag string.

    Operations:
    - Lowercase
    - Unicode normalization (NFD) and accent stripping
    - Whitespace trimming
    - Replace non-alphanumeric sequences with single spaces
    """
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
    """
    Process a list of raw tags: canonicalize them and remove noise tags.

    Returns
    -------
    List[str]
        Sorted list of unique, valid canonical tags.
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
    """Load the enrichment cache for the specified entity type."""
    path = _get_enrichment_cache_path(entity_type)
    return _load_json_dict(path)


def _save_entity_cache(entity_type: str, data: Dict[str, Any]) -> None:
    """Save the enrichment cache for the specified entity type."""
    path = _get_enrichment_cache_path(entity_type)
    _save_json_dict(path, data)


def _get_entity_entry(cache: Dict[str, Any], key: str) -> Dict[str, Any]:
    """
    Retrieve or initialize a cache entry for a given key (MBID or Name).
    """
    entry = cache.get(key)
    if entry is None:
        entry = {
            "genres": [],
            "sources": {
                "musicbrainz": False,
                "lastfm": False,
            },
        }
        cache[key] = entry
    else:
        entry.setdefault("genres", [])
        entry.setdefault("sources", {})
        entry["sources"].setdefault("musicbrainz", False)
        entry["sources"].setdefault("lastfm", False)
    return entry


def _maybe_clear_entry_for_force_update(cache: Dict[str, Any], key: str, force: bool) -> None:
    """Remove an entry from the cache if force update is requested."""
    if force and key in cache:
        del cache[key]


# ------------------------------------------------------------
# Provider: MusicBrainz
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
    if not tags_field:
        return []
    out = []
    for item in tags_field:
        name = item.get("name")
        if name:
            out.append(name)
    return out


# --- MBID Based Lookups ---

def mb_enrich_recording(recording_mbid: str) -> List[str]:
    """Fetch tags for a recording MBID from MusicBrainz."""
    if not recording_mbid: return []
    try:
        data = _mb_request(f"recording/{recording_mbid}", {"fmt": "json", "inc": "tags+genres"})
        return _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
    except Exception:
        return []

def mb_enrich_release(release_mbid: str) -> List[str]:
    """Fetch tags for a release MBID from MusicBrainz."""
    if not release_mbid: return []
    try:
        data = _mb_request(f"release/{release_mbid}", {"fmt": "json", "inc": "tags+genres"})
        return _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
    except Exception:
        return []

def mb_enrich_artist(artist_mbid: str) -> List[str]:
    """Fetch tags for an artist MBID from MusicBrainz."""
    if not artist_mbid: return []
    try:
        data = _mb_request(f"artist/{artist_mbid}", {"fmt": "json", "inc": "tags+genres"})
        return _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
    except Exception:
        return []


# --- Name Based Fallback (Search) ---

def mb_search_artist(artist_name: str) -> List[str]:
    """Search for an artist by name on MusicBrainz and return tags of the top result."""
    if not artist_name: return []
    try:
        query = f'artist:"{artist_name}"'
        data = _mb_request("artist", {"query": query, "fmt": "json", "limit": "1"})
        artists = data.get("artists", [])
        if artists:
            best = artists[0]
            return _mb_tags_to_list(best.get("tags"))
        return []
    except Exception:
        return []

def mb_search_release(artist_name: str, release_name: str) -> List[str]:
    """Search for a release by name/artist on MusicBrainz and return tags of the top result."""
    if not artist_name or not release_name: return []
    try:
        query = f'release:"{release_name}" AND artist:"{artist_name}"'
        data = _mb_request("release", {"query": query, "fmt": "json", "limit": "1"})
        releases = data.get("releases", [])
        if releases:
            best = releases[0]
            return _mb_tags_to_list(best.get("tags"))
        return []
    except Exception:
        return []

def mb_search_recording(artist_name: str, track_name: str) -> List[str]:
    """Search for a recording by name/artist on MusicBrainz and return tags of the top result."""
    if not artist_name or not track_name: return []
    try:
        query = f'recording:"{track_name}" AND artist:"{artist_name}"'
        data = _mb_request("recording", {"query": query, "fmt": "json", "limit": "1"})
        recs = data.get("recordings", [])
        if recs:
            best = recs[0]
            return _mb_tags_to_list(best.get("tags"))
        return []
    except Exception:
        return []


# ------------------------------------------------------------
# Provider: Last.fm
# ------------------------------------------------------------

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

def _lastfm_extract_tags(toplevel_key: str, data: Dict[str, Any]) -> List[str]:
    """Extract tags from Last.fm response structure."""
    toplevel = data.get(toplevel_key) or {}
    tags_block = toplevel.get("toptags") or toplevel.get("tags") or {}
    tags_list = tags_block.get("tag") or []
    out = []
    if isinstance(tags_list, dict): tags_list = [tags_list]
    for t in tags_list:
        name = t.get("name")
        if name: out.append(name)
    return out

def lastfm_enrich_track(artist_name: str, track_name: str) -> List[str]:
    """Fetch tags for a track from Last.fm."""
    if not artist_name or not track_name: return []
    try:
        data = _lastfm_request({"method": "track.getInfo", "artist": artist_name, "track": track_name})
        return _lastfm_extract_tags("track", data)
    except Exception: return []

def lastfm_enrich_album(artist_name: str, album_name: str) -> List[str]:
    """Fetch tags for an album from Last.fm."""
    if not artist_name or not album_name: return []
    try:
        data = _lastfm_request({"method": "album.getInfo", "artist": artist_name, "album": album_name})
        return _lastfm_extract_tags("album", data)
    except Exception: return []

def lastfm_enrich_artist(artist_name: str) -> List[str]:
    """Fetch tags for an artist from Last.fm."""
    if not artist_name: return []
    try:
        data = _lastfm_request({"method": "artist.getInfo", "artist": artist_name})
        return _lastfm_extract_tags("artist", data)
    except Exception: return []


# ------------------------------------------------------------
# Entity Enrichment Orchestration
# ------------------------------------------------------------

class EnrichmentStats:
    """Helper class to track enrichment performance metrics."""
    def __init__(self):
        self.processed = 0
        self.cache_hits = 0
        self.mb_lookups = 0
        self.lastfm_lookups = 0
        self.fallbacks = 0
    
    def to_dict(self):
        return self.__dict__.copy()


def _enrich_single_entity(
    entity_type: str,
    mbid: Optional[str],
    name_info: Dict[str, str], # {"artist": "...", "album": "...", "track": "..."}
    cache: Dict[str, Any],
    enrichment_mode: str,
    noise_tags: Set[str],
    stats: EnrichmentStats
) -> Tuple[str, List[str]]:
    """
    Enrich a single entity.
    
    Logic:
    1. Check Cache.
    2. If not found or forced update, query configured providers.
    3. Try MBID first; if missing/fails, fallback to Name Search.
    4. Canonicalize tags and update cache.
    
    Returns
    -------
    (key, genres) : Tuple[str, List[str]]
        The key is the MBID (if available) or the Name Key used for storage.
    """
    
    # Determine the unique cache key. Prefer MBID, fallback to name combo.
    key = mbid
    if not key:
        # Construct fallback key from names
        parts = []
        if name_info.get("artist"): parts.append(name_info["artist"])
        if entity_type == "album" and name_info.get("album"): parts.append(name_info["album"])
        if entity_type == "track" and name_info.get("track"): parts.append(name_info["track"])
        key = "|".join(parts)
    
    if not key: return "", [] # Cannot enrich without ID or Name

    entry = cache.get(key)

    # CHECK CACHE
    if enrichment_mode == ENRICHMENT_MODE_CACHE_ONLY:
        stats.processed += 1
        if entry and entry.get("genres"):
            stats.cache_hits += 1
            return key, entry.get("genres")
        return key, []

    # If already cached and we are NOT forced to update, return cache
    if entry and entry.get("genres"):
        stats.processed += 1
        stats.cache_hits += 1
        return key, entry.get("genres")

    # DO LOOKUP
    stats.processed += 1
    accumulated_tags: List[str] = []
    
    # 1. MusicBrainz
    if enrichment_mode in (ENRICHMENT_MODE_MB, ENRICHMENT_MODE_ALL):
        tags = []
        # Try MBID first
        if mbid:
            if entity_type == "track": tags = mb_enrich_recording(mbid)
            elif entity_type == "album": tags = mb_enrich_release(mbid)
            elif entity_type == "artist": tags = mb_enrich_artist(mbid)
            if tags: stats.mb_lookups += 1
        
        # Fallback to Name Search if MBID failed or missing
        if not tags and not mbid:
            stats.fallbacks += 1
            if entity_type == "track": 
                tags = mb_search_recording(name_info.get("artist"), name_info.get("track"))
            elif entity_type == "album": 
                tags = mb_search_release(name_info.get("artist"), name_info.get("album"))
            elif entity_type == "artist": 
                tags = mb_search_artist(name_info.get("artist"))
            if tags: stats.mb_lookups += 1 # Count as lookup even if fallback
            
        if tags:
            accumulated_tags.extend(tags)
            time.sleep(NETWORK_DELAY_SECONDS)

    # 2. Last.fm
    if enrichment_mode in (ENRICHMENT_MODE_LASTFM, ENRICHMENT_MODE_ALL):
        tags = []
        # Last.fm is always name based
        if entity_type == "track":
            tags = lastfm_enrich_track(name_info.get("artist"), name_info.get("track"))
        elif entity_type == "album":
            tags = lastfm_enrich_album(name_info.get("artist"), name_info.get("album"))
        elif entity_type == "artist":
            tags = lastfm_enrich_artist(name_info.get("artist"))
        
        if tags:
            stats.lastfm_lookups += 1
            accumulated_tags.extend(tags)
            time.sleep(NETWORK_DELAY_SECONDS)

    # Finalize
    entry = _get_entity_entry(cache, key)
    
    if not accumulated_tags and entry.get("genres"):
        canonical_genres = entry.get("genres")
    else:
        canonical_new = canonicalize_and_filter_tags(accumulated_tags, noise_tags)
        existing = entry.get("genres") or []
        merged = set(existing) | set(canonical_new)
        canonical_genres = sorted(merged)

    # Update cache entry
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
    
    Orchestrates the enrichment of artists, albums, and tracks in the provided DataFrame.
    Supports progress reporting and cancellation via callbacks.

    Parameters
    ----------
    df : pd.DataFrame
        The report DataFrame to enrich.
    report_type : str
        The type of report ("artist", "album", "track"). Determines enrichment depth.
    enrichment_mode : str
        The selected enrichment mode (Cache Only, MusicBrainz, etc.).
    force_cache_update : bool
        If True, clears existing cache entries for affected entities before lookup.
    progress_callback : Callable, optional
        Callback to report progress (current, total, message).
    is_cancelled : Callable, optional
        Callback to check if the user has cancelled the operation.

    Returns
    -------
    enriched_df : pd.DataFrame
        The DataFrame with added genre columns (track_genres, album_genres, artist_genres, Genres).
    stats : dict
        Statistics about the enrichment process (hits, lookups, etc.).
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
    
    # Pre-calculate work to do for progress bar
    unique_tracks = pd.DataFrame()
    unique_albums = pd.DataFrame()
    unique_artists = pd.DataFrame()
    
    do_tracks = False
    do_albums = False
    do_artists = False

    # Identify work based on report type columns
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

    # Mappings from MBID -> Genre String
    track_map = {}
    album_map = {}
    artist_map = {}

    def check_cancel():
        if is_cancelled and is_cancelled():
            return True
        return False

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
            
            if force_cache_update and mbid and mbid in cache: del cache[mbid]
            
            k, g = _enrich_single_entity("track", mbid, name_info, cache, enrichment_mode, noise_tags, stats["track"])
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
            if force_cache_update and mbid and mbid in cache: del cache[mbid]
            
            k, g = _enrich_single_entity("album", mbid, name_info, cache, enrichment_mode, noise_tags, stats["album"])
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
            
            if force_cache_update and mbid and mbid in cache: del cache[mbid]
            
            k, g = _enrich_single_entity("artist", mbid, name_info, cache, enrichment_mode, noise_tags, stats["artist"])
            if mbid: artist_map[mbid] = g
            
            current_item += 1
            if progress_callback:
                progress_callback(current_item, total_items, f"Enriching Artists ({current_item}/{total_items})...")

    # Apply maps to create individual genre columns
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
        
    # ------------------------------------------------------------
    # Consolidate into master 'Genres' column
    # ------------------------------------------------------------
    # Identify which genre columns were actually created or exist
    genre_cols = [c for c in ["artist_genres", "album_genres", "track_genres"] if c in enriched_df.columns]
    
    if genre_cols:
        def unify_genres(row):
            """Combine, deduplicate, and sort genres from all available entities."""
            tags = set()
            for c in genre_cols:
                val = row[c]
                if isinstance(val, str) and val:
                    # columns are pipe-separated
                    for t in val.split("|"):
                        t = t.strip()
                        if t:
                            tags.add(t)
            return "|".join(sorted(tags))

        if progress_callback:
            progress_callback(total_items, total_items, "Finalizing genre consolidation...")
            
        enriched_df["Genres"] = enriched_df.apply(unify_genres, axis=1)

    # Flatten stats for return
    final_stats = {
        "artists": stats["artist"].to_dict(),
        "albums": stats["album"].to_dict(),
        "tracks": stats["track"].to_dict()
    }
    
    return enriched_df, final_stats