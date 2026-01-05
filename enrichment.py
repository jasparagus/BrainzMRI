import json
import os
import time
import urllib.parse
import urllib.request
from tqdm import tqdm
import pandas as pd

from user import get_cache_root


# ------------------------------------------------------------
# Cache Helpers
# ------------------------------------------------------------

def _get_user_genre_cache_path(username: str) -> str:
    """
    Return the path to the user's genre cache file.
    """
    cache_root = get_cache_root()
    user_dir = os.path.join(cache_root, "users", username)
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, "genres_cache.json")


def load_genre_cache(cache_path: str):
    """
    Load the genre cache from disk.

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

    # Newer list-based format
    return data


def save_genre_cache(cache, cache_path: str):
    """Save the genre cache to disk."""
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


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

def enrich_report_with_genres(report_df: pd.DataFrame, username: str, use_api: bool = True):
    """
    Add genre information to an artist-based report.

    Parameters
    ----------
    report_df : DataFrame
        Report DataFrame containing an "artist" column.
    username : str
        The username whose cache directory stores the genre cache.
    use_api : bool
        Whether to query MusicBrainz API for missing genres.

    Returns
    -------
    DataFrame
        Enriched DataFrame with a "Genres" column.
    """
    cache_path = _get_user_genre_cache_path(username)
    genre_cache = load_genre_cache(cache_path)

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
                save_genre_cache(genre_cache, cache_path)

            # Log missing genres
            if g == ["Unknown"]:
                missing_log_path = os.path.join(os.path.dirname(cache_path), "missing_genres.txt")
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

    username = df["_username"].iloc[0]

    # Drop helper column before enrichment
    df = df.drop(columns=["_username"])

    return enrich_report_with_genres(df, username, use_api=use_api)