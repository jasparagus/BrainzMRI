import json
import os
import time
import urllib.parse
import urllib.request
from tqdm import tqdm
import pandas as pd

from user import get_cache_root


# ------------------------------------------------------------
# Global Cache Helpers
# ------------------------------------------------------------

# Registry of global cache files (extensible)
_GLOBAL_CACHE_FILES = {
    "genres": "genres_cache.json",
    # Future caches can be added here:
    # "artists": "artist_cache.json",
    # "albums": "album_cache.json",
    # "tracks": "track_cache.json",
    # "failures": "lookup_failures.json",
}


def get_global_cache_path(cache_type: str) -> str:
    """
    Return the full path to a global cache file of the given type.
    Creates the global cache directory if needed.
    """
    cache_root = get_cache_root()
    global_dir = os.path.join(cache_root, "global")
    os.makedirs(global_dir, exist_ok=True)

    filename = _GLOBAL_CACHE_FILES.get(cache_type)
    if filename is None:
        raise ValueError(f"Unknown global cache type: {cache_type}")

    return os.path.join(global_dir, filename)


# ------------------------------------------------------------
# Genre Cache Load/Save
# ------------------------------------------------------------

def load_genre_cache():
    """
    Load the global genre cache.

    Returns
    -------
    list[dict]
        List of cache entries with fields:
        - entity
        - artist
        - album
        - track
        - artist_mbid
        - release_mbid
        - recording_mbid
        - genres
    """
    cache_path = get_global_cache_path("genres")

    if not os.path.exists(cache_path):
        return []

    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Legacy format: { "Artist Name": ["genre1", "genre2"] }
    if isinstance(data, dict):
        converted = []
        for artist, genres in data.items():
            converted.append(
                {
                    "entity": "artist",
                    "artist": artist,
                    "album": None,
                    "track": None,
                    "artist_mbid": None,
                    "release_mbid": None,
                    "recording_mbid": None,
                    "genres": genres,
                }
            )
        return converted

    return data


def save_genre_cache(cache):
    """Save the global genre cache to disk."""
    cache_path = get_global_cache_path("genres")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------
# Cache Entry Helpers
# ------------------------------------------------------------

def _lookup_artist_entry(cache, artist_name: str):
    """Return the cache entry for the given artist, or None."""
    for entry in cache:
        if entry.get("entity") == "artist" and entry.get("artist") == artist_name:
            return entry
    return None


def _get_or_create_artist_entry(cache, artist_name: str):
    """Return an existing cache entry or create a new one."""
    entry = _lookup_artist_entry(cache, artist_name)
    if entry is None:
        entry = {
            "entity": "artist",
            "artist": artist_name,
            "album": None,
            "track": None,
            "artist_mbid": None,
            "release_mbid": None,
            "recording_mbid": None,
            "genres": ["Unknown"],
        }
        cache.append(entry)
    return entry


# ------------------------------------------------------------
# API Lookup
# ------------------------------------------------------------

def get_artist_genres(artist_name: str):
    """
    Query MusicBrainz for genre tags.

    Returns
    -------
    list[str]
        List of genre names, or ["Unknown"] if unavailable.
    """
    query = urllib.parse.quote(artist_name)
    url = f"https://musicbrainz.org/ws/2/artist/?query={query}&fmt=json"

    try:
        with urllib.request.urlopen(url) as resp:
            data = json.load(resp)
            if "artists" in data and data["artists"]:
                artist = data["artists"][0]
                tags = artist.get("tags", [])
                return [t["name"] for t in tags] if tags else ["Unknown"]
    except Exception:
        return ["Unknown"]

    return ["Unknown"]


# ------------------------------------------------------------
# Enrichment Logic
# ------------------------------------------------------------

def enrich_report_with_genres(report_df: pd.DataFrame, use_api: bool = True):
    """
    Add genre information to an artist-based report.

    Parameters
    ----------
    report_df : DataFrame
        Report DataFrame containing an "artist" column.
    use_api : bool
        Whether to query MusicBrainz API for missing genres.

    Returns
    -------
    DataFrame
        Enriched DataFrame with a "Genres" column.
    """
    genre_cache = load_genre_cache()

    # Work with artist as index for convenience
    if "artist" in report_df.columns:
        work_df = report_df.set_index("artist")
    else:
        work_df = report_df.copy()

    genres = []

    with tqdm(total=len(work_df), desc="Enriching artists") as pbar:
        for artist in work_df.index:
            entry = _lookup_artist_entry(genre_cache, artist)

            # Cache hit
            if entry is not None and entry.get("genres") and entry["genres"] != ["Unknown"]:
                g = entry["genres"]

            # Cache miss
            else:
                if use_api:
                    g = get_artist_genres(artist)
                    time.sleep(1.2)  # Rate limiting
                else:
                    g = ["Unknown"]

                entry = _get_or_create_artist_entry(genre_cache, artist)

                # Update MBID if available
                if "artist_mbid" in work_df.columns:
                    mbid = work_df.loc[artist, "artist_mbid"]
                    if mbid:
                        entry["artist_mbid"] = mbid

                entry["genres"] = g
                save_genre_cache(genre_cache)

            # Log missing genres
            if g == ["Unknown"]:
                missing_log_path = os.path.join(
                    os.path.dirname(get_global_cache_path("genres")),
                    "missing_genres.txt"
                )
                mbid = entry.get("artist_mbid") or None
                url = f"https://musicbrainz.org/artist/{mbid}" if mbid else "(no MBID available)"
                with open(missing_log_path, "a", encoding="utf-8") as f:
                    f.write(f"{artist}\t{mbid or 'None'}\t{url}\n")

            genres.append("|".join(g))
            pbar.update(1)

    enriched = work_df.copy()
    enriched["Genres"] = genres
    enriched = enriched.reset_index()

    return enriched


def enrich_report(df: pd.DataFrame, report_type: str, source: str):
    """
    Generic enrichment entry point.

    Parameters
    ----------
    df : DataFrame
        Report DataFrame.
    report_type : str
        Report type key ("artist", "album", "track", etc.).
    source : str
        "Cache" or "Query API (Slow)".

    Returns
    -------
    DataFrame
        Enriched DataFrame.
    """
    use_api = source == "Query API (Slow)"

    if "artist" not in df.columns:
        return df

    # The GUI injects the username into the DataFrame before calling this
    if "_username" not in df.columns:
        raise ValueError("Missing _username column for enrichment.")

    # Drop helper column before enrichment
    df = df.drop(columns=["_username"])

    return enrich_report_with_genres(df, use_api=use_api)