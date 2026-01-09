"""
Reporting module for BrainzMRI.

This module is responsible for:
- Aggregating listens data into Top-N reports (Artist/Album/Track).
- Calculating statistics (total listens, total hours).
- Filtering data by time range, thresholds, and likes.
- Managing column order and presentation.
- Generating the "New Music by Year" analysis.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import time
import os


# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------

# Define preferred hierarchy for column ordering
PREFERRED_COLUMN_ORDER = [
    "artist",
    "album",
    "track_name",
    "total_listens",
    "total_hours_listened",
    "unique_liked_tracks",
    "last_listened",
    "first_listened",
    "Genres",
]


# ------------------------------------------------------------
# Time Filtering
# ------------------------------------------------------------

def filter_by_days(df: pd.DataFrame, col: str, start_days: int = 0, end_days: int = 365) -> pd.DataFrame:
    """
    Filter a DataFrame by a datetime column using a 'days ago' range.

    Parameters
    ----------
    df : pd.DataFrame
        The input DataFrame containing the listens data.
    col : str
        The name of the datetime column to filter on (e.g., 'listened_at').
    start_days : int, optional
        The start of the range in days ago (0 = now), by default 0.
    end_days : int, optional
        The end of the range in days ago, by default 365.

    Returns
    -------
    pd.DataFrame
        The subset of `df` falling within the calculated date range.
    """
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=end_days)
    end_dt = now - timedelta(days=start_days)
    return df[(df[col] >= start_dt) & (df[col] <= end_dt)]


# ------------------------------------------------------------
# Column Ordering Helper
# ------------------------------------------------------------

def apply_column_order(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reorder the DataFrame columns according to PREFERRED_COLUMN_ORDER.
    
    Columns listed in PREFERRED_COLUMN_ORDER are placed first, in that order.
    Any columns in the DataFrame that are NOT in the preferred list (e.g. MBIDs, 
    specific genre columns) are appended to the end.

    Parameters
    ----------
    df : pd.DataFrame
        The DataFrame to reorder.

    Returns
    -------
    pd.DataFrame
        The reordered DataFrame.
    """
    all_cols = df.columns.tolist()
    
    # 1. Select columns that exist in the preferred list, in order
    ordered_cols = [c for c in PREFERRED_COLUMN_ORDER if c in all_cols]
    
    # 2. Append any remaining columns at the end
    remaining_cols = [c for c in all_cols if c not in ordered_cols]
    
    return df[ordered_cols + remaining_cols]


# ------------------------------------------------------------
# Raw Listens Report
# ------------------------------------------------------------

def report_raw_listens(df: pd.DataFrame, topn: int = None):
    """
    Generate a simple Raw Listens report.
    
    This is a passthrough report that applies no grouping or aggregation, 
    useful for inspecting the underlying data after filters are applied.

    Parameters
    ----------
    df : pd.DataFrame
        The filtered listens DataFrame.
    topn : int, optional
        Limit the output to the top N rows, by default None (all rows).

    Returns
    -------
    tuple
        (result_df, meta_dict)
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

def _compute_unique_likes(df: pd.DataFrame, liked_mbids: set, group_col: str) -> pd.DataFrame:
    """
    Compute the number of unique liked tracks for each grouped entity.

    Parameters
    ----------
    df : pd.DataFrame
        The listens DataFrame.
    liked_mbids : set
        A set of recording MBIDs that the user has liked.
    group_col : str
        The grouping level ('artist', 'album', or 'track').

    Returns
    -------
    pd.DataFrame
        A DataFrame with the grouping keys and a 'unique_liked_tracks' count column.
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

def _group_listens(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    Internal helper to group listens by the specified entity type.
    
    This function handles the aggregation of stats (listens, duration)
    and the propagation of metadata (MBIDs, first/last listen dates).

    Parameters
    ----------
    df : pd.DataFrame
        The listens DataFrame.
    group_col : str
        'artist', 'album', or 'track'.

    Returns
    -------
    pd.DataFrame
        The aggregated DataFrame.
    """
    if group_col == "album":
        grouped = df.groupby(["artist", "album"]).agg(
            total_listens=("album", "count"),
            total_duration_ms=("duration_ms", "sum"),
            first_listened=("listened_at", "min"),
            last_listened=("listened_at", "max"),
            artist_mbid=("artist_mbid", "first"),
            release_mbid=("release_mbid", "first"),
        )

    elif group_col == "track":
        grouped = df.groupby(["artist", "track_name"]).agg(
            total_listens=("track_name", "count"),
            total_duration_ms=("duration_ms", "sum"),
            first_listened=("listened_at", "min"),
            last_listened=("listened_at", "max"),
            album=("album", "first"), 
            artist_mbid=("artist_mbid", "first"),
            release_mbid=("release_mbid", "first"),
            recording_mbid=("recording_mbid", "first"),
        )

    else:  # artist
        grouped = df.groupby("artist").agg(
            total_listens=("artist", "count"),
            total_duration_ms=("duration_ms", "sum"),
            first_listened=("listened_at", "min"),
            last_listened=("listened_at", "max"),
            artist_mbid=("artist_mbid", "first"),
        )

    return grouped


def report_top(
    df: pd.DataFrame,
    group_col: str = "artist",
    days=None,
    by: str = "total_listens",
    topn: int = 100,
    min_listens: int = 0,
    min_minutes: float = 0.0,
    min_likes: int = 0,
    liked_mbids: set = None,
):
    """
    Generate a Top-N report for artists, albums, or tracks.
    
    Applies thresholds, sorting, and dynamic column ordering.

    Parameters
    ----------
    df : pd.DataFrame
        The listens DataFrame.
    group_col : str, optional
        'artist', 'album', or 'track'.
    days : int, optional
        Legacy days filter (typically None if filtered upstream).
    by : str, optional
        Column to sort by, usually 'total_listens'.
    topn : int, optional
        Number of results to return.
    min_listens : int, optional
        Filter out entities with fewer than N listens.
    min_minutes : float, optional
        Filter out entities listened to for less than N minutes.
    min_likes : int, optional
        Filter out entities with fewer than N unique liked tracks.
    liked_mbids : set, optional
        Set of user liked MBIDs for calculating the likes column.

    Returns
    -------
    tuple
        (result_df, meta_dict)
    """

    # Legacy days filtering
    if days is not None:
        if isinstance(days, tuple):
            start_days, end_days = days
            if not (start_days == 0 and end_days == 0):
                df = filter_by_days(df, "listened_at", start_days, end_days)
        else:
            if days != 0:
                df = filter_by_days(df, "listened_at", 0, days)

    grouped = _group_listens(df, group_col)

    grouped["total_hours_listened"] = (
        grouped["total_duration_ms"] / (1000 * 60 * 60)
    ).round(1)

    grouped = grouped.drop(columns=["total_duration_ms"]).reset_index()

    # ------------------------------------------------------------
    # Likes-based filtering (Minimum Likes Threshold)
    # ------------------------------------------------------------
    if min_likes > 0:
        likes_df = _compute_unique_likes(df, liked_mbids, group_col)
        
        join_cols = ["artist"]
        if group_col == "album":
            join_cols = ["artist", "album"]
        elif group_col == "track":
            join_cols = ["artist", "track_name"]

        grouped = grouped.merge(likes_df, on=join_cols, how="left")
        grouped["unique_liked_tracks"] = grouped["unique_liked_tracks"].fillna(0).astype(int)
        grouped = grouped[grouped["unique_liked_tracks"] >= min_likes]

    # ------------------------------------------------------------
    # Thresholds
    # ------------------------------------------------------------
    if min_listens > 0 or min_minutes > 0:
        grouped = grouped[
            (grouped["total_listens"] >= min_listens)
            | (grouped["total_hours_listened"] >= (min_minutes / 60.0))
        ]

    sorted_df = grouped.sort_values(by, ascending=False)
    result = sorted_df if (topn is None or topn == 0) else sorted_df.head(topn)

    # ------------------------------------------------------------
    # Dynamic Column Ordering
    # ------------------------------------------------------------
    result = apply_column_order(result)

    entity = (
        "Artists" if group_col == "artist"
        else "Albums" if group_col == "album"
        else "Tracks"
    )

    meta = {
        "entity": entity,
        "topn": topn,
        "days": days,
        "metric": "listens" if by == "total_listens" else "duration",
    }

    return result, meta


# ------------------------------------------------------------
# New Music by Year Report
# ------------------------------------------------------------
def report_new_music_by_year(df: pd.DataFrame):
    """
    Generate the 'New Music by Year' report.
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

def save_report(df: pd.DataFrame, user, meta: dict = None, report_name: str = None) -> str:
    """
    Save the DataFrame to a CSV file in the user's reports directory.
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