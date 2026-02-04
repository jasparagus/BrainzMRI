"""
Enhanced Enrichment implementation for BrainzMRI.

This module is responsible for fetching, caching, and applying metadata (specifically genres)
to the reporting DataFrames. It orchestrates local caching and delegates network calls
to the api_client module.
"""

import json
import os
from typing import Any, Optional, Callable

import pandas as pd
import numpy as np  # Needed for isnan checks

from config import config 
from api_client import MusicBrainzClient, LastFMClient
import parsing 

# ------------------------------------------------------------
# Constants and modes
# ------------------------------------------------------------

ENRICHMENT_MODE_CACHE_ONLY = "Cache Only"
ENRICHMENT_MODE_MB = "Query MusicBrainz"
ENRICHMENT_MODE_LASTFM = "Query Last.fm"
ENRICHMENT_MODE_ALL = "Query All Sources (Slow)"
CACHE_SAVE_BATCH_SIZE = 20 

# Initialize Clients
mb_client = MusicBrainzClient()
lastfm_client = LastFMClient()


# ------------------------------------------------------------
# Global cache paths and helpers
# ------------------------------------------------------------

def _get_global_dir() -> str:
    """Return the path to the global cache directory."""
    global_dir = os.path.join(config.cache_dir, "global")
    os.makedirs(global_dir, exist_ok=True)
    return global_dir


def _load_cache(filename: str) -> dict[str, Any]:
    path = os.path.join(_get_global_dir(), filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(filename: str, data: dict[str, Any]) -> None:
    path = os.path.join(_get_global_dir(), filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# ------------------------------------------------------------
# Resolver Cache (New for Persistence)
# ------------------------------------------------------------

def _load_resolver_cache() -> dict[str, Any]:
    return _load_cache("mbid_resolver_cache.json")

def _save_resolver_cache(data: dict[str, Any]) -> None:
    _save_cache("mbid_resolver_cache.json", data)


# ------------------------------------------------------------
# Core Enrichment Logic (Genres)
# ------------------------------------------------------------

def _enrich_single_entity(
    entity_type: str,
    info: dict[str, str],
    mode: str,
    force_update: bool
) -> dict[str, Any]:
    """
    Fetch metadata for a single entity (Artist, Album, or Track).
    Returns a dictionary of tags/genres found.
    """
    if mode == ENRICHMENT_MODE_CACHE_ONLY:
        return {}

    tags = set()
    api_endpoint = entity_type
    if entity_type == "track":
        api_endpoint = "recording"
    elif entity_type == "album":
        api_endpoint = "release"

    # 1. MusicBrainz Lookup
    if mode in (ENRICHMENT_MODE_MB, ENRICHMENT_MODE_ALL):
        mbid = info.get("mbid")

        if not mbid and entity_type == "track":
            # Basic resolution attempt
            res = mb_client.search_recording_details(info.get("artist"), info.get("track"), info.get("album"))
            if res:
                mbid = res["mbid"]

        if mbid:
            if entity_type == "album":
                mb_tags = mb_client.get_release_group_tags(mbid)
            else:
                mb_tags = mb_client.get_entity_tags(api_endpoint, mbid)
            
            tags.update(mb_tags)
        else:
            query = ""
            if entity_type == "artist":
                query = f'artist:"{info.get("artist")}"'
                mb_tags = mb_client.search_entity_tags("artist", query, "artists")
                tags.update(mb_tags)

    # 2. Last.fm Lookup
    if mode in (ENRICHMENT_MODE_LASTFM, ENRICHMENT_MODE_ALL):
        lf_tags = []
        if entity_type == "artist":
            lf_tags = lastfm_client.get_tags("artist.getTopTags", "artist", artist=info.get("artist"))
        elif entity_type == "track":
            lf_tags = lastfm_client.get_tags("track.getTopTags", "track", artist=info.get("artist"),
                                             track=info.get("track"))
        elif entity_type == "album":
            lf_tags = lastfm_client.get_tags("album.getTopTags", "album", artist=info.get("artist"),
                                             album=info.get("album"))

        tags.update(lf_tags)

    return {"genres": list(tags)}


def _process_enrichment_loop(
    entity_type: str,
    items_to_process: list[dict[str, str]], 
    results_map: dict[str, Any],  
    cache_filename: str,
    mode: str,
    force_update: bool,
    progress_callback: Optional[Callable],
    is_cancelled: Optional[Callable]
) -> dict[str, int]:
    stats = {
        "processed": 0,
        "cache_hits": 0,
        "newly_fetched": 0,
        "empty": 0,
        "fallbacks": 0
    }

    updates_since_save = 0
    total = len(items_to_process)

    for i, item in enumerate(items_to_process):
        if is_cancelled and is_cancelled():
            break

        stats["processed"] += 1
        key = item["_key"]

        if not force_update and key in results_map:
            stats["cache_hits"] += 1
            continue

        if progress_callback:
            msg = f"Enriching {entity_type} {i + 1}/{total}..."
            progress_callback(i, total, msg)

        result_data = _enrich_single_entity(entity_type, item, mode, force_update)

        if result_data and result_data.get("genres"):
            results_map[key] = result_data
            stats["newly_fetched"] += 1
            if not item.get("mbid"):
                stats["fallbacks"] += 1
        else:
            results_map[key] = {"genres": []}
            stats["empty"] += 1

        updates_since_save += 1

        if updates_since_save >= CACHE_SAVE_BATCH_SIZE:
            _save_cache(cache_filename, results_map)
            updates_since_save = 0

    if updates_since_save > 0:
        _save_cache(cache_filename, results_map)

    return stats


def enrich_report(
    df: pd.DataFrame,
    *,  
    enrichment_mode: str = ENRICHMENT_MODE_CACHE_ONLY,
    force_cache_update: bool = False,
    progress_callback: Optional[Callable] = None,
    is_cancelled: Optional[Callable] = None,
    deep_query: bool = False
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Main entry point. Enriches the DataFrame with Genre data.
    """
    if df.empty:
        return df, {}

    df = df.copy()
    stats_report = {}

    artist_cache = _load_cache("artist_enrichment.json")
    album_cache = _load_cache("album_enrichment.json")
    track_cache = _load_cache("track_enrichment.json")

    # 1. Artists
    if "artist" in df.columns:
        if "artist_mbid" in df.columns:
            artists_df = (
                df[["artist", "artist_mbid"]]
                .sort_values(by="artist_mbid", na_position="last")
                .drop_duplicates(subset=["artist"], keep="first")
            )
        else:
            artists_df = df[["artist"]].drop_duplicates()

        items_to_process = []
        for _, row in artists_df.iterrows():
            name = str(row["artist"])
            mbid = str(row.get("artist_mbid", ""))
            if mbid == "None" or mbid == "nan": mbid = ""

            if mbid:
                key = mbid
            else:
                key = name

            items_to_process.append({
                "_key": key,
                "artist": name,
                "mbid": mbid
            })

        st = _process_enrichment_loop(
            "artist", items_to_process, artist_cache, "artist_enrichment.json",
            enrichment_mode, force_cache_update, progress_callback, is_cancelled
        )
        stats_report["artists"] = st

    # 2. Albums
    if deep_query and "album" in df.columns and "artist" in df.columns:
        cols = ["artist", "album"]
        if "release_mbid" in df.columns: cols.append("release_mbid")

        albums_df = df[cols].drop_duplicates(subset=["artist", "album"])

        items_to_process = []
        for _, row in albums_df.iterrows():
            artist = str(row["artist"])
            album = str(row["album"])
            if album.lower() == "unknown": continue

            mbid = str(row.get("release_mbid", ""))
            if mbid == "None" or mbid == "nan": mbid = ""

            if mbid:
                key = mbid
            else:
                key = parsing.make_album_key(artist, album)

            items_to_process.append({
                "_key": key,
                "artist": artist,
                "album": album,
                "mbid": mbid
            })

        st = _process_enrichment_loop(
            "album", items_to_process, album_cache, "album_enrichment.json",
            enrichment_mode, force_cache_update, progress_callback, is_cancelled
        )
        stats_report["albums"] = st

    # 3. Tracks
    if deep_query and "track_name" in df.columns and "artist" in df.columns:
        cols = ["artist", "track_name"]
        if "album" in df.columns: cols.append("album")
        if "recording_mbid" in df.columns: cols.append("recording_mbid")

        tracks_df = df[cols].drop_duplicates(subset=["artist", "track_name"])

        items_to_process = []
        for _, row in tracks_df.iterrows():
            artist = str(row["artist"])
            track = str(row["track_name"])
            album = str(row.get("album", ""))

            mbid = str(row.get("recording_mbid", ""))
            if mbid == "None" or mbid == "nan": mbid = ""

            if mbid:
                key = mbid
            else:
                key = parsing.make_track_key(artist, track, album)

            items_to_process.append({
                "_key": key,
                "artist": artist,
                "track": track,
                "album": album,
                "mbid": mbid
            })

        st = _process_enrichment_loop(
            "track", items_to_process, track_cache, "track_enrichment.json",
            enrichment_mode, force_cache_update, progress_callback, is_cancelled
        )
        stats_report["tracks"] = st

    # Apply Results
    def get_genres(key_series, cache):
        return key_series.map(lambda k: "|".join(cache.get(k, {}).get("genres", [])))

    if "artist" in df.columns:
        def get_artist_key(row):
            mbid = str(row.get("artist_mbid", ""))
            if mbid and mbid != "None" and mbid != "nan":
                return mbid
            return str(row["artist"])
        keys = df.apply(get_artist_key, axis=1)
        df["artist_genres"] = get_genres(keys, artist_cache)

    if "album" in df.columns and "artist" in df.columns:
        def get_album_key(row):
            mbid = str(row.get("release_mbid", ""))
            if mbid and mbid != "None" and mbid != "nan":
                return mbid
            return parsing.make_album_key(row["artist"], row["album"])
        keys = df.apply(get_album_key, axis=1)
        df["album_genres"] = get_genres(keys, album_cache)
    else:
        df["album_genres"] = ""

    if "track_name" in df.columns and "artist" in df.columns:
        def get_track_key(row):
            mbid = str(row.get("recording_mbid", ""))
            if mbid and mbid != "None" and mbid != "nan":
                return mbid
            album = row.get("album", "")
            return parsing.make_track_key(row["artist"], row["track_name"], album)
        keys = df.apply(get_track_key, axis=1)
        df["track_genres"] = get_genres(keys, track_cache)
    else:
        df["track_genres"] = ""

    def unify_genres(row):
        g = set()
        for col in ["artist_genres", "album_genres", "track_genres"]:
            val = row.get(col, "")
            if val:
                g.update(val.split("|"))
        g.discard("")
        return "|".join(sorted(list(g)))

    df["Genres"] = df.apply(unify_genres, axis=1)

    return df, stats_report


# ------------------------------------------------------------
# Metadata Resolution (Persistence Added)
# ------------------------------------------------------------

def resolve_missing_mbids(
    df: pd.DataFrame,
    force_update: bool = False,
    progress_callback: Optional[Callable] = None,
    is_cancelled: Optional[Callable] = None
) -> tuple[pd.DataFrame, int, int]:
    """
    Attempt to find missing recording_mbids. Uses a persistent cache.
    """
    if "recording_mbid" not in df.columns:
        df["recording_mbid"] = ""

    # Load persistent resolver cache
    results_map = _load_resolver_cache()
    original_cache_size = len(results_map)

    # Identify rows needing resolution
    # Logic: if force_update is True, we attempt to resolve ALL rows, even if they have MBIDs?
    # NO, force_update usually means "re-fetch items that are in cache but maybe stale" OR "re-fetch items that failed".
    # But here, we are iterating "unique_rows".
    # For now, let's keep the mask strictly for "missing or empty" MBIDs in the DataFrame.
    # The user wants to "Force a cache overwrite".
    # This implies that if the item IS missing in DF, but IS in cache, we should ignore the cache and fetch again.
    
    mask_missing = (
        (df["recording_mbid"].isna() | (df["recording_mbid"] == "") | (df["recording_mbid"] == "None")) &
        (df["artist"].notna() & (df["artist"] != "")) &
        (df["track_name"].notna() & (df["track_name"] != ""))
    )

    unique_rows = df.loc[mask_missing, ["artist", "track_name", "album"]].drop_duplicates()

    total = len(unique_rows)
    resolved_count = 0
    failed_count = 0
    updates_since_save = 0

    for i, (_, row) in enumerate(unique_rows.iterrows()):
        if is_cancelled and is_cancelled():
            break

        # Sanitization: Force strings, handle NaN
        artist = str(row["artist"]).strip()
        track = str(row["track_name"]).strip()
        
        # Safe album extraction
        album_val = row["album"]
        if pd.isna(album_val) or str(album_val).lower() == "nan" or str(album_val).lower() == "none":
            album = ""
        else:
            album = str(album_val).strip()

        key = parsing.make_track_key(artist, track, album)

        # Check Cache (bypass if force_update)
        if not force_update and key in results_map:
            # We count it as resolved if the cache has a valid entry
            if results_map[key]: 
                resolved_count += 1
            else:
                failed_count += 1
            continue

        if progress_callback:
            progress_callback(i, total, f"Resolving: {artist} - {track}...")

        # API Call (Slow)
        res = mb_client.search_recording_details(artist, track, album)
        
        results_map[key] = res # res is dict or None
        updates_since_save += 1

        if res:
            resolved_count += 1
        else:
            failed_count += 1
        
        # Periodic Save
        if updates_since_save >= 10:
            _save_resolver_cache(results_map)
            updates_since_save = 0

    # Final Save
    if updates_since_save > 0:
        _save_resolver_cache(results_map)

    # Apply results to dataframe
    def applicator(row):
        existing_mbid = row.get("recording_mbid")
        existing_album = row.get("album")

        # If already exists, keep it
        if existing_mbid and str(existing_mbid) != "None" and str(existing_mbid) != "":
            return pd.Series([existing_mbid, existing_album], index=["recording_mbid", "album"])

        # Re-construct key to lookup result
        # Must match sanitization logic above
        a_val = row["album"]
        if pd.isna(a_val) or str(a_val).lower() == "nan" or str(a_val).lower() == "none":
            safe_album = ""
        else:
            safe_album = str(a_val).strip()
            
        k = parsing.make_track_key(str(row["artist"]).strip(), str(row["track_name"]).strip(), safe_album)
        res = results_map.get(k)

        if res and isinstance(res, dict) and "mbid" in res:
            new_mbid = res["mbid"]
            new_album = res.get("album", existing_album)

            # Use new album name if original was unknown/missing
            final_album = existing_album
            if pd.isna(existing_album) or str(existing_album).lower() in ["unknown", "none", "nan", ""]:
                final_album = new_album

            return pd.Series([new_mbid, final_album], index=["recording_mbid", "album"])

        return pd.Series([existing_mbid, existing_album], index=["recording_mbid", "album"])

    if not df.empty:
        cols_out = df.apply(applicator, axis=1)
        df["recording_mbid"] = cols_out["recording_mbid"]
        df["album"] = cols_out["album"]

    return df, resolved_count, failed_count