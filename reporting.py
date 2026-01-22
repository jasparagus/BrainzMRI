"""
reporting.py
Reporting logic for BrainzMRI.

This module is responsible for:
- Aggregating listens data into Top-N reports.
- Calculating statistics (total listens, total hours).
- Filtering data by time range, thresholds, and likes.
- Managing column order.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import time
import os

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------

PREFERRED_COLUMN_ORDER = [
    "artist",
    "album",
    "track_name",
    "total_listens",
    "Likes",                # Unified Integer Column (0, 1, or Count)
    "Genres",
    "last_listened",
    "first_listened",
    "total_hours_listened",
]


# ------------------------------------------------------------
# Time & Recency Filtering
# ------------------------------------------------------------

def filter_by_days(df: pd.DataFrame, col: str, start_days: int = 0, end_days: int = 365) -> pd.DataFrame:
    """Filter a DataFrame by a datetime column using a 'days ago' range."""
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=end_days)
    end_dt = now - timedelta(days=start_days)
    return df[(df[col] >= start_dt) & (df[col] <= end_dt)]


def filter_by_recency(df: pd.DataFrame, entity_cols: list[str], start_days: int, end_days: int) -> pd.DataFrame:
    """
    Filter the DataFrame to include only entities that were *last listened to*
    within the specified 'days ago' window.
    """
    if start_days == 0 and end_days == 0:
        return df

    now = datetime.now(timezone.utc)
    min_dt = now - timedelta(days=end_days)
    max_dt = now - timedelta(days=start_days)

    # 1. Calculate the TRUE last listen date for every entity (ignoring time range filters)
    true_last = (
        df.groupby(entity_cols)["listened_at"]
        .max()
        .reset_index()
        .rename(columns={"listened_at": "true_last_listened"})
    )

    # 2. Find entities where the last listen falls in the window
    allowed = true_last[
        (true_last["true_last_listened"] >= min_dt)
        & (true_last["true_last_listened"] <= max_dt)
    ]

    # 3. Filter original DF to only include those entities
    return df.merge(allowed[entity_cols], on=entity_cols, how="inner")


def filter_by_thresholds(
    df: pd.DataFrame, 
    min_listens: int = 0, 
    min_minutes: float = 0.0,
    min_likes: int = 0
) -> pd.DataFrame:
    """
    Filter aggregated report by metrics.
    Applies OR logic for Activity (Listens OR Minutes) and AND logic for Likes.
    """
    mask = pd.Series(True, index=df.index)
    
    # OR logic for listens/minutes (if either is met, keep it)
    if min_listens > 0 or min_minutes > 0:
        mask_listens = (df["total_listens"] >= min_listens)
        mask_minutes = (df["total_hours_listened"] * 60 >= min_minutes)
        mask = mask_listens | mask_minutes
    
    # AND logic for likes (must be met if set)
    if min_likes > 0:
        if "Likes" in df.columns:
            mask = mask & (df["Likes"] >= min_likes)
        else:
            # If min_likes is requested but data is missing, return empty
            return df.iloc[0:0]
        
    return df[mask]


# ------------------------------------------------------------
# Column Ordering Helper
# ------------------------------------------------------------

def apply_column_order(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder the DataFrame columns according to PREFERRED_COLUMN_ORDER."""
    all_cols = df.columns.tolist()
    ordered_cols = [c for c in PREFERRED_COLUMN_ORDER if c in all_cols]
    remaining_cols = [c for c in all_cols if c not in ordered_cols]
    return df[ordered_cols + remaining_cols]


# ------------------------------------------------------------
# Raw Listens Report
# ------------------------------------------------------------

def report_raw_listens(df: pd.DataFrame, topn: int = None, liked_mbids: set = None):
    """
    Generate a simple Raw Listens report.
    Adds a 'Likes' integer column (1 if liked, 0 if not).
    """
    # Create a copy to safely add columns
    result = df.head(topn).copy() if (topn is not None and topn > 0) else df.copy()
    
    # Calculate Likes column (1/0 Integer)
    if liked_mbids and "recording_mbid" in result.columns:
        result["Likes"] = result["recording_mbid"].apply(
            lambda x: 1 if x in liked_mbids else 0
        )
    else:
        result["Likes"] = 0
    
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

def _compute_likes_count(df: pd.DataFrame, liked_mbids: set, group_col: str) -> pd.DataFrame:
    """
    Compute the number of unique liked tracks for each grouped entity.
    Returns a DataFrame with [entity_cols, 'Likes'].
    """
    if group_col == "artist":
        cols = ["artist"]
    elif group_col == "album":
        cols = ["artist", "album"]
    else:  # track
        cols = ["artist", "track_name"]
    
    empty_cols = cols + ["Likes"]

    if not liked_mbids:
        return pd.DataFrame(columns=empty_cols)

    liked_df = df[df["recording_mbid"].isin(liked_mbids)]
    if liked_df.empty:
        return pd.DataFrame(columns=empty_cols)

    # Count unique recording MBIDs per group
    grouped = liked_df.groupby(cols)["recording_mbid"].nunique().reset_index()
    grouped = grouped.rename(columns={"recording_mbid": "Likes"})
    return grouped


# ------------------------------------------------------------
# Top-N Reports (Artist, Album, Track)
# ------------------------------------------------------------

def _group_listens(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Internal helper to group listens by the specified entity type."""
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
    recency_range: tuple = None,  
):
    """Generate a Top-N report for artists, albums, or tracks."""

    # 1. Filter by Listen Date (Time Range)
    if days is not None:
        if isinstance(days, tuple):
            start_days, end_days = days
            if not (start_days == 0 and end_days == 0):
                df = filter_by_days(df, "listened_at", start_days, end_days)
        else:
            if days != 0:
                df = filter_by_days(df, "listened_at", 0, days)

    # 2. Filter by Last Listened Date (Recency)
    if recency_range:
        start_r, end_r = recency_range
        # 0,0 implies disabled
        if start_r > 0 or end_r > 0:
            if group_col == "artist":
                cols = ["artist"]
            elif group_col == "album":
                cols = ["artist", "album"]
            else: # track
                cols = ["artist", "track_name"]
            
            df = filter_by_recency(df, cols, start_r, end_r)

    # 3. Group and Aggregate
    grouped = _group_listens(df, group_col)

    # FIX: Ensure numeric types for aggregation to avoid TypeError on empty/object columns
    if "total_duration_ms" in grouped.columns:
        grouped["total_duration_ms"] = pd.to_numeric(grouped["total_duration_ms"], errors='coerce').fillna(0)

    grouped["total_hours_listened"] = (
        grouped["total_duration_ms"] / (1000 * 60 * 60)
    ).round(1)

    grouped = grouped.drop(columns=["total_duration_ms"]).reset_index()

    # --- Unified Likes Aggregation ---
    if liked_mbids:
        likes_df = _compute_likes_count(df, liked_mbids, group_col)
        join_cols = ["artist"]
        if group_col == "album": join_cols = ["artist", "album"]
        elif group_col == "track": join_cols = ["artist", "track_name"]

        grouped = grouped.merge(likes_df, on=join_cols, how="left")
        
        # Ensure strict integer type
        if "Likes" in grouped.columns:
            grouped["Likes"] = grouped["Likes"].fillna(0).astype(int)
    else:
        grouped["Likes"] = 0
    
    # --- Threshold Filtering ---
    grouped = filter_by_thresholds(grouped, min_listens, min_minutes, min_likes)

    sorted_df = grouped.sort_values(by, ascending=False)
    result = sorted_df if (topn is None or topn == 0) else sorted_df.head(topn)

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
def report_new_music_by_year(df: pd.DataFrame, **kwargs):
    """
    Generate the 'New Music by Year' report.
    Accepts arbitrary kwargs to safely ignore unused filter arguments.
    """
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Year",
                "Unique Artists", "New Artists", "Percent New Artists",
                "Unique Albums", "New Albums", "Percent New Albums",
                "Unique Tracks", "New Tracks", "Percent New Tracks",
            ]
        ), {
            "entity": "NewMusic",
            "topn": None,
            "days": None,
            "metric": "Yearly",
        }

    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["listened_at"]):
        df["listened_at"] = pd.to_datetime(df["listened_at"], utc=True)
        
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
            "New Artists": na, # RAW COUNT
            "Percent New Artists": pa.round(0).astype(int),
            "Unique Albums": ub,
            "New Albums": nb, # RAW COUNT
            "Percent New Albums": pb.round(0).astype(int),
            "Unique Tracks": ut,
            "New Tracks": nt, # RAW COUNT
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
# Genre Flavor Report (Weighted by Listens)
# ------------------------------------------------------------

def report_genre_flavor(df: pd.DataFrame):
    """
    Generate 'Genre Flavor' report: Top genres weighted by listen counts AND likes.
    Uses Artist-Weighted logic for likes: An artist's total likes are attributed to each of their genres.
    """
    source_col = "Genres" if "Genres" in df.columns else "artist_genres"
    
    if source_col not in df.columns:
        return pd.DataFrame(columns=["Genre", "Listens", "Likes"]), {"entity": "Genre", "metric": "Listens"}

    # Include Likes in the working set if available
    cols_to_use = ["total_listens", source_col]
    if "Likes" in df.columns:
        cols_to_use.append("Likes")
    
    work = df[cols_to_use].copy()
    work = work[work[source_col].notna() & (work[source_col] != "")]
    
    # Ensure Likes is numeric
    if "Likes" in work.columns:
        work["Likes"] = work["Likes"].fillna(0).astype(int)
    else:
        work["Likes"] = 0

    work["Genre"] = work[source_col].astype(str).str.split("|")
    
    exploded = work.explode("Genre")
    exploded["Genre"] = exploded["Genre"].str.strip()
    
    # Aggregate both Listens and Likes per Genre
    grouped = exploded.groupby("Genre")[["total_listens", "Likes"]].sum().reset_index()
    grouped = grouped.rename(columns={"total_listens": "Listens"})
    
    # Sort by Listens primarily, then Likes
    grouped = grouped.sort_values(["Listens", "Likes"], ascending=[False, False]).reset_index(drop=True)
    
    meta = {
        "entity": "Genre",
        "topn": len(grouped),
        "days": None,
        "metric": "weighted_listens"
    }
    
    return grouped, meta


# ------------------------------------------------------------
# Favorite Artist Trend Report (Time Binning)
# ------------------------------------------------------------

def report_artist_trend(df: pd.DataFrame, bins: int = 15, topn: int = 20):
    """
    Generate 'Favorite Artist Trend' report (Tabular format).
    Divides time range into `bins`. For each bin, finds top `topn` artists.
    """
    effective_topn = min(topn, 20) if topn else 20
    
    if df.empty:
        return pd.DataFrame(columns=["Period Start", "Rank", "Artist", "Listens"]), {}

    df = df.copy()
    df["period"] = pd.cut(df["listened_at"], bins=bins)
    
    grouped = df.groupby(["period", "artist"], observed=True).size().reset_index(name="listens")
    grouped = grouped.sort_values(["period", "listens"], ascending=[True, False])
    
    result_rows = []
    periods = grouped["period"].unique()
    
    for p in periods:
        block = grouped[grouped["period"] == p]
        top_block = block.head(effective_topn).copy()
        top_block["Rank"] = range(1, len(top_block) + 1)
        period_str = p.left.strftime("%Y-%m-%d")
        
        for _, row in top_block.iterrows():
            result_rows.append({
                "Period Start": period_str,
                "Rank": row["Rank"],
                "Artist": row["artist"],
                "Listens": row["listens"]
            })
            
    result_df = pd.DataFrame(result_rows, columns=["Period Start", "Rank", "Artist", "Listens"])
    
    meta = {
        "entity": "ArtistTrend",
        "topn": effective_topn,
        "days": None,
        "metric": "trend"
    }
    
    return result_df, meta


def prepare_artist_trend_chart_data(df: pd.DataFrame, bins: int = 15, topn: int = 20) -> pd.DataFrame:
    """
    Prepare data for Stacked Area Chart.
    """
    effective_topn = min(topn, 20) if topn else 20
    
    if df.empty:
        return pd.DataFrame()

    top_artists = df['artist'].value_counts().head(effective_topn).index.tolist()
    df_filtered = df[df['artist'].isin(top_artists)].copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    df_filtered['period'] = pd.cut(df_filtered['listened_at'], bins=bins)
    
    grouped = df_filtered.groupby(['period', 'artist'], observed=True).size().reset_index(name='count')
    pivot = grouped.pivot(index='period', columns='artist', values='count').fillna(0)
    pivot = pivot.reindex(columns=top_artists, fill_value=0)
    
    pivot.index = [p.left.strftime("%Y-%m-%d") for p in pivot.index]
    
    return pivot


# ------------------------------------------------------------
# Saving Reports
# ------------------------------------------------------------

def save_report(df: pd.DataFrame, user, meta: dict = None, report_name: str = None) -> str:
    """Save the DataFrame to a CSV file in the user's reports directory."""
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