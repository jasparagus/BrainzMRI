import zipfile
import json
import pandas as pd
import os
import io
import time
import urllib.parse
import urllib.request
from tkinter import Tk, filedialog
from tqdm import tqdm  # progress bar
from datetime import datetime, UTC, timezone, timedelta


"""
Parses and analyzes music listens exported as a zip from Listenbrainz. 
Generates a "library" of artists/albums/tracks based on listened data.
Enables browsing of listened music, including generating reports of things
like top artists, top albums, top tracks, filtered by time or recency. 

The exported listenbrainz zip file contains 3 items:
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
4. Recording_mbid for cross-linking likes with tracks


ToDo - 

Build a GUI wrapper to live inside a separate file. The GUI should have the following UI elements for generating reports:
  1. A UI element (button) to select (and render an indication after selection) the zip file
  2. A set of inputs for the reporting functions (mins, tracks, group_col, days, topn, etc. in functions "report_top" and "report_artists_threshold")
    * Time Range [Days Ago] - "Start" and "End" boxes that accept a number of days or 0 to filter time range. Defaults: 0 (min) and 365 (max).
    * Minimum Tracks Listened - A box that accepts a number of tracks (accepts 0 or greater). Default: 15.
    * Minimum Listening Hours - A box that accepts a number of hours (accepts 0 to greater). Default: 0.
    * Last Listened [Days Ago] - A box of the same format as "Time Range [Days Ago]"; enables filtering by last listened date. Defaults: 180 (min) & 365 (max).
    * Top N - A box to enter a number for how many items to include in output. Default: 200.
  3. A dropdown to select reporting type ("By Album", "By Artist", "By Track")
  4. An "Analyze" button to generate the filtered report

"""

def select_zip_file():
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
        filetypes=[("ZIP files", "*.zip")]
    )
    return file_path


def parse_listenbrainz_zip(zip_path):
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
    with zipfile.ZipFile(zip_path, 'r') as z:
        # Load user.json
        user_info = json.loads(z.read("user.json").decode("utf-8"))
        
        # Load feedback.jsonl
        feedback = []
        if "feedback.jsonl" in z.namelist():
            with z.open("feedback.jsonl") as f:
                for line in f:
                    feedback.append(json.loads(line.decode("utf-8")))
        
        # Load listens
        listens = []
        for name in z.namelist():
            if name.startswith("listens/") and name.endswith(".jsonl"):
                with z.open(name) as f:
                    for line in f:
                        listens.append(json.loads(line.decode("utf-8")))
    
    return user_info, feedback, listens


def filter_by_days(df, col, start_days=0, end_days=365):
    """
    Filter a DataFrame by a datetime column using a "days ago" range.
    start_days = minimum days ago (e.g., 0)
    end_days   = maximum days ago (e.g., 365)
    """
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=end_days)
    end_dt = now - timedelta(days=start_days)
    return df[(df[col] >= start_dt) & (df[col] <= end_dt)]


def load_genre_cache(cache_path):
    """
    Load the genre cache from disk if it exists.

    Parameters
    ----------
    cache_path : str
        Path to the JSON cache file.

    Returns
    -------
    dict
        Mapping of artist name → list of genre strings.
    """
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_genre_cache(cache, cache_path):
    """
    Save the genre cache to disk as JSON.

    Parameters
    ----------
    cache : dict
        Mapping of artist name → list of genre strings.
    cache_path : str
        Path where the cache should be written.
    """
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def normalize_listens(listens, zip_path=None):
    """
    Normalize raw ListenBrainz listen objects into a flat DataFrame. 
    Log any items without album info in missing_album_info

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
    
    for idx, l in enumerate(listens):
        meta = l.get("track_metadata", {})
        
        mbid_mapping = meta.get("mbid_mapping") or {}
        artists = []
        if "artists" in mbid_mapping and mbid_mapping["artists"]:
            artists = [a.get("artist_credit_name") for a in mbid_mapping["artists"] if a.get("artist_credit_name")]
        else:
            if meta.get("artist_name"):
                artists = [meta["artist_name"]]
            else:
                print(f"\n[WARN] Missing artist info- Track='{meta.get('track_name','Unknown')}', Album='{meta.get('release_name','Unknown')}'")
                artists = ["Unknown"]
        
        album_name = meta.get("release_name", "Unknown")
        
        if album_name == "Unknown":
            warning = f"[WARN] Unknown album- Artist='{artists[0]}', Track='{meta.get('track_name','Unknown')}', Album='Unknown'"
            if log_file:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(warning + "\n")
        
        # Duration: prefer ms, fallback to s
        info = meta.get("additional_info", {}) or {}
        duration_ms = info.get("duration_ms")
        if duration_ms is None and "duration" in info:
            duration_ms = info["duration"] * 1000
        
        listened_at = l.get("listened_at")
        listened_dt = datetime.fromtimestamp(listened_at, UTC) if listened_at else None
        
        recording_mbid = None
        if "mbid_mapping" in meta and meta["mbid_mapping"]:
            recording_mbid = meta["mbid_mapping"].get("recording_mbid")
        elif "additional_info" in meta and meta["additional_info"].get("lastfm_recording_mbid"):
            recording_mbid = meta["additional_info"]["lastfm_recording_mbid"]

        # Create one record per artist
        for artist in artists:
            records.append({
                "artist": artist,
                "album": album_name,
                "duration_ms": duration_ms or 0,
                "listened_at": listened_dt,
                "recording_mbid": recording_mbid
            })

    
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


def report_artists_with_likes(df, feedback):
    """
    Generate a report of artists with liked recordings.
    NOTE: This report does not use days-based filtering; this should be applied before calling.
    Note: the returned DataFrame preserves the artist name as the index for later use.
    Note: enrich_report_with_genres relies on iterating over report_df.index.

    Parameters
    ----------
    df : pandas.DataFrame
        Normalized listens DataFrame.
    feedback : list of dict
        Raw feedback entries.

    Returns
    -------
    tuple
        (artist_likes_df, metadata)
        
        - artist_likes_df : pandas.DataFrame
            Columns:
            - artist
            - unique_likes
            - total_liked_listens
        - metadata : dict
            Contains entity, topn, days, and metric for filename generation.    
    """
    # Filter listens that were liked
    liked_mbids = load_feedback(feedback)
    liked_listens = df[df["recording_mbid"].isin(liked_mbids)]

    # Unique liked recordings per artist
    unique_likes = (
        liked_listens.groupby("artist")["recording_mbid"]
        .nunique()
        .reset_index(name="unique_likes")
    )

    # Total liked listens per artist
    total_liked_listens = (
        liked_listens.groupby("artist")
        .size()
        .reset_index(name="total_liked_listens")
    )

    # Merge both counts & sort by unique likes
    artist_likes = pd.merge(unique_likes, total_liked_listens, on="artist")
    artist_likes = artist_likes.sort_values(
        ["unique_likes", "total_liked_listens"], ascending=[False, False]
    )

    meta = {
        "entity": "Artists",
        "topn": "Liked",
        "days": None,
        "metric": "Likes"
    }

    return artist_likes, meta


def report_artists_threshold(df, mins=30, tracks=15):
    """
    Filter artists who exceed a minimum listening threshold.
    Threshold based on either of:
    - total listen minutes (default 30)
    - total tracks scrobbled (default 15)

    Parameters
    ----------
    df : pandas.DataFrame
        Normalized listens DataFrame.
    mins : int, optional
        Minimum total listening time in minutes.
    tracks : int, optional
        Minimum number of tracks listened.

    Returns
    -------
    pandas.DataFrame
        Artists meeting the threshold, sorted by total tracks.
    """
    grouped = df.groupby("artist").agg(
    total_tracks=("artist", "count"),
    total_duration_ms=("duration_ms", "sum"),
    last_listened=("listened_at", "max")
    )
    grouped["total_duration_hours"] = (grouped["total_duration_ms"] / (1000 * 60 * 60)).round(1)
    grouped["last_listened"] = grouped["last_listened"].dt.strftime("%Y-%m-%d")
    
    
    filtered = grouped[(grouped.total_tracks > tracks) | (grouped.total_duration_ms > mins*60*1000)]
    return filtered.sort_values("total_tracks", ascending=False)[
        ["total_tracks", "total_duration_hours", "last_listened"]
        ]

def report_top(df, group_col="artist", days=None, by="total_tracks", topn=100):
    """
    Generate a Top-N report for artists or albums.
    Optionally filter by a "last N days" window.

    Parameters
    ----------
    df : pandas.DataFrame
        Normalized listens DataFrame.
    group_col : {"artist", "album"}
        Column to group by.
    days : int or None or tuple, optional
        If provided, restricts listens to the last N days or a range given by tuple
    by : {"total_tracks", "total_duration_hours"}
        Metric used for ranking.
    topn : int
        Number of rows to return.

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
            if start_days == 0 and end_days == 0:
                pass
            else:
                df = filter_by_days(df, "listened_at", start_days, end_days)
        else:
            if days == 0:
                pass
            else:
                df = filter_by_days(df, "listened_at", 0, days)


   
    if group_col == "album":
        grouped = df.groupby(["artist", "album"]).agg(
            total_tracks=("album", "count"),
            total_duration_ms=("duration_ms", "sum"),
            last_listened=("listened_at", "max")
        )
    else:
        grouped = df.groupby("artist").agg(
            total_tracks=("artist", "count"),
            total_duration_ms=("duration_ms", "sum"),
            last_listened=("listened_at", "max")
        )

    grouped["total_duration_hours"] = (grouped["total_duration_ms"] / (1000 * 60 * 60)).round(1)
    grouped["last_listened_dt"] = grouped["last_listened"]
    grouped["last_listened"] = grouped["last_listened"].dt.strftime("%Y-%m-%d")
    grouped = grouped.reset_index()
    if group_col == "album":
        grouped["album"] = grouped["artist"] + " | " + grouped["album"]
        grouped = grouped.drop(columns=["artist"])

    key = by
    result = grouped.sort_values(key, ascending=False).head(topn)

    return result, {
        "entity": "Artists" if group_col == "artist" else "Albums",
        "topn": topn,
        "days": days,
        "metric": "tracks" if by == "total_tracks" else "duration"
    }


def save_report(df, zip_path, meta=None, report_name=None):
    """
    Save a report to the /reports directory with an auto-generated filename.

    Parameters
    ----------
    df : pandas.DataFrame
        Report data to write.
    zip_path : str
        Path to the original ListenBrainz ZIP (used to locate /reports).
    meta : dict, optional
        Metadata returned by report_top(), used to construct filenames.
        Keys:
            - entity : str
            - topn : int
            - days : int or None or tuple
            - metric : str
    report_name : str, optional
        If provided, overrides auto-naming (e.g., "Artists_With_Likes").

    Returns
    -------
    None
        Writes a .txt file to disk.
    """
    base_dir = os.path.dirname(zip_path)
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    if report_name:
        filename = f"{timestamp}_{report_name}.txt"
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

        filename = f"{timestamp}_{entity}_Top{topn}_{range_str}_{metric_str}.txt"

    filepath = os.path.join(reports_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        title = report_name if report_name else filename
        f.write(f"=== {title} ===\n\n")

        # Convert everything to strings for consistent left-justified formatting
        df_str = df.astype(str)

        # Compute column widths (max of header and values)
        col_widths = {}
        for col in df_str.columns:
            max_len = max(len(col), df_str[col].map(len).max())
            col_widths[col] = max_len

        # Write header row
        header_cells = [col.ljust(col_widths[col]) for col in df_str.columns]
        f.write("  ".join(header_cells) + "\n")

        # Write each data row
        for _, row in df_str.iterrows():
            cells = [row[col].ljust(col_widths[col]) for col in df_str.columns]
            f.write("  ".join(cells) + "\n")

    print(f"Report saved to {filepath}")
    return filepath


def get_artist_genres(artist_name):
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


def enrich_report_with_genres(report_df, zip_path, report_name="Artists_Library"):
    """
    Add genre information to an artist report and save it as a CSV.

    Parameters
    ----------
    report_df : pandas.DataFrame
        DataFrame containing artist, total_tracks, and total_duration_hours.
    zip_path : str
        Path to the ListenBrainz ZIP (used to locate /reports).
    report_name : str, optional
        Base name for the output CSV file.

    Returns
    -------
    pandas.DataFrame
        Copy of report_df with an added "Genres" column.
    """
    base_dir = os.path.dirname(zip_path)
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    # Load or initialize cache
    cache_path = os.path.join(reports_dir, "genres_cache.json")
    genre_cache = load_genre_cache(cache_path)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{report_name}.csv"
    out_path = os.path.join(reports_dir, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("Artist,Tracks,Hours,LastListened,Genres\n")

        genres = []
        cache_hits = 0
        api_hits = 0
        api_failures = 0

        with tqdm(total=len(report_df), desc="Enriching artists") as pbar:
            for artist in report_df.index:                
                if artist in genre_cache and genre_cache[artist] != ["Unknown"]:
                    g = genre_cache[artist]
                    cache_hits += 1
                else:
                    g = get_artist_genres(artist)
                    time.sleep(1.2)
                    if not g or g == ["Unknown"]:
                        api_failures += 1
                    else:
                        api_hits += 1

                    genre_cache[artist] = g
                    save_genre_cache(genre_cache, cache_path)

                
                genre_str = "|".join(g)
                genres.append(genre_str)
                
                tracks = report_df.loc[artist, "total_tracks"]
                hours = report_df.loc[artist, "total_duration_hours"]
                last = report_df.loc[artist, "last_listened"]
                
                f.write(f"{artist},{tracks},{hours:.2f},{last},{genre_str}\n")
                f.flush()

                artist_disp = (artist[:15] + "...") if len(artist) > 18 else artist.ljust(18)
                genre_disp  = (genre_str[:20] + "...") if len(genre_str) > 23 else genre_str.ljust(23)

                pbar.set_postfix({
                    "Cache": cache_hits,
                    "API": api_hits,
                    "Fail": api_failures,
                    "Artist": artist_disp,
                    "Genre": genre_disp
                })

                pbar.update(1)

    enriched = report_df.copy()
    enriched["Genres"] = genres
    return out_path, enriched


if __name__ == "__main__":
    zip_path = select_zip_file()
    user_info, feedback, listens = parse_listenbrainz_zip(zip_path)
    df = normalize_listens(listens, zip_path)
    
    artists_df, meta = report_top(df, group_col="artist", days=1000, by="total_tracks", topn=200)
    save_report(artists_df, zip_path, meta=meta)
    
    albums_df, meta = report_top(df, group_col="album", days=365, by="total_tracks", topn=200)
    save_report(albums_df, zip_path, meta=meta)
    
    likes_df, meta = report_artists_with_likes(df, feedback)
    save_report(likes_df, zip_path, meta=meta)

    artist_report = report_artists_threshold(df, mins=30, tracks=15)
    enriched_report = enrich_report_with_genres(artist_report, zip_path)


