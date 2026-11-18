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

from config import config  # FIX: Import config for paths

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


def filter_by_recency(
    df: pd.DataFrame, 
    entity_cols: list[str], 
    start_days: int, 
    end_days: int, 
    mode: str = "last"
) -> pd.DataFrame:
    """
    Filter the DataFrame to include only entities based on their aggregated listen date.
    
    Args:
        df: Source DataFrame
        entity_cols: Columns to group by (e.g. ['artist'] or ['artist', 'album'])
        start_days: Start of the 'days ago' window
        end_days: End of the 'days ago' window
        mode: 'last' (Recency/Max) or 'first' (Discovery/Min)
    """
    if start_days == 0 and end_days == 0:
        return df

    now = datetime.now(timezone.utc)
    min_dt = now - timedelta(days=end_days)
    max_dt = now - timedelta(days=start_days)

    # Determine aggregation strategy
    if mode == "first":
        agg_func = "min"
        temp_col = "true_first_listened"
    else:
        agg_func = "max"
        temp_col = "true_last_listened"

    # 1. Calculate the TRUE aggregate date for every entity
    grouped = (
        df.groupby(entity_cols)["listened_at"]
        .agg(agg_func)
        .reset_index()
        .rename(columns={"listened_at": temp_col})
    )

    # 2. Find entities where the aggregate date falls in the window
    allowed = grouped[
        (grouped[temp_col] >= min_dt)
        & (grouped[temp_col] <= max_dt)
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
# Listen Count vs. Time (Moving Average)
# ------------------------------------------------------------

def _format_window_label(window_days: int) -> str:
    """Format a window size in days into a human-readable period string.
    E.g. 1 -> '1 day', 7 -> '1 week', 30 -> '1 month', 14 -> '2 weeks', 45 -> '45 days'.
    """
    if window_days == 1:
        return "1 day"
    if window_days == 7:
        return "1 week"
    if window_days == 14:
        return "2 weeks"
    if window_days == 21:
        return "3 weeks"
    if window_days == 30:
        return "1 month"
    if window_days == 60:
        return "2 months"
    if window_days == 90:
        return "3 months"
    if window_days % 30 == 0 and window_days >= 30:
        months = window_days // 30
        return f"{months} months"
    if window_days % 7 == 0 and window_days >= 7:
        weeks = window_days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''}"
    return f"{window_days} days"


def report_listen_count_vs_time(df: pd.DataFrame, **kwargs) -> tuple:
    """Compute a moving average of daily listen counts.

    The listen timestamps are binned into calendar days, producing a count
    per day.  A centered rolling average is then applied with a window size
    of ``ceil(total_span_days / 15)`` to give a smooth, human-readable
    curve.  The output is normalised to listens-per-day.

    Returns:
        (result_df, meta) where result_df has columns ['date', 'daily_listens']
        and meta contains 'window_days' and 'window_label'.
    """
    import math

    if df.empty or "listened_at" not in df.columns:
        empty = pd.DataFrame(columns=["date", "daily_listens"])
        return empty, {"entity": "listen_rate", "window_days": 1, "window_label": "1 day"}

    work = df[["listened_at"]].copy()
    if not pd.api.types.is_datetime64_any_dtype(work["listened_at"]):
        work["listened_at"] = pd.to_datetime(work["listened_at"], utc=True)

    # Bin into calendar days
    work["date"] = work["listened_at"].dt.normalize()
    daily = work.groupby("date").size().reset_index(name="count")
    daily = daily.sort_values("date").reset_index(drop=True)

    # Determine the span and window size
    date_min = daily["date"].min()
    date_max = daily["date"].max()
    span_days = max(1, (date_max - date_min).days)

    # Fill gaps — ensure every day in the range has an entry (count=0)
    full_range = pd.date_range(start=date_min, end=date_max, freq="D", name="date")
    daily = daily.set_index("date").reindex(full_range, fill_value=0).rename_axis("date").reset_index()

    # Window size: ceil(span / 15), minimum 1
    window_days = max(1, math.ceil(span_days / 15))
    window_label = _format_window_label(window_days)

    # Centered rolling average (already in units of listens/day since each bin = 1 day)
    daily["daily_listens"] = (
        daily["count"]
        .rolling(window=window_days, center=True, min_periods=1)
        .mean()
    )

    result = daily[["date", "daily_listens"]].copy()

    meta = {
        "entity": "listen_rate",
        "window_days": window_days,
        "window_label": window_label,
        "metric": "listen_rate",
    }
    return result, meta


# ------------------------------------------------------------
# Raw Listens Report
# ------------------------------------------------------------

def report_raw_listens(df: pd.DataFrame, topn: int = None, liked_mbids: set = None, **kwargs):
    """
    Generate a simple Raw Listens report.
    Adds a 'Likes' integer column (1 if liked, 0 if not).
    Accepts **kwargs to sink unused filter arguments.
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

    liked_df = df[df["recording_mbid"].isin(liked_mbids)].copy()
    if liked_df.empty:
        return pd.DataFrame(columns=empty_cols)

    # Count unique recording MBIDs per group
    grouped = liked_df.groupby(cols)["recording_mbid"].nunique().reset_index()
    grouped = grouped.rename(columns={"recording_mbid": "Likes"})
    return grouped


# ------------------------------------------------------------
# Top-N Reports (Artist, Album, Track)
# ------------------------------------------------------------

def _normalize_names_by_mbid(df: pd.DataFrame, name_col: str, mbid_col: str) -> pd.DataFrame:
    """Replace name variants with the most-frequent spelling per MBID.

    When the same MBID maps to multiple name spellings (e.g. case variations
    like 'Between The Buried And Me' vs 'Between the Buried and Me'), rows
    with a valid MBID are updated to the most-common spelling.  Rows with
    a missing MBID are left untouched.

    Returns a *copy* of the DataFrame — the original is not mutated.
    """
    if mbid_col not in df.columns or not df[mbid_col].notna().any():
        return df
    if name_col not in df.columns:
        return df

    df = df.copy()

    # Build a mapping: mbid -> most-frequent name spelling
    valid_mask = (
        df[mbid_col].notna() &
        (df[mbid_col].astype(str).str.strip() != "") &
        (df[mbid_col].astype(str).str.lower() != "nan") &
        (df[mbid_col].astype(str).str.lower() != "none")
    )
    if not valid_mask.any():
        return df

    canonical = (
        df[valid_mask]
        .groupby([mbid_col, name_col])
        .size()
        .reset_index(name="_n")
        .sort_values("_n", ascending=False)
        .drop_duplicates(subset=mbid_col, keep="first")
        .set_index(mbid_col)[name_col]
    )

    df.loc[valid_mask, name_col] = df.loc[valid_mask, mbid_col].map(canonical)
    return df


def _group_listens(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Internal helper to group listens by the specified entity type.

    Before grouping, name columns are canonicalized via their MBID
    counterpart so that case variations are merged (see
    _normalize_names_by_mbid).
    """
    # Normalize name columns using MBIDs so case variants merge naturally.
    df = _normalize_names_by_mbid(df, "artist", "artist_mbid")

    if group_col == "album":
        df = _normalize_names_by_mbid(df, "album", "release_mbid")
        grouped = df.groupby(["artist", "album"]).agg(
            total_listens=("album", "count"),
            total_duration_ms=("duration_ms", "sum"),
            first_listened=("listened_at", "min"),
            last_listened=("listened_at", "max"),
            artist_mbid=("artist_mbid", "first"),
            release_mbid=("release_mbid", "first"),
        )

    elif group_col == "track":
        df = _normalize_names_by_mbid(df, "track_name", "recording_mbid")
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
    first_range: tuple = None, 
    **kwargs
):
    """
    Generate a Top-N report for artists, albums, or tracks.
    Accepts **kwargs to sink unused arguments from ReportEngine.
    """

    # 1. Filter by Listen Date (Time Range)
    if days is not None:
        if isinstance(days, tuple):
            start_days, end_days = days
            if not (start_days == 0 and end_days == 0):
                df = filter_by_days(df, "listened_at", start_days, end_days)
        else:
            if days != 0:
                df = filter_by_days(df, "listened_at", 0, days)

    # Prepare columns for grouping/filtering
    if group_col == "artist":
        cols = ["artist"]
    elif group_col == "album":
        cols = ["artist", "album"]
    else: # track
        cols = ["artist", "track_name"]

    # 2. Filter by Last Listened Date (Recency)
    if recency_range:
        start_r, end_r = recency_range
        if start_r > 0 or end_r > 0:
            df = filter_by_recency(df, cols, start_r, end_r, mode="last")

    # 3. Filter by First Listened Date (Discovery)
    if first_range:
        start_f, end_f = first_range
        if start_f > 0 or end_f > 0:
            df = filter_by_recency(df, cols, start_f, end_f, mode="first")

    # 4. Group and Aggregate
    grouped = _group_listens(df, group_col)

    # FIX: Ensure numeric types for aggregation to avoid TypeError on empty/object columns
    if "total_duration_ms" in grouped.columns:
        grouped["total_duration_ms"] = pd.to_numeric(grouped["total_duration_ms"], errors='coerce').fillna(0)

    grouped["total_hours_listened"] = (
        grouped["total_duration_ms"] / (1000 * 60 * 60)
    ).round(1)

    grouped = grouped.drop(columns=["total_duration_ms"]).reset_index()

    # FIX: Ensure join columns are strictly strings to prevent merge errors (float vs object)
    if "artist" in grouped.columns: grouped["artist"] = grouped["artist"].fillna("").astype(str)
    if "album" in grouped.columns: grouped["album"] = grouped["album"].fillna("").astype(str)
    if "track_name" in grouped.columns: grouped["track_name"] = grouped["track_name"].fillna("").astype(str)

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
# Favorite Entity Trend Report (Time Binning)
# ------------------------------------------------------------

def report_entity_trend(df: pd.DataFrame, entity: str = "artist", bins: int = 15, topn: int = 20, **kwargs):
    """
    Generate a Favorite Entity Trend report (Tabular format).
    Divides time range into `bins`. For each bin, finds top `topn` entities.
    `entity` can be "artist", "album", or "track".
    Accepts **kwargs to act as a sink for unused filters (min_listens, etc).
    """
    # Map entity type to DataFrame column and display label
    entity_map = {
        "artist": ("artist", "Artist", "ArtistTrend", "artist_mbid"),
        "album":  ("album",  "Album",  "AlbumTrend",  "release_mbid"),
        "track":  ("track_name", "Track", "TrackTrend", "recording_mbid"),
    }
    group_col, display_label, meta_entity, mbid_col = entity_map.get(entity, entity_map["artist"])

    effective_topn = min(topn, 20) if topn else 20
    
    if df.empty:
        return pd.DataFrame(columns=["Period Start", "Rank", display_label, "Listens"]), {}

    df = df.copy()

    # --- MBID-based data quality ---
    # 1. Filter out rows without a valid MBID (eliminates "Unknown" / unmapped data)
    if mbid_col in df.columns:
        df = df.dropna(subset=[mbid_col])
        df = df[df[mbid_col].str.strip() != ""]
    if df.empty:
        return pd.DataFrame(columns=["Period Start", "Rank", display_label, "Listens"]), {}

    # 2. Resolve canonical display name (most common text name per MBID)
    if mbid_col in df.columns:
        canonical = df.groupby(mbid_col)[group_col].agg(lambda x: x.mode().iloc[0]).rename("_canonical")
        df = df.merge(canonical, left_on=mbid_col, right_index=True, how="left")
        df[group_col] = df["_canonical"]
        df = df.drop(columns=["_canonical"])

    # 3. For album/track, also canonicalize artist and build composite display name
    if entity != "artist" and "artist_mbid" in df.columns:
        artist_canonical = df.groupby("artist_mbid")["artist"].agg(
            lambda x: x.mode().iloc[0]
        ).rename("_artist_canonical")
        df = df.merge(artist_canonical, left_on="artist_mbid", right_index=True, how="left")
        df["artist"] = df["_artist_canonical"].fillna(df["artist"])
        df = df.drop(columns=["_artist_canonical"])
        df[group_col] = df[group_col] + " \u2014 " + df["artist"]

    df["period"] = pd.cut(df["listened_at"], bins=bins)
    
    grouped = df.groupby(["period", group_col], observed=True).size().reset_index(name="listens")
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
                display_label: row[group_col],
                "Listens": row["listens"]
            })
            
    result_df = pd.DataFrame(result_rows, columns=["Period Start", "Rank", display_label, "Listens"])
    
    meta = {
        "entity": meta_entity,
        "topn": effective_topn,
        "days": None,
        "metric": "trend"
    }
    
    return result_df, meta

# Backward-compatible alias
report_artist_trend = report_entity_trend


def prepare_entity_trend_chart_data(df: pd.DataFrame, entity: str = "artist", bins: int = 15, topn: int = 20) -> pd.DataFrame:
    """
    Prepare data for Stacked Area Chart.
    `entity` can be "artist", "album", or "track".
    """
    col_map = {"artist": "artist", "album": "album", "track": "track_name"}
    mbid_map = {"artist": "artist_mbid", "album": "release_mbid", "track": "recording_mbid"}
    group_col = col_map.get(entity, "artist")
    mbid_col = mbid_map.get(entity, "artist_mbid")

    effective_topn = min(topn, 20) if topn else 20
    
    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    # --- MBID-based data quality ---
    # 1. Filter out rows without a valid MBID
    if mbid_col in df.columns:
        df = df.dropna(subset=[mbid_col])
        df = df[df[mbid_col].str.strip() != ""]
    if df.empty:
        return pd.DataFrame()

    # 2. Resolve canonical display name (most common text name per MBID)
    if mbid_col in df.columns:
        canonical = df.groupby(mbid_col)[group_col].agg(lambda x: x.mode().iloc[0]).rename("_canonical")
        df = df.merge(canonical, left_on=mbid_col, right_index=True, how="left")
        df[group_col] = df["_canonical"]
        df = df.drop(columns=["_canonical"])

    # 3. For album/track, also canonicalize artist and build composite display name
    if entity != "artist" and "artist_mbid" in df.columns:
        artist_canonical = df.groupby("artist_mbid")["artist"].agg(
            lambda x: x.mode().iloc[0]
        ).rename("_artist_canonical")
        df = df.merge(artist_canonical, left_on="artist_mbid", right_index=True, how="left")
        df["artist"] = df["_artist_canonical"].fillna(df["artist"])
        df = df.drop(columns=["_artist_canonical"])
        df[group_col] = df[group_col] + " \u2014 " + df["artist"]

    top_entities = df[group_col].value_counts().head(effective_topn).index.tolist()
    df_filtered = df[df[group_col].isin(top_entities)].copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    # Drop rows with missing timestamps — NaT causes pd.cut to produce NaN bin edges
    df_filtered = df_filtered.dropna(subset=['listened_at'])
    if df_filtered.empty:
        return pd.DataFrame()

    df_filtered['period'] = pd.cut(df_filtered['listened_at'], bins=bins)
    
    grouped = df_filtered.groupby(['period', group_col], observed=True).size().reset_index(name='count')
    pivot = grouped.pivot(index='period', columns=group_col, values='count').fillna(0)
    pivot = pivot.reindex(columns=top_entities, fill_value=0)
    
    pivot.index = [p.left.strftime("%Y-%m-%d") for p in pivot.index]
    
    return pivot

# Backward-compatible alias
prepare_artist_trend_chart_data = prepare_entity_trend_chart_data


# ------------------------------------------------------------
# Cross-Service Likes Audit Report
# ------------------------------------------------------------

def _build_history_indexes(df: pd.DataFrame) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    """
    Build O(1) lookup dictionaries from listening history DataFrame:
      1. mbid_to_hist: recording_mbid -> best row dict
      2. name_to_hist: (artist_lower, track_lower) -> best row dict
    Prioritizes rows with non-empty recording_mbid, album, artist_mbid, and release_mbid.
    """
    mbid_to_hist: dict[str, dict] = {}
    name_to_hist: dict[tuple[str, str], dict] = {}

    if df is None or df.empty:
        return mbid_to_hist, name_to_hist

    cols = [c for c in ["artist", "track_name", "album", "recording_mbid", "artist_mbid", "release_mbid"] if c in df.columns]
    if not cols:
        return mbid_to_hist, name_to_hist

    dedup_df = df[cols].drop_duplicates()

    def _clean_field(val: object) -> str:
        if val is None or pd.isna(val):
            return ""
        s = str(val).strip()
        return "" if s.lower() in ("nan", "none", "") else s

    mbid_scores: dict[str, int] = {}
    name_scores: dict[tuple[str, str], int] = {}

    for row_tuple in dedup_df.itertuples(index=False):
        row_dict = row_tuple._asdict()
        artist = _clean_field(row_dict.get("artist"))
        track = _clean_field(row_dict.get("track_name"))
        album = _clean_field(row_dict.get("album"))
        if album.lower() == "unknown":
            album = ""
        rec_mbid = _clean_field(row_dict.get("recording_mbid"))
        art_mbid = _clean_field(row_dict.get("artist_mbid"))
        rel_mbid = _clean_field(row_dict.get("release_mbid"))

        score = (
            (4 if rec_mbid else 0) +
            (2 if artist else 0) +
            (2 if track else 0) +
            (2 if album else 0) +
            (1 if art_mbid else 0) +
            (1 if rel_mbid else 0)
        )

        entry = {
            "artist": artist,
            "track_name": track,
            "album": album,
            "recording_mbid": rec_mbid,
            "artist_mbid": art_mbid,
            "release_mbid": rel_mbid,
        }

        if rec_mbid and score > mbid_scores.get(rec_mbid, -1):
            mbid_scores[rec_mbid] = score
            mbid_to_hist[rec_mbid] = entry

        if artist and track:
            norm_key = (artist.lower(), track.lower())
            if score > name_scores.get(norm_key, -1):
                name_scores[norm_key] = score
                name_to_hist[norm_key] = entry

    return mbid_to_hist, name_to_hist


def report_likes(df: pd.DataFrame, liked_mbids: set = None, lastfm_loves: list = None,
                 resolver_cache: dict = None, **kwargs):
    """
    Generate a cross-service Likes audit report.
    
    Args:
        df: User's listening history (used to resolve MBID → artist/track/album).
        liked_mbids: Set of recording MBIDs liked on ListenBrainz.
        lastfm_loves: List of dicts {'artist': str, 'track': str, 'mbid': str|None} from Last.fm.
        resolver_cache: Dict mapping track keys → resolution results (from enrichment.get_resolver_cache).
    
    Returns:
        DataFrame with columns: track_name, artist, album, Last.fm Liked, ListenBrainz Liked, 
        Both Liked, recording_mbid
    """
    import parsing
    
    if liked_mbids is None:
        liked_mbids = set()
    if resolver_cache is None:
        resolver_cache = {}
    
    rows = []  # Will hold the final audit rows

    # Pre-index listening history and resolver cache for O(1) lookups
    mbid_to_hist, name_to_hist = _build_history_indexes(df)

    mbid_to_resolved: dict[str, dict] = {}
    partial_name_to_resolved: dict[tuple[str, str], dict] = {}
    for cache_key, cache_val in resolver_cache.items():
        if isinstance(cache_val, dict) and cache_val.get("mbid"):
            c_mbid = str(cache_val["mbid"]).strip()
            c_artist = str(cache_val.get("artist") or "").strip()
            c_track = str(cache_val.get("track") or "").strip()
            c_album = str(cache_val.get("album") or "").strip()
            if not c_artist or not c_track:
                k_art, k_trk, k_alb = parsing.parse_track_key(cache_key)
                c_artist = c_artist or k_art
                c_track = c_track or k_trk
                c_album = c_album or k_alb
            info = {"mbid": c_mbid, "artist": c_artist, "track": c_track, "album": c_album}
            if c_mbid:
                mbid_to_resolved[c_mbid] = info
            if c_artist and c_track:
                partial_name_to_resolved[(c_artist.lower(), c_track.lower())] = info

    # ------------------------------------------------------------------
    # Step 1: Build LB Likes base from listening history & resolver cache
    # ------------------------------------------------------------------
    if liked_mbids:
        for mbid in liked_mbids:
            hist = mbid_to_hist.get(mbid)
            if hist:
                rows.append({
                    "track_name": hist["track_name"],
                    "artist": hist["artist"],
                    "album": hist["album"],
                    "ListenBrainz Liked": 1,
                    "Last.fm Liked": 0,
                    "recording_mbid": mbid,
                    "artist_mbid": hist["artist_mbid"],
                    "release_mbid": hist["release_mbid"],
                })
                continue

            # Reverse lookup via resolver cache if not directly in history by MBID
            res_info = mbid_to_resolved.get(mbid)
            if res_info:
                c_artist = res_info["artist"]
                c_track = res_info["track"]
                c_album = res_info["album"]
                name_hist = name_to_hist.get((c_artist.lower(), c_track.lower())) if (c_artist and c_track) else None
                if name_hist:
                    rows.append({
                        "track_name": name_hist["track_name"] or c_track,
                        "artist": name_hist["artist"] or c_artist,
                        "album": name_hist["album"] or c_album,
                        "ListenBrainz Liked": 1,
                        "Last.fm Liked": 0,
                        "recording_mbid": mbid,
                        "artist_mbid": name_hist["artist_mbid"],
                        "release_mbid": name_hist["release_mbid"],
                    })
                else:
                    rows.append({
                        "track_name": c_track,
                        "artist": c_artist,
                        "album": c_album,
                        "ListenBrainz Liked": 1,
                        "Last.fm Liked": 0,
                        "recording_mbid": mbid,
                        "artist_mbid": "",
                        "release_mbid": "",
                    })
            else:
                rows.append({
                    "track_name": "",
                    "artist": "",
                    "album": "",
                    "ListenBrainz Liked": 1,
                    "Last.fm Liked": 0,
                    "recording_mbid": mbid,
                    "artist_mbid": "",
                    "release_mbid": "",
                })
    
    # ------------------------------------------------------------------
    # Step 2: Join Last.fm loves (if available)
    # ------------------------------------------------------------------
    if lastfm_loves:
        lb_mbid_to_row: dict[str, int] = {}
        lb_name_to_row: dict[tuple[str, str], int] = {}
        for j, row in enumerate(rows):
            r_mbid = row.get("recording_mbid", "")
            if r_mbid:
                lb_mbid_to_row[r_mbid] = j
            r_art = row.get("artist", "").strip().lower()
            r_trk = row.get("track_name", "").strip().lower()
            if r_art and r_trk:
                lb_name_to_row[(r_art, r_trk)] = j

        for love in lastfm_loves:
            artist = str(love.get("artist") or "").strip()
            track = str(love.get("track") or "").strip()
            lfm_mbid = str(love.get("mbid") or "").strip()
            if lfm_mbid.lower() in ("none", "nan", ""):
                lfm_mbid = ""

            norm_name = (artist.lower(), track.lower()) if (artist and track) else None
            hist = name_to_hist.get(norm_name) if norm_name else None
            hist_mbid = hist["recording_mbid"] if hist else ""

            key = parsing.make_track_key(artist, track, "")
            cached = resolver_cache.get(key)
            if not (isinstance(cached, dict) and cached.get("mbid")) and norm_name:
                cached = partial_name_to_resolved.get(norm_name)

            cache_mbid = str(cached.get("mbid") or "").strip() if isinstance(cached, dict) else ""
            cache_album = str(cached.get("album") or "").strip() if isinstance(cached, dict) else ""

            # Check if this Last.fm love matches an existing row by MBID or case-insensitive name
            match_idx = None
            for candidate_mbid in (lfm_mbid, hist_mbid, cache_mbid):
                if candidate_mbid and candidate_mbid in lb_mbid_to_row:
                    match_idx = lb_mbid_to_row[candidate_mbid]
                    break
            if match_idx is None and norm_name and norm_name in lb_name_to_row:
                match_idx = lb_name_to_row[norm_name]

            if match_idx is not None:
                target = rows[match_idx]
                target["Last.fm Liked"] = 1
                # Backfill missing metadata on unnamed/incomplete rows
                if not target.get("artist"):
                    target["artist"] = (hist["artist"] if hist and hist.get("artist") else artist)
                if not target.get("track_name"):
                    target["track_name"] = (hist["track_name"] if hist and hist.get("track_name") else track)
                if not target.get("album"):
                    target["album"] = (hist["album"] if hist and hist.get("album") else cache_album)
                if not target.get("artist_mbid") and hist:
                    target["artist_mbid"] = hist.get("artist_mbid", "")
                if not target.get("release_mbid") and hist:
                    target["release_mbid"] = hist.get("release_mbid", "")
                if target.get("artist") and target.get("track_name"):
                    lb_name_to_row[(target["artist"].lower(), target["track_name"].lower())] = match_idx
                continue

            # Unmatched Last.fm love: prefer history recording_mbid for alignment, then resolver cache, then Last.fm MBID
            chosen_mbid = hist_mbid or cache_mbid or lfm_mbid or ""
            h_row = mbid_to_hist.get(chosen_mbid) if chosen_mbid else None
            if not h_row:
                h_row = hist

            final_artist = (h_row["artist"] if h_row and h_row.get("artist") else artist)
            final_track = (h_row["track_name"] if h_row and h_row.get("track_name") else track)
            final_album = (h_row["album"] if h_row and h_row.get("album") else cache_album)
            final_artist_mbid = (h_row.get("artist_mbid", "") if h_row else "")
            final_release_mbid = (h_row.get("release_mbid", "") if h_row else "")

            new_idx = len(rows)
            rows.append({
                "track_name": final_track,
                "artist": final_artist,
                "album": final_album,
                "ListenBrainz Liked": 0,
                "Last.fm Liked": 1,
                "recording_mbid": chosen_mbid,
                "artist_mbid": final_artist_mbid,
                "release_mbid": final_release_mbid,
            })
            if chosen_mbid:
                lb_mbid_to_row[chosen_mbid] = new_idx
            if final_artist and final_track:
                lb_name_to_row[(final_artist.lower(), final_track.lower())] = new_idx
    
    # ------------------------------------------------------------------
    # Step 3: Build result DataFrame
    # ------------------------------------------------------------------
    if not rows:
        result = pd.DataFrame(columns=[
            "track_name", "artist", "album", 
            "Last.fm Liked", "ListenBrainz Liked", "Both Liked", 
            "recording_mbid", "artist_mbid", "release_mbid"
        ])
    else:
        result = pd.DataFrame(rows)
        result["Both Liked"] = (
            (result["ListenBrainz Liked"] == 1) & (result["Last.fm Liked"] == 1)
        ).astype(int)
        
        # Ensure integer types
        for col in ["ListenBrainz Liked", "Last.fm Liked", "Both Liked"]:
            result[col] = result[col].fillna(0).astype(int)
        
        # Column order
        col_order = ["track_name", "artist", "album", 
                     "Last.fm Liked", "ListenBrainz Liked", "Both Liked", 
                     "recording_mbid", "artist_mbid", "release_mbid"]
        result = result[[c for c in col_order if c in result.columns]]
    
    meta = {
        "entity": "Likes",
        "topn": None,
        "days": None,
        "metric": "audit",
    }
    
    return result, meta


# ------------------------------------------------------------
# Likes for Days Pipeline & Formatting Helpers
# ------------------------------------------------------------

def format_track_duration(ms: int | float) -> str:
    """Format milliseconds into MM:SS or H:MM:SS."""
    if not ms or pd.isna(ms) or ms <= 0:
        return "0:00"
    total_seconds = int(ms) // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_human_duration(ms: int | float) -> str:
    """Format total duration in milliseconds into human-readable text."""
    if not ms or pd.isna(ms) or ms <= 0:
        return "0 minutes"
    total_seconds = int(ms) // 1000
    minutes = total_seconds // 60
    hours = minutes // 60
    days = hours // 24

    if days >= 1:
        rem_hours = hours % 24
        return f"{days}d {rem_hours}h" if rem_hours else f"{days} days"
    if hours >= 1:
        rem_min = minutes % 60
        return f"{hours}h {rem_min}m" if rem_min else f"{hours} hours"
    if minutes >= 1:
        return f"{minutes} minutes"
    return "< 1 minute"


def get_resolved_likes(
    *,
    df: pd.DataFrame,
    liked_mbids: set,
    lastfm_loves: list = None,
    resolver_cache: dict = None,
    **kwargs
) -> pd.DataFrame:
    """
    Retrieve all resolved likes (ListenBrainz + Last.fm) that possess a valid recording_mbid.
    """
    audit_df, _ = report_likes(
        df=df,
        liked_mbids=liked_mbids,
        lastfm_loves=lastfm_loves,
        resolver_cache=resolver_cache
    )
    if audit_df.empty:
        return audit_df

    # Filter to tracks with non-empty recording_mbid
    mask_resolved = (
        audit_df["recording_mbid"].notna() &
        (audit_df["recording_mbid"] != "") &
        (audit_df["recording_mbid"].str.lower() != "none") &
        (audit_df["recording_mbid"].str.lower() != "nan")
    )
    resolved_df = audit_df[mask_resolved].copy()

    return resolved_df.reset_index(drop=True)


def report_likes_for_days(
    *,
    df: pd.DataFrame,
    resolved_likes_df: pd.DataFrame,
    durations_map: dict[str, int],
    topn: int = 100,
    min_listens: int = 3,
    **kwargs
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """
    Compile 'Likes for Days' Top-N lists for Tracks, Artists, and Albums.

    Args:
        df: User listening history DataFrame.
        resolved_likes_df: DataFrame of resolved likes with recording_mbids.
        durations_map: Dict mapping recording_mbid -> duration_ms.
        topn: Maximum number of rows to return for Top-N lists.
        min_listens: Minimum listen count threshold for a liked track to be included.

    Returns:
        (track_df, artist_df, album_df, meta)
    """
    effective_min_listens = max(1, int(min_listens))

    if resolved_likes_df.empty or df.empty:
        empty_tracks = pd.DataFrame(columns=[
            "track_name", "artist", "album", "Duration", "listens",
            "Total Time", "total_duration_ms", "duration_ms", "Likes", "recording_mbid"
        ])
        empty_artists = pd.DataFrame(columns=[
            "artist", "Likes", "listens", "total_duration_ms", "Total Time", "track_count"
        ])
        empty_albums = pd.DataFrame(columns=[
            "artist", "album", "Likes", "listens", "total_duration_ms", "Total Time", "track_count"
        ])
        return empty_tracks, empty_artists, empty_albums, {
            "entity": "likes_for_days",
            "topn": topn,
            "min_listens": effective_min_listens,
            "metric": "duration",
            "artist_df": empty_artists,
            "album_df": empty_albums,
            "track_df": empty_tracks,
        }

    # 1. Precompute listen counts and fallback durations from history
    mbid_counts = {}
    if "recording_mbid" in df.columns:
        valid_mbids = df[df["recording_mbid"].notna() & (df["recording_mbid"] != "")]["recording_mbid"]
        mbid_counts = valid_mbids.value_counts().to_dict()

    name_counts = {}
    if "artist" in df.columns and "track_name" in df.columns:
        grouped_names = df.groupby([df["artist"].str.lower().str.strip(), df["track_name"].str.lower().str.strip()]).size()
        name_counts = grouped_names.to_dict()

    hist_mbid_dur = {}
    hist_name_dur = {}
    if "duration_ms" in df.columns:
        pos_dur_df = df[pd.to_numeric(df["duration_ms"], errors="coerce").fillna(0) > 0]
        if not pos_dur_df.empty:
            if "recording_mbid" in pos_dur_df.columns:
                valid_m = pos_dur_df[pos_dur_df["recording_mbid"].notna() & (pos_dur_df["recording_mbid"] != "")]
                if not valid_m.empty:
                    hist_mbid_dur = valid_m.groupby("recording_mbid")["duration_ms"].max().to_dict()
            if "artist" in pos_dur_df.columns and "track_name" in pos_dur_df.columns:
                hist_name_dur = pos_dur_df.groupby(
                    [pos_dur_df["artist"].str.lower().str.strip(), pos_dur_df["track_name"].str.lower().str.strip()]
                )["duration_ms"].max().to_dict()

    mbid_to_hist, name_to_hist = _build_history_indexes(df)

    # 2. Build Track list with listen counts and durations
    track_rows = []
    for _, row in resolved_likes_df.iterrows():
        mbid = str(row.get("recording_mbid", "")).strip()
        artist = str(row.get("artist", "")).strip()
        track_name = str(row.get("track_name", "")).strip()
        album = str(row.get("album", "")).strip()
        artist_mbid = str(row.get("artist_mbid", "")).strip()
        release_mbid = str(row.get("release_mbid", "")).strip()

        norm_name = (artist.lower(), track_name.lower()) if (artist and track_name) else None

        # Fallback to history index for missing artist_mbid / release_mbid / album
        if not artist_mbid or not release_mbid or not album:
            h_entry = mbid_to_hist.get(mbid) or (name_to_hist.get(norm_name) if norm_name else None)
            if h_entry:
                if not artist_mbid:
                    artist_mbid = h_entry.get("artist_mbid", "")
                if not release_mbid:
                    release_mbid = h_entry.get("release_mbid", "")
                if not album:
                    album = h_entry.get("album", "")

        # Count listens by MBID or canonical names
        c_mbid = mbid_counts.get(mbid, 0)
        c_name = name_counts.get(norm_name, 0) if norm_name else 0
        listens = max(c_mbid, c_name)

        # Truncate to liked tracks meeting the minimum listen threshold
        if listens < effective_min_listens:
            continue

        # Duration retrieval from duration cache / MusicBrainz, with history fallback
        raw_dur = durations_map.get(mbid, 0)
        duration_ms = int(raw_dur.get("duration_ms", 0) or 0) if isinstance(raw_dur, dict) else int(raw_dur or 0)
        if duration_ms <= 0:
            fallback_d = hist_mbid_dur.get(mbid, 0)
            if fallback_d <= 0 and norm_name:
                fallback_d = hist_name_dur.get(norm_name, 0)
            if fallback_d > 0:
                duration_ms = int(fallback_d)

        total_duration_ms = duration_ms * listens

        track_rows.append({
            "track_name": track_name,
            "artist": artist,
            "album": album,
            "Duration": format_track_duration(duration_ms),
            "listens": int(listens),
            "Total Time": format_human_duration(total_duration_ms),
            "total_duration_ms": int(total_duration_ms),
            "duration_ms": int(duration_ms),
            "Likes": 1,
            "recording_mbid": mbid,
            "artist_mbid": artist_mbid,
            "release_mbid": release_mbid,
        })

    if not track_rows:
        empty_tracks = pd.DataFrame(columns=[
            "track_name", "artist", "album", "Duration", "listens",
            "Total Time", "total_duration_ms", "duration_ms", "Likes", "recording_mbid"
        ])
        empty_artists = pd.DataFrame(columns=[
            "artist", "Likes", "listens", "total_duration_ms", "Total Time", "track_count"
        ])
        empty_albums = pd.DataFrame(columns=[
            "artist", "album", "Likes", "listens", "total_duration_ms", "Total Time", "track_count"
        ])
        return empty_tracks, empty_artists, empty_albums, {
            "entity": "likes_for_days",
            "topn": topn,
            "min_listens": effective_min_listens,
            "metric": "duration",
            "artist_df": empty_artists,
            "album_df": empty_albums,
            "track_df": empty_tracks,
        }

    full_track_df = pd.DataFrame(track_rows)

    # 1. Normalize name columns using MBIDs so case/spelling variants merge
    full_track_df = _normalize_names_by_mbid(full_track_df, "artist", "artist_mbid")
    full_track_df = _normalize_names_by_mbid(full_track_df, "album", "release_mbid")

    # 2. Case-insensitive canonicalization fallback (e.g. for tracks lacking MBID or remaining casing diffs)
    if "artist" in full_track_df.columns and not full_track_df.empty:
        artist_lower_to_canonical = full_track_df.groupby(full_track_df["artist"].str.lower())["artist"].agg(
            lambda s: s.mode().iloc[0] if not s.empty else ""
        ).to_dict()
        full_track_df["artist"] = full_track_df["artist"].str.lower().map(artist_lower_to_canonical)

    if "album" in full_track_df.columns and not full_track_df.empty:
        full_track_df["album"] = full_track_df["album"].fillna("").astype(str).str.strip()
        full_track_df.loc[full_track_df["album"] == "", "album"] = "[Unknown Album]"
        album_lower_to_canonical = full_track_df.groupby(full_track_df["album"].str.lower())["album"].agg(
            lambda s: s.mode().iloc[0] if not s.empty else "[Unknown Album]"
        ).to_dict()
        full_track_df["album"] = full_track_df["album"].str.lower().map(album_lower_to_canonical)

    # Sort by total listen duration descending, then by listen count
    full_track_df = full_track_df.sort_values(
        by=["total_duration_ms", "listens"],
        ascending=[False, False]
    ).reset_index(drop=True)

    # Deduplicate by case-insensitive (artist, track_name) so divergent MBIDs never double-count
    if not full_track_df.empty:
        full_track_df["_dedup_art"] = full_track_df["artist"].str.lower().str.strip()
        full_track_df["_dedup_trk"] = full_track_df["track_name"].str.lower().str.strip()
        non_empty_mask = (full_track_df["_dedup_art"] != "") & (full_track_df["_dedup_trk"] != "")
        deduped_named = full_track_df[non_empty_mask].drop_duplicates(subset=["_dedup_art", "_dedup_trk"], keep="first")
        unnamed = full_track_df[~non_empty_mask]
        full_track_df = pd.concat([deduped_named, unnamed], ignore_index=True).drop(columns=["_dedup_art", "_dedup_trk"])
        full_track_df = full_track_df.sort_values(
            by=["total_duration_ms", "listens"],
            ascending=[False, False]
        ).reset_index(drop=True)

    # 3. Build Artist list from all qualifying liked tracks
    artist_groups = full_track_df.groupby("artist")
    artist_rows = []
    for art_name, grp in artist_groups:
        total_art_duration = grp["total_duration_ms"].sum()
        total_art_listens = grp["listens"].sum()
        unique_likes = len(grp)  # Count of qualifying liked tracks for this artist

        artist_rows.append({
            "artist": art_name,
            "Likes": int(unique_likes),
            "listens": int(total_art_listens),
            "total_duration_ms": int(total_art_duration),
            "Total Time": format_human_duration(total_art_duration),
            "track_count": int(unique_likes),
        })

    full_artist_df = pd.DataFrame(artist_rows)
    if not full_artist_df.empty:
        full_artist_df = full_artist_df.sort_values(
            by=["total_duration_ms", "listens"],
            ascending=[False, False]
        ).reset_index(drop=True)
    else:
        full_artist_df = pd.DataFrame(columns=[
            "artist", "Likes", "listens", "total_duration_ms", "Total Time", "track_count"
        ])

    # 4. Build Album list from all qualifying liked tracks
    album_groups = full_track_df.groupby(["artist", "album"])
    album_rows = []
    for (art_name, alb_name), grp in album_groups:
        total_alb_duration = grp["total_duration_ms"].sum()
        total_alb_listens = grp["listens"].sum()
        unique_likes = len(grp)  # Count of qualifying liked tracks for this album

        album_rows.append({
            "artist": art_name,
            "album": alb_name,
            "Likes": int(unique_likes),
            "listens": int(total_alb_listens),
            "total_duration_ms": int(total_alb_duration),
            "Total Time": format_human_duration(total_alb_duration),
            "track_count": int(unique_likes),
        })

    full_album_df = pd.DataFrame(album_rows)
    if not full_album_df.empty:
        full_album_df = full_album_df.sort_values(
            by=["total_duration_ms", "listens"],
            ascending=[False, False]
        ).reset_index(drop=True)
    else:
        full_album_df = pd.DataFrame(columns=[
            "artist", "album", "Likes", "listens", "total_duration_ms", "Total Time", "track_count"
        ])

    # Apply Top-N truncation
    if topn and topn > 0:
        top_track_df = full_track_df.head(topn).copy()
        top_artist_df = full_artist_df.head(topn).copy()
        top_album_df = full_album_df.head(topn).copy()
    else:
        top_track_df = full_track_df.copy()
        top_artist_df = full_artist_df.copy()
        top_album_df = full_album_df.copy()

    meta = {
        "entity": "likes_for_days",
        "topn": topn,
        "min_listens": effective_min_listens,
        "metric": "duration",
        "artist_df": top_artist_df,
        "album_df": top_album_df,
        "track_df": top_track_df,
    }

    return top_track_df, top_artist_df, top_album_df, meta


# ------------------------------------------------------------
# Saving Reports
# ------------------------------------------------------------

def save_report(df: pd.DataFrame, user, meta: dict = None, report_name: str = None) -> str:
    """Save the DataFrame to a CSV file in the reports directory."""
    reports_dir = config.reports_dir
    os.makedirs(reports_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    username = ""
    if user:
        if isinstance(user, str):
            username = user
        elif hasattr(user, "username") and user.username:
            username = user.username

    prefix = f"{username}_{timestamp}" if username else timestamp

    if report_name:
        filename = f"{prefix}_{report_name}.csv"
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
        filename = f"{prefix}_{topn_str}_{entity}_{range_str}_{metric_str}.csv"

    filepath = os.path.join(reports_dir, filename)
    df.to_csv(filepath, index=False)
    print(f"Report saved to {filepath}")
    return filepath