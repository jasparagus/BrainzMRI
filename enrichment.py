"""
Enhanced Enrichment implementation for BrainzMRI.

This module is responsible for fetching, caching, and applying metadata (specifically genres)
to the reporting DataFrames. It orchestrates local caching and delegates network calls
to the api_client module.
"""

import json
import os
import unicodedata
from typing import Dict, Any, List, Set, Tuple, Optional, Callable

import pandas as pd

from user import get_cache_root
from api_client import MusicBrainzClient, LastFMClient
import parsing  # Imported for key generation


# ------------------------------------------------------------
# Constants and modes
# ------------------------------------------------------------

ENRICHMENT_MODE_CACHE_ONLY = "Cache Only"
ENRICHMENT_MODE_MB = "Query MusicBrainz"
ENRICHMENT_MODE_LASTFM = "Query Last.fm"
ENRICHMENT_MODE_ALL = "Query All Sources (Slow)"
CACHE_SAVE_BATCH_SIZE = 20  # Save cache after this many updates

# Initialize Clients
mb_client = MusicBrainzClient()
lastfm_client = LastFMClient()


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

def _get_resolver_cache_path() -> str:
    """Return the path to the MBID resolver cache."""
    global_dir = _get_global_dir()
    return os.path.join(global_dir, "mbid_resolver_cache.json")

def _get_failures_cache_path() -> str:
    """Return the path to the enrichment failures log."""
    global_dir = _get_global_dir()
    return os.path.join(global_dir, "enrichment_failures.json")

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
# Provider Wrapper Logic (Delegates to api_client)
# ------------------------------------------------------------

def mb_enrich_recording(mbid: str) -> List[str]: 
    return mb_client.get_entity_tags("recording", mbid)

def mb_enrich_release(mbid: str) -> List[str]: 
    return mb_client.get_entity_tags("release", mbid)

def mb_enrich_artist(mbid: str) -> List[str]: 
    return mb_client.get_entity_tags("artist", mbid)

# --- MB Search Fallbacks ---

def mb_search_artist(artist_name: str) -> List[str]:
    if not artist_name: return []
    return mb_client.search_entity_tags("artist", f'artist:"{artist_name}"', "artists")

def mb_search_release(artist_name: str, release_name: str) -> List[str]:
    if not artist_name or not release_name: return []
    q = f'release:"{release_name}" AND artist:"{artist_name}"'
    return mb_client.search_entity_tags("release", q, "releases")

def mb_search_recording(artist_name: str, track_name: str) -> List[str]:
    if not artist_name or not track_name: return []
    q = f'recording:"{track_name}" AND artist:"{artist_name}"'
    return mb_client.search_entity_tags("recording", q, "recordings")


# --- Last.fm Logic ---

def lastfm_enrich_track(artist: str, track: str) -> List[str]:
    if not artist or not track: return []
    return lastfm_client.get_tags("track.getInfo", "track", artist=artist, track=track)

def lastfm_enrich_album(artist: str, album: str) -> List[str]:
    if not artist or not album: return []
    return lastfm_client.get_tags("album.getInfo", "album", artist=artist, album=album)

def lastfm_enrich_artist(artist: str) -> List[str]:
    if not artist: return []
    return lastfm_client.get_tags("artist.getInfo", "artist", artist=artist)


# ------------------------------------------------------------
# Entity Enrichment Orchestration
# ------------------------------------------------------------

class EnrichmentStats:
    """Helper class to track enrichment performance metrics."""
    def __init__(self):
        self.processed = 0
        self.cache_hits = 0
        self.newly_fetched = 0
        self.empty = 0
        self.fallbacks = 0
    
    def to_dict(self):
        return self.__dict__.copy()


def _update_failures_log(
    failures: Dict[str, Any], 
    entity_type: str, 
    mbid: str, 
    genres: List[str], 
    name_info: Dict[str, str],
    attempted_fetch: bool
):
    """
    Helper to update the failures dictionary (live state).
    - If genres found: Remove MBID from failure log (Fixed).
    - If no genres found AND we tried to fetch: Add MBID to failure log (Broken).
    """
    if failures is None or not mbid:
        return

    # Ensure container exists
    if entity_type not in failures:
        failures[entity_type] = {}

    if genres:
        # SUCCESS: Clean up if present
        if mbid in failures[entity_type]:
            del failures[entity_type][mbid]
    elif attempted_fetch:
        # FAILURE: Only log if we actually tried to fetch (not just a cold cache miss)
        readable = name_info.get("artist", "")
        if entity_type == "album":
            readable += f" - {name_info.get('album', '')}"
        elif entity_type == "track":
            readable += f" - {name_info.get('track', '')}"
        
        failures[entity_type][mbid] = readable.strip()


def _enrich_single_entity(
    entity_type: str,
    mbid: Optional[str],
    name_info: Dict[str, str],
    cache: Dict[str, Any],
    enrichment_mode: str,
    noise_tags: Set[str],
    stats: EnrichmentStats,
    failures: Optional[Dict[str, Any]] = None,
    force_update: bool = False
) -> Tuple[str, List[str], bool]:
    """
    Enrich a single entity.
    Returns (key, genres, cache_modified_bool). 
    Key is MBID (if available) or Name Key.
    Does NOT save to disk.
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
        return "", [], False

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
            res_genres = entry.get("genres")
            # Cleaning check (Success from cache)
            if mbid: _update_failures_log(failures, entity_type, mbid, res_genres, name_info, False)
            return key, res_genres, False
        else:
            stats.empty += 1
            # No logging here: It's Cache Only and empty, likely just cold.
            return key, [], False

    if entry and entry.get("genres"):
        stats.processed += 1
        stats.cache_hits += 1
        res_genres = entry.get("genres")
        # Cleaning check (Success from cache)
        if mbid: _update_failures_log(failures, entity_type, mbid, res_genres, name_info, False)
        return key, res_genres, False

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

    # 4. Finalize
    entry = _get_entity_entry(cache, key)
    
    cache_modified = False
    
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
            if not existing:
                stats.empty += 1
            else:
                stats.cache_hits += 1

    # Update cache (IN MEMORY ONLY)
    if canonical_genres:
        # Check if actually different to report modification
        if set(canonical_genres) != set(entry.get("genres", [])):
            entry["genres"] = canonical_genres
            if enrichment_mode in (ENRICHMENT_MODE_MB, ENRICHMENT_MODE_ALL):
                entry["sources"]["musicbrainz"] = True
            if enrichment_mode in (ENRICHMENT_MODE_LASTFM, ENRICHMENT_MODE_ALL):
                entry["sources"]["lastfm"] = True
            
            cache[key] = entry
            cache_modified = True

    # Failure Logging
    if mbid:
        # We know we attempted a fetch because we are past the CACHE_ONLY block
        _update_failures_log(failures, entity_type, mbid, canonical_genres, name_info, True)

    return key, canonical_genres, cache_modified


def enrich_report(
    df: pd.DataFrame,
    report_type: str,
    enrichment_mode: str,
    *,
    force_cache_update: bool = False,
    deep_query: bool = False,
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
    
    # Load Failures Log (Option 1: Active State)
    failures_path = _get_failures_cache_path()
    failures = _load_json_dict(failures_path)
    
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
        # LOGIC CHANGE: If not deep_query, force mode to CACHE_ONLY for tracks
        track_mode = enrichment_mode if deep_query else ENRICHMENT_MODE_CACHE_ONLY
        
        cache = _load_entity_cache("track")
        unsaved_changes = 0
        
        for _, row in unique_tracks.iterrows():
            if check_cancel(): break
            
            mbid = str(row["recording_mbid"]) if "recording_mbid" in row and pd.notna(row["recording_mbid"]) else None
            name_info = {
                "artist": row["artist"] if "artist" in row else "",
                "track": row["track_name"] if "track_name" in row else ""
            }
            k, g, modified = _enrich_single_entity("track", mbid, name_info, cache, track_mode, noise_tags, stats["track"], failures, force_update=force_cache_update)
            if mbid: track_map[mbid] = g
            
            if modified:
                unsaved_changes += 1
                if unsaved_changes >= CACHE_SAVE_BATCH_SIZE:
                    _save_entity_cache("track", cache)
                    unsaved_changes = 0
            
            current_item += 1
            if progress_callback:
                progress_callback(current_item, total_items, f"Enriching Tracks ({current_item}/{total_items})...")
        
        # Final Save
        if unsaved_changes > 0:
            _save_entity_cache("track", cache)

    # 2. Enrich Albums
    if do_albums and not check_cancel():
        # LOGIC CHANGE: If not deep_query, force mode to CACHE_ONLY for albums
        album_mode = enrichment_mode if deep_query else ENRICHMENT_MODE_CACHE_ONLY

        cache = _load_entity_cache("album")
        unsaved_changes = 0
        
        for _, row in unique_albums.iterrows():
            if check_cancel(): break

            mbid = str(row["release_mbid"]) if "release_mbid" in row and pd.notna(row["release_mbid"]) else None
            name_info = {
                "artist": row["artist"] if "artist" in row else "",
                "album": row["album"] if "album" in row else ""
            }
            k, g, modified = _enrich_single_entity("album", mbid, name_info, cache, album_mode, noise_tags, stats["album"], failures, force_update=force_cache_update)
            if mbid: album_map[mbid] = g
            
            if modified:
                unsaved_changes += 1
                if unsaved_changes >= CACHE_SAVE_BATCH_SIZE:
                    _save_entity_cache("album", cache)
                    unsaved_changes = 0
            
            current_item += 1
            if progress_callback:
                progress_callback(current_item, total_items, f"Enriching Albums ({current_item}/{total_items})...")
        
        # Final Save
        if unsaved_changes > 0:
            _save_entity_cache("album", cache)

    # 3. Enrich Artists
    if do_artists and not check_cancel():
        # Artists are always fetched (unless global mode is Cache Only)
        
        cache = _load_entity_cache("artist")
        unsaved_changes = 0
        
        for _, row in unique_artists.iterrows():
            if check_cancel(): break

            mbid = str(row["artist_mbid"]) if "artist_mbid" in row and pd.notna(row["artist_mbid"]) else None
            name_info = {"artist": row["artist"]}
            k, g, modified = _enrich_single_entity("artist", mbid, name_info, cache, enrichment_mode, noise_tags, stats["artist"], failures, force_update=force_cache_update)
            if mbid: artist_map[mbid] = g
            
            if modified:
                unsaved_changes += 1
                if unsaved_changes >= CACHE_SAVE_BATCH_SIZE:
                    _save_entity_cache("artist", cache)
                    unsaved_changes = 0
            
            current_item += 1
            if progress_callback:
                progress_callback(current_item, total_items, f"Enriching Artists ({current_item}/{total_items})...")
        
        # Final Save
        if unsaved_changes > 0:
            _save_entity_cache("artist", cache)

    # Save Failures Log
    _save_json_dict(failures_path, failures)

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


# ------------------------------------------------------------
# MBID RESOLVER (New in Phase 4.1)
# ------------------------------------------------------------

def resolve_missing_mbids(
    df: pd.DataFrame,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None
) -> Tuple[pd.DataFrame, int, int]:
    """
    Scan DataFrame for rows missing recording_mbid and attempt to resolve them.
    Fills in: recording_mbid AND album name (if Unknown/Missing).
    """
    if "recording_mbid" not in df.columns:
        return df, 0, 0
    
    # Work on a copy
    df_out = df.copy()
    
    # Identify unique rows that need help (Missing or None/NaN)
    mask_missing = (
        df_out["recording_mbid"].isna() | 
        (df_out["recording_mbid"] == "") | 
        (df_out["recording_mbid"] == "None")
    )
    
    # Create unique keys for lookup
    candidates = df_out[mask_missing][["artist", "track_name", "album"]].drop_duplicates()
    
    total = len(candidates)
    if total == 0:
        return df_out, 0, 0
        
    # Load Resolver Cache
    cache_path = _get_resolver_cache_path()
    cache = _load_json_dict(cache_path)
    
    count_resolved = 0
    count_failed = 0
    
    # Results map: key -> {"mbid": "...", "album": "..."}
    results_map = {}
    
    for i, (_, row) in enumerate(candidates.iterrows()):
        if is_cancelled and is_cancelled():
            break
            
        # Use centralized key generation
        key = parsing.make_track_key(row["artist"], row["track_name"], row["album"])
        
        # 1. Check Cache
        cached_entry = cache.get(key)
        
        if cached_entry:
            # Handle legacy string cache (convert to dict on the fly)
            if isinstance(cached_entry, str):
                if cached_entry == "NOT_FOUND":
                    count_failed += 1
                else:
                    results_map[key] = {"mbid": cached_entry, "album": row["album"]} # Keep old album if legacy cache
                    count_resolved += 1
            # Handle new dict cache
            elif isinstance(cached_entry, dict):
                if cached_entry.get("status") == "NOT_FOUND":
                    count_failed += 1
                else:
                    results_map[key] = cached_entry
                    count_resolved += 1
            
            if progress_callback:
                progress_callback(i+1, total, f"Resolving (Cached) {i+1}/{total}...")
            continue
            
        # 2. Hit API
        if progress_callback:
            progress_callback(i+1, total, f"Resolving (API) {i+1}/{total}...")
            
        # Returns dict: {'mbid': '...', 'album': '...', 'title': '...'}
        details = mb_client.search_recording_details(row["artist"], row["track_name"], row["album"], threshold=85)
        
        if details:
            # Cache success
            cache[key] = details
            results_map[key] = details
            count_resolved += 1
        else:
            # Cache failure (negative caching)
            cache[key] = {"status": "NOT_FOUND"}
            count_failed += 1
            
        # Save cache periodically
        if (i % 5) == 0:
            _save_json_dict(cache_path, cache)
            
    # Final save
    _save_json_dict(cache_path, cache)
    
    # 3. Apply to DataFrame using vectorized apply
    # We update both MBID and Album (if album is Unknown)
    
    def filler(row):
        existing_mbid = row["recording_mbid"]
        existing_album = row["album"]
        
        # If we already have an ID, we don't touch it
        if existing_mbid and str(existing_mbid) != "None" and str(existing_mbid) != "":
            return pd.Series([existing_mbid, existing_album], index=["recording_mbid", "album"])
            
        # Try to find resolved data using the centralized key
        k = parsing.make_track_key(row["artist"], row["track_name"], row["album"])
        res = results_map.get(k)
        
        if res and isinstance(res, dict) and "mbid" in res:
            new_mbid = res["mbid"]
            new_album = res.get("album", existing_album)
            
            # Logic: Only overwrite album if current is "Unknown" or empty
            # But wait, user might prefer the MB canonical album name over their own
            # Let's stick to: Overwrite if current is "Unknown"
            final_album = existing_album
            if str(existing_album).lower() == "unknown":
                final_album = new_album
                
            return pd.Series([new_mbid, final_album], index=["recording_mbid", "album"])
            
        # Fallback (legacy string cache handling implicit if result_map not cleaned)
        # But we normalized results_map above, so we are good.
        
        return pd.Series([existing_mbid, existing_album], index=["recording_mbid", "album"])
        
    # Update columns
    if not df_out.empty:
        df_out[["recording_mbid", "album"]] = df_out.apply(filler, axis=1)
    
    return df_out, count_resolved, count_failed