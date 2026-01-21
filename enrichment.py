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

from config import config # REFACTORED
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
    # REFACTORED: Use config
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
# Core Enrichment Logic
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

    # Map internal entity types to API endpoints
    # track -> recording
    # album -> release (But we typically hop to release-group for tags)
    # artist -> artist
    api_endpoint = entity_type
    if entity_type == "track":
        api_endpoint = "recording"
    elif entity_type == "album":
        api_endpoint = "release"

    # 1. MusicBrainz Lookup
    if mode in (ENRICHMENT_MODE_MB, ENRICHMENT_MODE_ALL):
        mbid = info.get("mbid")

        # If we don't have an MBID, try to find one first (Resolution)
        if not mbid and entity_type == "track":
            # Basic resolution attempt
            res = mb_client.search_recording_details(info.get("artist"), info.get("track"), info.get("album"))
            if res:
                mbid = res["mbid"]
                # We could update the cache with this new MBID here, but for now just use it for tags

        if mbid:
            if entity_type == "album":
                # Special logic for Albums: The MBID is likely a Release ID.
                # Releases rarely have genres; Release Groups do.
                mb_tags = mb_client.get_release_group_tags(mbid)
            else:
                # Standard lookup for Artist/Recording
                mb_tags = mb_client.get_entity_tags(api_endpoint, mbid)
            
            tags.update(mb_tags)
        else:
            # Fallback: Search by name if no MBID (and resolution failed or not attempted)
            # This is "Fuzzy Enrichment"
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
    items_to_process: list[dict[str, str]],  # List of dicts identifying the item
    results_map: dict[str, Any],  # The cache dict to update
    cache_filename: str,
    mode: str,
    force_update: bool,
    progress_callback: Optional[Callable],
    is_cancelled: Optional[Callable]
) -> dict[str, int]:
    """
    Generic loop to process a list of items, fetch metadata, update cache, and report progress.
    Returns stats: {'processed', 'cache_hits', 'newly_fetched', 'empty', 'fallbacks'}
    """
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

        # Determine unique key for this item
        # Note: 'item' must contain '_key' field pre-calculated by caller
        key = item["_key"]

        # Check Cache
        if not force_update and key in results_map:
            stats["cache_hits"] += 1
            continue

        # Fetch
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
            # Negative Caching to prevent re-fetching empty results forever
            results_map[key] = {"genres": []}
            stats["empty"] += 1

        updates_since_save += 1

        # Batch Save
        if updates_since_save >= CACHE_SAVE_BATCH_SIZE:
            _save_cache(cache_filename, results_map)
            updates_since_save = 0

    # Final Save
    if updates_since_save > 0:
        _save_cache(cache_filename, results_map)

    return stats


def enrich_report(
    df: pd.DataFrame,
    *,  # STRICT KEYWORD ENFORCEMENT
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

    stats_report = {}

    # ------------------------------------------------------------------
    # 1. Prepare Caches (Restored legacy filenames)
    # ------------------------------------------------------------------
    artist_cache = _load_cache("artist_enrichment.json")
    album_cache = _load_cache("album_enrichment.json")
    track_cache = _load_cache("track_enrichment.json")

    # ------------------------------------------------------------------
    # 2. Enrich Artists (Always runs if column exists)
    # ------------------------------------------------------------------
    if "artist" in df.columns:
        # Prepare unique artists list
        # Prioritize rows with MBIDs for better cache keys
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

            # Key generation: Prioritize MBID, Fallback to Name
            # This matches the healthy behavior.
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

    # ------------------------------------------------------------------
    # 3. Enrich Albums (Conditional: Deep Query)
    # ------------------------------------------------------------------
    if deep_query and "album" in df.columns and "artist" in df.columns:
        # Dedupe
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

            # Key: Prioritize MBID, Fallback to Name
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

    # ------------------------------------------------------------------
    # 4. Enrich Tracks (Conditional: Deep Query)
    # ------------------------------------------------------------------
    if deep_query and "track_name" in df.columns and "artist" in df.columns:
        # Dedupe
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

            # Key: Prioritize MBID, Fallback to Name
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

    # ------------------------------------------------------------------
    # 5. Apply Results to DataFrame
    # ------------------------------------------------------------------

    # Helper to get genres safely
    def get_genres(key_series, cache):
        return key_series.map(lambda k: "|".join(cache.get(k, {}).get("genres", [])))

    # Apply Artists
    if "artist" in df.columns:
        # We must replicate the key generation logic here to perform the lookup
        def get_artist_key(row):
            mbid = str(row.get("artist_mbid", ""))
            if mbid and mbid != "None" and mbid != "nan":
                return mbid
            return str(row["artist"])

        # Create a temporary series of keys
        keys = df.apply(get_artist_key, axis=1)
        df["artist_genres"] = get_genres(keys, artist_cache)

    # Apply Albums
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

    # Apply Tracks
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

    # Unified Genre Column
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
# Metadata Resolution
# ------------------------------------------------------------

def resolve_missing_mbids(
    df: pd.DataFrame,
    progress_callback: Optional[Callable] = None,
    is_cancelled: Optional[Callable] = None
) -> tuple[pd.DataFrame, int, int]:
    """
    Attempt to find missing recording_mbids for tracks in the dataframe.
    """
    if "recording_mbid" not in df.columns:
        df["recording_mbid"] = ""

    mask_missing = (
        (df["recording_mbid"].isna() | (df["recording_mbid"] == "") | (df["recording_mbid"] == "None")) &
        (df["artist"].notna() & (df["artist"] != "")) &
        (df["track_name"].notna() & (df["track_name"] != ""))
    )

    unique_rows = df.loc[mask_missing, ["artist", "track_name", "album"]].drop_duplicates()

    total = len(unique_rows)
    resolved_count = 0
    failed_count = 0
    results_map = {}

    for i, (_, row) in enumerate(unique_rows.iterrows()):
        if is_cancelled and is_cancelled():
            break

        artist = str(row["artist"])
        track = str(row["track_name"])
        album = str(row["album"])

        key = parsing.make_track_key(artist, track, album)

        if key in results_map: continue

        if progress_callback:
            progress_callback(i, total, f"Resolving: {artist} - {track}...")

        # API Call
        res = mb_client.search_recording_details(artist, track, album)
        if res:
            results_map[key] = res
            resolved_count += 1
        else:
            results_map[key] = None
            failed_count += 1

    def applicator(row):
        existing_mbid = row.get("recording_mbid")
        existing_album = row.get("album")

        if existing_mbid and str(existing_mbid) != "None" and str(existing_mbid) != "":
            return pd.Series([existing_mbid, existing_album], index=["recording_mbid", "album"])

        k = parsing.make_track_key(row["artist"], row["track_name"], row["album"])
        res = results_map.get(k)

        if res and isinstance(res, dict) and "mbid" in res:
            new_mbid = res["mbid"]
            new_album = res.get("album", existing_album)

            final_album = existing_album
            if str(existing_album).lower() == "unknown":
                final_album = new_album

            return pd.Series([new_mbid, final_album], index=["recording_mbid", "album"])

        return pd.Series([existing_mbid, existing_album], index=["recording_mbid", "album"])

    if not df.empty:
        cols_out = df.apply(applicator, axis=1)
        df["recording_mbid"] = cols_out["recording_mbid"]
        df["album"] = cols_out["album"]

    return df, resolved_count, failed_count