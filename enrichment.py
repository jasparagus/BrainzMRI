"""
Enhanced Enrichment implementation for BrainzMRI.
Includes:
- Multi-entity enrichment (track / album / artist)
- Multi-provider enrichment (MusicBrainz + Last.fm)
- Provider priority and Name-based Fallback
- Global cache for enriched genres
- Observability (stats collection)
"""

import json
import os
import time
import unicodedata
from typing import Dict, Any, List, Set, Tuple, Optional

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

NETWORK_DELAY_SECONDS = 1.05
LASTFM_API_ROOT = "https://ws.audioscrobbler.com/2.0/"
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
    path = _get_enrichment_cache_path(entity_type)
    return _load_json_dict(path)


def _save_entity_cache(entity_type: str, data: Dict[str, Any]) -> None:
    path = _get_enrichment_cache_path(entity_type)
    _save_json_dict(path, data)


def _get_entity_entry(cache: Dict[str, Any], key: str) -> Dict[str, Any]:
    """
    Get or create an entry in the cache. 
    'key' is usually MBID, but acts as a unique ID.
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
    if force and key in cache:
        del cache[key]


# ------------------------------------------------------------
# Provider: MusicBrainz
# ------------------------------------------------------------

def _mb_request(path: str, params: Dict[str, str]) -> Dict[str, Any]:
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
    if not tags_field:
        return []
    out = []
    for item in tags_field:
        name = item.get("name")
        if name:
            out.append(name)
    return out


# --- MBID Based ---

def mb_enrich_recording(recording_mbid: str) -> List[str]:
    if not recording_mbid: return []
    try:
        data = _mb_request(f"recording/{recording_mbid}", {"fmt": "json", "inc": "tags+genres"})
        return _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
    except Exception:
        return []

def mb_enrich_release(release_mbid: str) -> List[str]:
    if not release_mbid: return []
    try:
        data = _mb_request(f"release/{release_mbid}", {"fmt": "json", "inc": "tags+genres"})
        return _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
    except Exception:
        return []

def mb_enrich_artist(artist_mbid: str) -> List[str]:
    if not artist_mbid: return []
    try:
        data = _mb_request(f"artist/{artist_mbid}", {"fmt": "json", "inc": "tags+genres"})
        return _mb_tags_to_list(data.get("tags")) + _mb_tags_to_list(data.get("genres"))
    except Exception:
        return []


# --- Name Based Fallback (Search) ---

def mb_search_artist(artist_name: str) -> List[str]:
    """Fallback: Search for artist by name and get tags of top match."""
    if not artist_name: return []
    try:
        # Strict Lucene search for best match
        query = f'artist:"{artist_name}"'
        data = _mb_request("artist", {"query": query, "fmt": "json", "limit": "1"})
        artists = data.get("artists", [])
        if artists:
            best = artists[0]
            # Verify basic name match confidence? For now, trust top result.
            return _mb_tags_to_list(best.get("tags"))
        return []
    except Exception:
        return []

def mb_search_release(artist_name: str, release_name: str) -> List[str]:
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
    if not artist_name or not track_name: return []
    try:
        data = _lastfm_request({"method": "track.getInfo", "artist": artist_name, "track": track_name})
        return _lastfm_extract_tags("track", data)
    except Exception: return []

def lastfm_enrich_album(artist_name: str, album_name: str) -> List[str]:
    if not artist_name or not album_name: return []
    try:
        data = _lastfm_request({"method": "album.getInfo", "artist": artist_name, "album": album_name})
        return _lastfm_extract_tags("album", data)
    except Exception: return []

def lastfm_enrich_artist(artist_name: str) -> List[str]:
    if not artist_name: return []
    try:
        data = _lastfm_request({"method": "artist.getInfo", "artist": artist_name})
        return _lastfm_extract_tags("artist", data)
    except Exception: return []


# ------------------------------------------------------------
# Entity Enrichment Orchestration
# ------------------------------------------------------------

class EnrichmentStats:
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
    Returns (key, genres). The key is MBID if available, else name representation.
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
    # (Assuming force_cache logic is handled by clearing entry before calling this, or checked here.
    #  We will assume the caller cleared the specific entry if force was True.)
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
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Main entry point.
    Returns (enriched_df, stats_dict).
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
    
    # Determine which entities to enrich based on report type
    # For a Track report, we might want Track AND Artist genres.
    # For now, we mimic the existing logic: track->track_genres, album->album_genres, etc.
    
    # Mapping of MBIDs to Genres
    track_map = {}
    album_map = {}
    artist_map = {}

    # 1. Enrich Tracks
    if "recording_mbid" in df.columns or ("track_name" in df.columns and "artist" in df.columns):
        # We only enrich tracks if it is a 'track' report to save time, or if explicitly requested.
        # The prompt implies we enrich based on available columns.
        
        # To avoid iterating rows 3 times, we can iterate unique tuples.
        # Unique tracks:
        track_cols = ["artist", "track_name"]
        if "recording_mbid" in df.columns: track_cols.append("recording_mbid")
        unique_tracks = df[track_cols].drop_duplicates()
        
        if report_type == "track":
            cache = _load_entity_cache("track")
            for _, row in unique_tracks.iterrows():
                mbid = str(row["recording_mbid"]) if "recording_mbid" in row and pd.notna(row["recording_mbid"]) else None
                name_info = {
                    "artist": row["artist"] if "artist" in row else "",
                    "track": row["track_name"] if "track_name" in row else ""
                }
                
                if force_cache_update and mbid and mbid in cache: del cache[mbid]
                
                k, g = _enrich_single_entity("track", mbid, name_info, cache, enrichment_mode, noise_tags, stats["track"])
                if mbid: track_map[mbid] = g
                # Also map by name if mbid missing? For now we only map back to DF via MBID if present.
                # If the DF has no MBID, we can't easily join back without a complex merge.
                # Supported scope: MBID based join.

    # 2. Enrich Albums
    if "release_mbid" in df.columns or ("album" in df.columns and "artist" in df.columns):
        if report_type in ("album", "track"): # track reports also show album info
            album_cols = ["artist", "album"]
            if "release_mbid" in df.columns: album_cols.append("release_mbid")
            # Filter out empty albums
            unique_albums = df[album_cols].drop_duplicates()
            unique_albums = unique_albums[unique_albums["album"] != "Unknown"]
            
            cache = _load_entity_cache("album")
            for _, row in unique_albums.iterrows():
                mbid = str(row["release_mbid"]) if "release_mbid" in row and pd.notna(row["release_mbid"]) else None
                name_info = {
                    "artist": row["artist"] if "artist" in row else "",
                    "album": row["album"] if "album" in row else ""
                }
                if force_cache_update and mbid and mbid in cache: del cache[mbid]
                
                k, g = _enrich_single_entity("album", mbid, name_info, cache, enrichment_mode, noise_tags, stats["album"])
                if mbid: album_map[mbid] = g

    # 3. Enrich Artists (Always valid if artist col exists)
    if "artist" in df.columns:
        artist_cols = ["artist"]
        if "artist_mbid" in df.columns: artist_cols.append("artist_mbid")
        unique_artists = df[artist_cols].drop_duplicates()
        
        cache = _load_entity_cache("artist")
        for _, row in unique_artists.iterrows():
            mbid = str(row["artist_mbid"]) if "artist_mbid" in row and pd.notna(row["artist_mbid"]) else None
            name_info = {"artist": row["artist"]}
            
            if force_cache_update and mbid and mbid in cache: del cache[mbid]
            
            k, g = _enrich_single_entity("artist", mbid, name_info, cache, enrichment_mode, noise_tags, stats["artist"])
            if mbid: artist_map[mbid] = g

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

    # Flatten stats for return
    final_stats = {
        "artists": stats["artist"].to_dict(),
        "albums": stats["album"].to_dict(),
        "tracks": stats["track"].to_dict()
    }
    
    return enriched_df, final_stats