import json
import os
import time
import urllib.parse
import urllib.request
from tqdm import tqdm
import pandas as pd


def load_genre_cache(cache_path: str):
    """Load the genre cache from disk."""
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

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

    return []


def save_genre_cache(cache, cache_path: str):
    """Save the genre cache to disk."""
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _lookup_artist_entry(cache, artist_name: str):
    for entry in cache:
        if entry.get("entity") == "artist" and entry.get("artist") == artist_name:
            return entry
    return None


def _get_or_create_artist_entry(cache, artist_name: str):
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


def get_artist_genres(artist_name: str):
    """Query MusicBrainz for genre tags."""
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


def enrich_report_with_genres(report_df: pd.DataFrame, zip_path: str, use_api: bool = True):
    """Add genre information to an artist-based report."""
    base_dir = os.path.dirname(zip_path)
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    cache_path = os.path.join(reports_dir, "genres_cache.json")
    genre_cache = load_genre_cache(cache_path)

    if "artist" in report_df.columns:
        work_df = report_df.set_index("artist")
    else:
        work_df = report_df.copy()

    genres = []
    cache_hits = 0
    api_hits = 0
    api_failures = 0

    with tqdm(total=len(work_df), desc="Enriching artists") as pbar:
        for artist in work_df.index:
            entry = _lookup_artist_entry(genre_cache, artist)
            if entry is not None and entry.get("genres") and entry["genres"] != ["Unknown"]:
                g = entry["genres"]
                cache_hits += 1
            else:
                if use_api:
                    g = get_artist_genres(artist)
                    time.sleep(1.2)
                    if not g or g == ["Unknown"]:
                        api_failures += 1
                    else:
                        api_hits += 1
                else:
                    g = ["Unknown"]
                    api_failures += 1

                entry = _get_or_create_artist_entry(genre_cache, artist)
                if "artist_mbid" in work_df.columns:
                    mbid = work_df.loc[artist, "artist_mbid"]
                    if mbid:
                        entry["artist_mbid"] = mbid
                entry["genres"] = g
                save_genre_cache(genre_cache, cache_path)

            # Missing genre logging
            if g == ["Unknown"]:
                missing_log_path = os.path.join(reports_dir, "missing_genres.txt")
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


def enrich_report(df: pd.DataFrame, report_type: str, source: str, zip_path: str):
    """Generic enrichment entry point."""
    use_api = source == "Query API (Slow)"

    if "artist" not in df.columns:
        return df

    return enrich_report_with_genres(df, zip_path, use_api=use_api)