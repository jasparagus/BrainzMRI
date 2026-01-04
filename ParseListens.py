import zipfile
import json
import pandas as pd
import os
import time
import urllib.parse
import urllib.request
from tkinter import Tk, filedialog
from tqdm import tqdm
from datetime import datetime, UTC, timezone, timedelta


"""
ParseListens.py
Parses and analyzes music listens exported as a zip from ListenBrainz.
Generates a "library" of artists/albums/tracks based on listened data.
Enables browsing of listened music, including generating reports of things
like top artists, top albums, top tracks, filtered by time or recency.

The exported ListenBrainz zip file contains 3 items:
1. "user.json" - a json file with user name and ID; this is unused
2. "feedback.jsonl" - a json lines file with likes and dislikes, each as a distinct line
    * Example row from "feedback.jsonl":
        {"score": 1, "created": 1476644563, "recording_mbid": "25b22e5e-052c-4550-85c6-9c1a7efe5dba", "recording_msid": null}
3. "listens" folder:
    * Contains one subfolder per year (e.g. "2016", "2025")
    * Each year subfolder contains a set of json lines files "1.jsonl", "12.jsonl", etc.
    * Each "*.jsonl" listen file contains listens in the form of single-line json objects
    * Example rows (listens) from a "*.jsonl" file within a year folder:
        {"inserted_at": 1764740348.909054, "listened_at": 1764740227, "track_metadata": {"track_name": "Etched Headplate", "artist_name": "Burial", "mbid_mapping": {"caa_id": 41334538769, "artists": [{"artist_mbid": "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6", "join_phrase": "", "artist_credit_name": "Burial"}], "artist_mbids": ["9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6"], "release_mbid": "e08c3db9-fc33-4d4e-b8b7-818d34228bef", "recording_mbid": "1eacb3ca-e8e1-4588-920d-1187dcb8ca79", "recording_name": "Etched Headplate", "caa_release_mbid": "02aa03a5-001b-4e5a-b3ad-23ad0fadb49c"}, "release_name": "Untrue", "recording_msid": "2b7b424f-b5f5-4ef2-bd2d-e80834708f02", "additional_info": {"duration": 362, "origin_url": "https://music.youtube.com/playlist?list=OLAK5uy_l-q8XlDmU4d7d2dgjpZBYPC-wFFKQTKrA", "submission_client": "Web Scrobbler", "music_service_name": "YouTube Music", "submission_client_version": "3.18.0"}}}
        {"inserted_at": 1762107306.802417, "listened_at": 1762107215, "track_metadata": {"track_name": "I Knew You Were Waiting (For Me)", "artist_name": "George Michael & Aretha Franklin", "mbid_mapping": {"caa_id": 15472428393, "artists": [{"artist_mbid": "ccb8f30e-4d71-40c4-8b1d-846dafe73e2c", "join_phrase": " & ", "artist_credit_name": "George Michael"}, {"artist_mbid": "2f9ecbed-27be-40e6-abca-6de49d50299e", "join_phrase": "", "artist_credit_name": "Aretha Franklin"}], "artist_mbids": ["ccb8f30e-4d71-40c4-8b1d-846dafe73e2c", "2f9ecbed-27be-40e6-abca-6de49d50299e"], "release_mbid": "69205df9-e4c3-41f2-9ff5-ad9714b0c210", "recording_mbid": "e5acf34e-d0eb-4e61-8269-b1d56d81d971", "recording_name": "I Knew You Were Waiting for Me", "caa_release_mbid": "bf240ed0-9e0c-3a44-ab3c-94dc69216af0"}, "release_name": "Aretha (Expanded Edition)", "recording_msid": "db4caef1-f087-4a35-9e79-51b14bffc882", "additional_info": {"duration_ms": 242000, "submission_client": "Pano Scrobbler", "submission_client_version": "4.13"}}}
        {'inserted_at': 1714272371.501321, 'listened_at': 1550646006, 'track_metadata': {'track_name': 'Easy on Me (feat. FATHERDUDE)', 'artist_name': 'Kill Paris', 'mbid_mapping': None, 'release_name': 'Galaxies Within Us', 'recording_msid': '058b6225-8311-4c7f-ad79-d34e1bc334bc', 'additional_info': {'submission_client': 'ListenBrainz lastfm importer', 'lastfm_artist_mbid': 'cfa44aeb-2cfa-40ff-b2bf-cef345312325', 'lastfm_release_mbid': '732b3d57-cdc5-401b-91d4-114b5e009f65'}}}

This module retrieves the following priority items from the listen objects.

1. Artist name(s), e.g. "Burial"
    * This is given by "artist_credit_name" from the list "artists" in "mbid_mapping" object if available
    * Fallback to simple "artist_name" from "track_metadata" if "mbid_mapping" is None
    * If a listen is tagged with multiple artists in "artists" list, count the listen towards the total for each artist separately
2. Album name, e.g. "Untrue" (given by "release_name" from the json object)
3. Track duration (given by "duration_ms", in milliseconds, or "duration", in s, from within "additional_info")
4. recording_mbid for cross-linking likes with tracks
"""


def select_zip_file() -> str:
    """
    Open a file dialog for selecting a ListenBrainz export ZIP file.

    Returns
    -------
    str
        Absolute path to the selected ZIP file, or an empty string if the user cancels.
    """
    root = Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select ListenBrainz Export ZIP",
        filetypes=[("ZIP files", "*.zip")],
    )
    return file_path


def parse_listenbrainz_zip(zip_path: str):
    """
    Parse the ListenBrainz export ZIP and extract user info, feedback, and listens.

    Parameters
    ----------
    zip_path : str
        Path to the ListenBrainz export ZIP file.

    Returns
    -------
    tuple
        (user_info, feedback, listens)
        - user_info : dict
            Parsed contents of user.json.
        - feedback : list of dict
            List of feedback entries from feedback.jsonl.
        - listens : list of dict
            All listen objects extracted from the /listens folder.
    """
    with zipfile.ZipFile(zip_path, "r") as z:
        user_info = json.loads(z.read("user.json").decode("utf-8"))

        feedback = []
        if "feedback.jsonl" in z.namelist():
            with z.open("feedback.jsonl") as f:
                for line in f:
                    feedback.append(json.loads(line.decode("utf-8")))

        listens = []
        for name in z.namelist():
            if name.startswith("listens/") and name.endswith(".jsonl"):
                with z.open(name) as f:
                    for line in f:
                        listens.append(json.loads(line.decode("utf-8")))

    return user_info, feedback, listens


def filter_by_days(df, col: str, start_days: int = 0, end_days: int = 365):
    """
    Filter a DataFrame by a datetime column using a "days ago" range.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame with a datetime-like column.
    col : str
        Name of the datetime column.
    start_days : int
        Minimum days ago (e.g., 0).
    end_days : int
        Maximum days ago (e.g., 365).

    Returns
    -------
    pandas.DataFrame
        Filtered DataFrame.
    """
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=end_days)
    end_dt = now - timedelta(days=start_days)
    return df[(df[col] >= start_dt) & (df[col] <= end_dt)]


def load_genre_cache(cache_path: str):
    """
    Load the genre cache from disk if it exists.

    Parameters
    ----------
    cache_path : str
        Path to the JSON cache file.

    Returns
    -------
    list of dict
        Structured list of cached genre entries. Each entry has:
        - entity : "artist" | "album" | "track"
        - artist, album, track : str or None
        - artist_mbid, release_mbid, recording_mbid : str or None
        - genres : list of str
    """
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Backwards compatibility: old cache was {artist: [genres]}
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


def save_genre_cache(cache, cache_path: str) -> None:
    """
    Save the genre cache to disk as JSON.

    Parameters
    ----------
    cache : list of dict
        Structured list of cached genre entries.
    cache_path : str
        Path where the cache should be written.
    """
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _lookup_artist_entry(cache, artist_name: str):
    """
    Find the first artist entry in the cache matching the given artist name.
    """
    for entry in cache:
        if entry.get("entity") == "artist" and entry.get("artist") == artist_name:
            return entry
    return None


def _get_or_create_artist_entry(cache, artist_name: str):
    """
    Get an artist entry from the cache, creating one if necessary.
    """
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


def normalize_listens(listens, zip_path: str | None = None) -> pd.DataFrame:
    """
    Normalize raw ListenBrainz listen objects into a flat DataFrame.
    Log any items without album info in missing_album_info.

    Parameters
    ----------
    listens : list of dict
        Raw listen objects extracted from the ZIP.
    zip_path : str, optional
        If provided, enables logging of missing album information into
        reports/missing_album_info.txt.

    Returns
    -------
    pandas.DataFrame
        Columns:
        - artist : str
        - album : str
        - track_name : str
        - duration_ms : int
        - listened_at : datetime or None
        - recording_mbid : str or None
    """
    records = []

    log_file = None
    if zip_path:
        base_dir = os.path.dirname(zip_path)
        reports_dir = os.path.join(base_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        log_file = os.path.join(reports_dir, "missing_album_info.txt")

        if os.path.exists(log_file):
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("")
            print(f"[INFO] Purged old missing_album_info log at {log_file}")

    for l in listens:
        meta = l.get("track_metadata", {})

        mbid_mapping = meta.get("mbid_mapping") or {}
        artists = []
        if "artists" in mbid_mapping and mbid_mapping["artists"]:
            artists = [
                a.get("artist_credit_name")
                for a in mbid_mapping["artists"]
                if a.get("artist_credit_name")
            ]
        else:
            if meta.get("artist_name"):
                artists = [meta["artist_name"]]
            else:
                print(
                    f"\n[WARN] Missing artist info- "
                    f"Track='{meta.get('track_name','Unknown')}', "
                    f"Album='{meta.get('release_name','Unknown')}'"
                )
                artists = ["Unknown"]

        album_name = meta.get("release_name", "Unknown")

        if album_name == "Unknown":
            warning = (
                f"[WARN] Unknown album- Artist='{artists[0]}', "
                f"Track='{meta.get('track_name','Unknown')}', Album='Unknown'"
            )
            if log_file:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(warning + "\n")

        # Duration: prefer ms, fallback to seconds
        info = meta.get("additional_info", {}) or {}
        duration_ms = info.get("duration_ms")
        if duration_ms is None and "duration" in info:
            duration_ms = info["duration"] * 1000

        listened_at = l.get("listened_at")
        listened_dt = datetime.fromtimestamp(listened_at, UTC) if listened_at else None

        recording_mbid = None
        if meta.get("mbid_mapping"):
            recording_mbid = meta["mbid_mapping"].get("recording_mbid")
        elif meta.get("additional_info") and meta["additional_info"].get(
            "lastfm_recording_mbid"
        ):
            recording_mbid = meta["additional_info"]["lastfm_recording_mbid"]

        for artist in artists:
            records.append(
                {
                    "artist": artist,
                    "album": album_name,
                    "track_name": meta.get("track_name", "Unknown"),
                    "duration_ms": duration_ms or 0,
                    "listened_at": listened_dt,
                    "recording_mbid": recording_mbid,
                }
            )

    return pd.DataFrame(records)


def load_feedback(feedback):
    """
    Extract the set of liked recording MBIDs from feedback entries.

    Parameters
    ----------
    feedback : list of dict
        Feedback rows from feedback.jsonl.

    Returns
    -------
    set
        Set of recording_mbid values where score == 1.
    """
    likes = set()
    for row in feedback:
        if row.get("score") == 1 and row.get("recording_mbid"):
            likes.add(row["recording_mbid"])
    return likes


def report_artists_with_likes(
    df: pd.DataFrame,
    feedback,
    min_listens: int = 0,
    min_minutes: float = 0.0,
    topn: int | None = None,
):
    """
    Generate a report of artists with liked recordings.

    Days-based and recency filters should be applied to df before calling.
    Thresholds are applied to liked listens only.

    Parameters
    ----------
    df : pandas.DataFrame
        Normalized listens DataFrame.
    feedback : list of dict
        Raw feedback entries.
    min_listens : int
        Minimum number of liked listens per artist.
    min_minutes : float
        Minimum liked listening time per artist (minutes).
    topn : int or None
        If provided, limit to top N rows.

    Returns
    -------
    tuple
        (artist_likes_df, metadata)

        - artist_likes_df : pandas.DataFrame
            Columns:
            - artist
            - unique_likes
            - total_liked_listens
            - liked_duration_hours
        - metadata : dict
            Contains entity, topn, days, and metric for filename generation.
    """
    liked_mbids = load_feedback(feedback)
    liked_listens = df[df["recording_mbid"].isin(liked_mbids)]

    if liked_listens.empty:
        artist_likes = pd.DataFrame(
            columns=[
                "artist",
                "unique_likes",
                "total_liked_listens",
                "liked_duration_hours",
            ]
        )
        meta = {
            "entity": "Artists",
            "topn": "Liked",
            "days": None,
            "metric": "Likes",
        }
        return artist_likes, meta

    grouped = liked_listens.groupby("artist").agg(
        unique_likes=("recording_mbid", "nunique"),
        total_liked_listens=("recording_mbid", "count"),
        liked_duration_ms=("duration_ms", "sum"),
    )
    grouped["liked_duration_hours"] = (
        grouped["liked_duration_ms"] / (1000 * 60 * 60)
    ).round(1)
    grouped = grouped.drop(columns=["liked_duration_ms"])

    # Thresholds on liked listens only
    if min_listens > 0:
        grouped = grouped[grouped["total_liked_listens"] >= min_listens]

    if min_minutes > 0:
        minutes_threshold_hours = min_minutes / 60.0
        grouped = grouped[grouped["liked_duration_hours"] >= minutes_threshold_hours]

    result = (
        grouped.reset_index()
        .sort_values(["unique_likes", "total_liked_listens"], ascending=[False, False])
    )

    if topn is not None:
        result = result.head(topn)

    meta = {
        "entity": "Artists",
        "topn": "Liked" if topn is None else topn,
        "days": None,
        "metric": "Likes",
    }

    return result, meta


def report_top(
    df: pd.DataFrame,
    group_col: str = "artist",
    days=None,
    by: str = "total_tracks",
    topn: int = 100,
    min_listens: int = 0,
    min_minutes: float = 0.0,
):
    """
    Generate a Top-N report for artists, albums, or tracks.

    Parameters
    ----------
    df : pandas.DataFrame
        Normalized listens DataFrame.
    group_col : {"artist", "album", "track"}
        Column to group by.
    days : int, tuple, or None
        If provided, restricts listens to a "days ago" window:
        - int: last N days
        - tuple(start_days, end_days): explicit window
        - None: no additional date filtering
    by : {"total_tracks", "total_duration_hours"}
        Metric used for ranking.
    topn : int
        Number of rows to return.
    min_listens : int
        Minimum number of listens for an entity to be included.
    min_minutes : float
        Minimum total listening time (minutes) for an entity to be included.

    Returns
    -------
    tuple
        (result_df, metadata)

        - result_df : pandas.DataFrame
            Top-N rows sorted by the chosen metric.
        - metadata : dict
            Contains entity, topn, days, and metric for filename generation.
    """
    if days is not None:
        if isinstance(days, tuple):
            start_days, end_days = days
            if not (start_days == 0 and end_days == 0):
                df = filter_by_days(df, "listened_at", start_days, end_days)
        else:
            if days != 0:
                df = filter_by_days(df, "listened_at", 0, days)

    if group_col == "album":
        grouped = df.groupby(["artist", "album"]).agg(
            total_tracks=("album", "count"),
            total_duration_ms=("duration_ms", "sum"),
            last_listened=("listened_at", "max"),
        )
    elif group_col == "track":
        grouped = df.groupby(["artist", "track_name"]).agg(
            total_tracks=("track_name", "count"),
            total_duration_ms=("duration_ms", "sum"),
            last_listened=("listened_at", "max"),
        )
    else:  # artist
        grouped = df.groupby("artist").agg(
            total_tracks=("artist", "count"),
            total_duration_ms=("duration_ms", "sum"),
            last_listened=("listened_at", "max"),
        )

    grouped["total_duration_hours"] = (
        grouped["total_duration_ms"] / (1000 * 60 * 60)
    ).round(1)
    grouped = grouped.drop(columns=["total_duration_ms"]).reset_index()

    if group_col == "artist":
        grouped = grouped[
            ["artist", "total_tracks", "total_duration_hours", "last_listened"]
        ]
    elif group_col == "album":
        grouped = grouped[
            ["artist", "album", "total_tracks", "total_duration_hours", "last_listened"]
        ]
    else:  # track
        grouped = grouped[
            [
                "artist",
                "track_name",
                "total_tracks",
                "total_duration_hours",
                "last_listened",
            ]
        ]

    # Apply unified thresholds
    if min_listens > 0 or min_minutes > 0:
        minutes_threshold_hours = min_minutes / 60.0
        grouped = grouped[
            (grouped["total_tracks"] >= min_listens)
            | (grouped["total_duration_hours"] >= minutes_threshold_hours)
        ]

    key = by
    result = grouped.sort_values(key, ascending=False).head(topn)

    entity = (
        "Artists"
        if group_col == "artist"
        else "Albums"
        if group_col == "album"
        else "Tracks"
    )
    meta = {
        "entity": entity,
        "topn": topn,
        "days": days,
        "metric": "tracks" if by == "total_tracks" else "duration",
    }

    return result, meta


def save_report(df: pd.DataFrame, zip_path: str, meta: dict | None = None, report_name: str | None = None) -> str:
    """
    Save a report to the /reports directory as CSV with an auto-generated filename.

    Parameters
    ----------
    df : pandas.DataFrame
        Report data to write.
    zip_path : str
        Path to the original ListenBrainz ZIP (used to locate /reports).
    meta : dict, optional
        Metadata returned by report_top() or report_artists_with_likes(), used to construct filenames.
        Keys:
            - entity : str
            - topn : int or "Liked"
            - days : int or tuple or None
            - metric : str
    report_name : str, optional
        If provided, overrides auto-naming (e.g., "Artists_With_Likes").

    Returns
    -------
    str
        Path to the written CSV file.
    """
    base_dir = os.path.dirname(zip_path)
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    if report_name:
        filename = f"{timestamp}_{report_name}.csv"
    else:
        entity = meta["entity"]
        topn = meta["topn"]
        days = meta.get("days")
        metric = meta["metric"]

        if days is None:
            range_str = "AllTime"
        elif isinstance(days, tuple):
            start_days, end_days = days
            range_str = f"Range{start_days}-{end_days}days"
        else:
            range_str = f"Last{days}days"

        metric_str = "By" + metric.capitalize()
        filename = f"{timestamp}_{entity}_Top{topn}_{range_str}_{metric_str}.csv"

    filepath = os.path.join(reports_dir, filename)
    df.to_csv(filepath, index=False)

    print(f"Report saved to {filepath}")
    return filepath


def get_artist_genres(artist_name: str):
    """
    Query MusicBrainz for genre tags associated with an artist.

    Parameters
    ----------
    artist_name : str
        Name of the artist to query.

    Returns
    -------
    list of str
        Genre names, or ["Unknown"] if no tags are found or an error occurs.
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
    except Exception as e:
        print(f"\n[WARN] Genre lookup failed for '{artist_name}': {e}")

    return ["Unknown"]


def enrich_report_with_genres(report_df: pd.DataFrame, zip_path: str, use_api: bool = True) -> pd.DataFrame:
    """
    Add genre information to an artist-based report DataFrame.

    This function operates purely in memory. CSV writing is handled separately
    by save_report().

    Parameters
    ----------
    report_df : pandas.DataFrame
        DataFrame containing 'artist' as index or column, plus aggregate stats.
    zip_path : str
        Path to the ListenBrainz ZIP (used to locate /reports).
    use_api : bool
        If True, query MusicBrainz when cache misses occur. If False, use cache only.

    Returns
    -------
    pandas.DataFrame
        Copy of report_df with an added "Genres" column.
    """
    base_dir = os.path.dirname(zip_path)
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    cache_path = os.path.join(reports_dir, "genres_cache.json")
    genre_cache = load_genre_cache(cache_path)

    # Ensure index is artist for iteration
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
                entry["genres"] = g
                save_genre_cache(genre_cache, cache_path)

            genre_str = "|".join(g)
            genres.append(genre_str)

            artist_disp = (artist[:15] + "...") if len(artist) > 18 else artist.ljust(18)
            genre_disp = (genre_str[:20] + "...") if len(genre_str) > 23 else genre_str.ljust(23)

            pbar.set_postfix(
                {
                    "Cache": cache_hits,
                    "API": api_hits,
                    "Fail": api_failures,
                    "Artist": artist_disp,
                    "Genre": genre_disp,
                }
            )
            pbar.update(1)

    enriched = work_df.copy()
    enriched["Genres"] = genres
    enriched = enriched.reset_index()

    return enriched


def enrich_report(df: pd.DataFrame, report_type: str, source: str, zip_path: str) -> pd.DataFrame:
    """
    Generic enrichment entry point.

    Parameters
    ----------
    df : pandas.DataFrame
        Aggregated report DataFrame (artist/album/track/liked artists).
    report_type : {"artist", "album", "track", "liked_artists"}
        Type of report being enriched.
    source : {"Cache", "Query API (Slow)"}
        Whether to query MusicBrainz or use cache only.
    zip_path : str
        Path to the ListenBrainz ZIP (used to locate /reports and cache).

    Returns
    -------
    pandas.DataFrame
        Enriched DataFrame with a "Genres" column.
    """
    use_api = source == "Query API (Slow)"

    # Phase 1: enrichment is always based on artist genres.
    # We expect an 'artist' column to exist.
    if "artist" not in df.columns:
        return df

    return enrich_report_with_genres(df, zip_path, use_api=use_api)


if __name__ == "__main__":
    # Debug / CLI entry point
    zip_path = select_zip_file()
    if not zip_path:
        raise SystemExit("No ZIP file selected.")

    user_info, feedback, listens = parse_listenbrainz_zip(zip_path)
    df = normalize_listens(listens, zip_path)

    artists_df, meta = report_top(
        df,
        group_col="artist",
        days=1000,
        by="total_tracks",
        topn=200,
        min_listens=0,
        min_minutes=0.0,
    )
    save_report(artists_df, zip_path, meta=meta)

    albums_df, meta = report_top(
        df,
        group_col="album",
        days=365,
        by="total_tracks",
        topn=200,
        min_listens=0,
        min_minutes=0.0,
    )
    save_report(albums_df, zip_path, meta=meta)

    likes_df, meta = report_artists_with_likes(
        df,
        feedback,
        min_listens=0,
        min_minutes=0.0,
        topn=None,
    )
    save_report(likes_df, zip_path, meta=meta)

    # Example: thresholded + enriched artist report (for debugging)
    artist_report, _ = report_top(
        df,
        group_col="artist",
        days=None,
        by="total_tracks",
        topn=200,
        min_listens=15,
        min_minutes=30.0,
    )
    enriched_artists = enrich_report(artist_report, "artist", "Cache", zip_path)
    save_report(enriched_artists, zip_path, report_name="Enriched_Artists_Debug")