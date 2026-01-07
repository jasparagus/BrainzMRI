import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import time
import os


# ------------------------------------------------------------
# Time Filtering
# ------------------------------------------------------------

def filter_by_days(df, col: str, start_days: int = 0, end_days: int = 365):
    """
    Filter a DataFrame by a datetime column using a 'days ago' range.

    Parameters
    ----------
    df : DataFrame
        Input DataFrame.
    col : str
        Name of the datetime column.
    start_days : int
        Minimum age in days (0 = now).
    end_days : int
        Maximum age in days.

    Returns
    -------
    DataFrame
        Filtered DataFrame.
    """
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=end_days)
    end_dt = now - timedelta(days=start_days)
    return df[(df[col] >= start_dt) & (df[col] <= end_dt)]


# ------------------------------------------------------------
# Raw Listens Report
# ------------------------------------------------------------

def report_raw_listens(df, topn=None):
    """
    Raw Listens report.
    A simple passthrough of the listens DataFrame after time filtering.
    No grouping, no thresholds, no enrichment.

    Parameters
    ----------
    df : DataFrame
        Canonical listens DataFrame.
    topn : int or None
        Maximum number of rows to return. If None or 0, return all rows.

    Returns
    -------
    result : DataFrame
    meta : dict
    """
    if topn is not None and topn > 0:
        result = df.head(topn)
    else:
        result = df

    meta = {
        "entity": "RawListens",
        "topn": topn if topn else "All",
        "days": None,
        "metric": "none",
    }

    return result, meta


# ------------------------------------------------------------
# Helper: Compute unique liked tracks per entity
# ------------------------------------------------------------

def _compute_unique_likes(df, liked_mbids, group_col):
    """
    Compute unique liked tracks per entity.

    Parameters
    ----------
    df : DataFrame
        Canonical listens DataFrame.
    liked_mbids : set[str]
        Set of liked recording MBIDs.
    group_col : str
        "artist", "album", or "track".

    Returns
    -------
    DataFrame with columns:
        - entity keys (artist / artist+album / artist+track_name)
        - unique_liked_tracks
    """
    if not liked_mbids:
        # No likes at all → return empty frame with correct columns
        if group_col == "artist":
            return pd.DataFrame(columns=["artist", "unique_liked_tracks"])
        elif group_col == "album":
            return pd.DataFrame(columns=["artist", "album", "unique_liked_tracks"])
        else:
            return pd.DataFrame(columns=["artist", "track_name", "unique_liked_tracks"])

    liked_df = df[df["recording_mbid"].isin(liked_mbids)]
    if liked_df.empty:
        # No liked listens in this filtered dataset
        if group_col == "artist":
            return pd.DataFrame(columns=["artist", "unique_liked_tracks"])
        elif group_col == "album":
            return pd.DataFrame(columns=["artist", "album", "unique_liked_tracks"])
        else:
            return pd.DataFrame(columns=["artist", "track_name", "unique_liked_tracks"])

    if group_col == "artist":
        grouped = liked_df.groupby("artist")["recording_mbid"].nunique().reset_index()
        grouped = grouped.rename(columns={"recording_mbid": "unique_liked_tracks"})
        return grouped

    elif group_col == "album":
        grouped = (
            liked_df.groupby(["artist", "album"])["recording_mbid"]
            .nunique()
            .reset_index()
        )
        grouped = grouped.rename(columns={"recording_mbid": "unique_liked_tracks"})
        return grouped

    else:  # track
        grouped = (
            liked_df.groupby(["artist", "track_name"])["recording_mbid"]
            .nunique()
            .reset_index()
        )
        grouped = grouped.rename(columns={"recording_mbid": "unique_liked_tracks"})
        return grouped


# ------------------------------------------------------------
# Top-N Reports (Artist, Album, Track)
# ------------------------------------------------------------

def _group_listens(df, group_col):
    """
    Internal helper to group listens by artist, album, or track.

    Returns a grouped DataFrame with:
    - total_tracks
    - total_duration_ms
    - first_listened
    - last_listened
    """
    if group_col == "album":
        grouped = df.groupby(["artist", "album"]).agg(
            total_tracks=("album", "count"),
            total_duration_ms=("duration_ms", "sum"),
            first_listened=("listened_at", "min"),
            last_listened=("listened_at", "max"),
        )

    elif group_col == "track":
        grouped = df.groupby(["artist", "track_name"]).agg(
            total_tracks=("track_name", "count"),
            total_duration_ms=("duration_ms", "sum"),
            first_listened=("listened_at", "min"),
            last_listened=("listened_at", "max"),
        )

    else:  # artist
        grouped = df.groupby("artist").agg(
            total_tracks=("artist", "count"),
            total_duration_ms=("duration_ms", "sum"),
            first_listened=("listened_at", "min"),
            last_listened=("listened_at", "max"),
        )

    return grouped


def report_top(
    df,
    group_col="artist",
    days=None,
    by="total_tracks",
    topn=100,
    min_listens=0,
    min_minutes=0.0,
    min_likes=0,
    liked_mbids=None,
):
    """
    Generate a Top-N report for artists, albums, or tracks.

    Parameters
    ----------
    df : DataFrame
        Canonical listens DataFrame.
    group_col : str
        "artist", "album", or "track".
    days : int or tuple or None
        Legacy parameter (GUI handles filtering now).
    by : str
        Sorting metric ("total_tracks" or "total_duration_hours").
    topn : int
        Number of rows to return.
    min_listens : int
        Minimum listens threshold.
    min_minutes : float
        Minimum duration threshold (minutes).
    min_likes   : int
        Minimum likes threshold

    Returns
    -------
    result : DataFrame
    meta : dict
    """

    # Legacy days filtering (kept for CLI compatibility)
    if days is not None:
        if isinstance(days, tuple):
            start_days, end_days = days
            if not (start_days == 0 and end_days == 0):
                df = filter_by_days(df, "listened_at", start_days, end_days)
        else:
            if days != 0:
                df = filter_by_days(df, "listened_at", 0, days)

    grouped = _group_listens(df, group_col)

    grouped["total_duration_hours"] = (
        grouped["total_duration_ms"] / (1000 * 60 * 60)
    ).round(1)

    grouped = grouped.drop(columns=["total_duration_ms"]).reset_index()

    # Column ordering
    if group_col == "artist":
        grouped = grouped[
            ["artist", "total_tracks", "total_duration_hours", "first_listened", "last_listened"]
        ]
    elif group_col == "album":
        grouped = grouped[
            ["artist", "album", "total_tracks", "total_duration_hours", "first_listened", "last_listened"]
        ]
    else:  # track
        grouped = grouped[
            ["artist", "track_name", "total_tracks", "total_duration_hours", "first_listened", "last_listened"]
        ]

    # ------------------------------------------------------------
    # Likes-based filtering (Minimum Likes Threshold)
    # ------------------------------------------------------------
    if min_likes > 0:
        likes_df = _compute_unique_likes(df, liked_mbids, group_col)

        # Merge likes into grouped table
        grouped = grouped.merge(
            likes_df,
            on=["artist"] if group_col == "artist"
            else ["artist", "album"] if group_col == "album"
            else ["artist", "track_name"],
            how="left",
        )

        # Fill missing likes with 0
        grouped["unique_liked_tracks"] = grouped["unique_liked_tracks"].fillna(0).astype(int)

        # Apply likes threshold
        grouped = grouped[grouped["unique_liked_tracks"] >= min_likes]

    # ------------------------------------------------------------
    # Existing thresholds (Minimum Listens OR Minimum Minutes)
    # ------------------------------------------------------------
    if min_listens > 0 or min_minutes > 0:
        grouped = grouped[
            (grouped["total_tracks"] >= min_listens)
            | (grouped["total_duration_hours"] >= (min_minutes / 60.0))
        ]

    sorted_df = grouped.sort_values(by, ascending=False)

    result = sorted_df if (topn is None or topn == 0) else sorted_df.head(topn)

    entity = (
        "Artists" if group_col == "artist"
        else "Albums" if group_col == "album"
        else "Tracks"
    )

    meta = {
        "entity": entity,
        "topn": topn,
        "days": days,
        "metric": "tracks" if by == "total_tracks" else "duration",
    }

    return result, meta


# ------------------------------------------------------------
# New Music by Year Report
# ------------------------------------------------------------
def report_new_music_by_year(df: pd.DataFrame):
    """
    Produce a year-by-year summary of unique artists, albums, and tracks,
    along with the percentage of each that were first listened in that year.
    This report expects the full raw listens dataset.

    """

    if df.empty:
        return pd.DataFrame(
            columns=[
                "Year",
                "Number of Unique Artists", "Percent New Artists",
                "Number of Unique Albums",  "Percent New Albums",
                "Number of Unique Tracks",  "Percent New Tracks",
            ]
        ), {
            "entity": "NewMusic",
            "topn": None,
            "days": None,
            "metric": "Yearly",
        }

    df = df.copy()
    df["year"] = df["listened_at"].dt.year

    min_year = int(df["year"].min())
    max_year = int(df["year"].max())
    all_years = list(range(min_year, max_year + 1))

    df["artist_id"] = df["artist_mbid"].fillna(df["artist"])
    df["album_id"]  = df["release_mbid"].fillna(df["album"])
    df["track_id"]  = df["recording_mbid"].fillna(df["track_name"])

    first_artist_year = df.groupby("artist_id")["listened_at"].min().dt.year
    first_album_year  = df.groupby("album_id")["listened_at"].min().dt.year
    first_track_year  = df.groupby("track_id")["listened_at"].min().dt.year

    artists_by_year = df.groupby("year")["artist_id"].nunique()
    albums_by_year  = df.groupby("year")["album_id"].nunique()
    tracks_by_year  = df.groupby("year")["track_id"].nunique()

    new_artists_by_year = first_artist_year.value_counts()
    new_albums_by_year  = first_album_year.value_counts()
    new_tracks_by_year  = first_track_year.value_counts()

    rows = []
    for y in all_years:
        ua = artists_by_year.get(y, 0)
        na = new_artists_by_year.get(y, 0)
        pa = (na / ua)*100 if ua > 0 else np.nan

        ub = albums_by_year.get(y, 0)
        nb = new_albums_by_year.get(y, 0)
        pb = (nb / ub)*100 if ub > 0 else np.nan

        ut = tracks_by_year.get(y, 0)
        nt = new_tracks_by_year.get(y, 0)
        pt = (nt / ut)*100 if ut > 0 else np.nan

        rows.append({
            "Year": y,
            "Unique Artists": ua,
            "Percent New Artists": pa.round(0).astype(int),
            "Unique Albums": ub,
            "Percent New Albums": pb.round(0).astype(int),
            "Unique Tracks": ut,
            "Percent New Tracks": pt.round(0).astype(int),
        })

    df_out = pd.DataFrame(rows)

    meta = {
        "entity": "NewMusic",
        "topn": None,
        "days": None,
        "metric": "Yearly",
    }

    result = df_out.sort_values("Year").reset_index(drop=True)
    return result, meta


# ------------------------------------------------------------
# Saving Reports
# ------------------------------------------------------------

def save_report(df, user, meta=None, report_name=None):
    """
    Save a report to the user's reports directory as CSV.

    Parameters
    ----------
    df : DataFrame
    user : User
        The User object whose cache directory will contain the report.
    meta : dict or None
    report_name : str or None

    Returns
    -------
    filepath : str
    """
    reports_dir = os.path.join(user.cache_dir, "reports")
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
            range_str = f"Range{days[0]}-{days[1]}days"
        else:
            range_str = f"Last{days}days"

        if (topn is None or topn == 0):
            topn_str = "All"
        else:
            topn_str = f"Top{topn}"

        metric_str = "By" + metric.capitalize()
        filename = f"{timestamp}_{topn_str}_{entity}_{range_str}_{metric_str}.csv"

    filepath = os.path.join(reports_dir, filename)
    df.to_csv(filepath, index=False)
    print(f"Report saved to {filepath}")
    return filepath