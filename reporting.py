"""
Reporting module for BrainzMRI.

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
    """Filter a DataFrame by a datetime column using a 'days ago' range."""
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=end_days)
    end_dt = now - timedelta(days=start_days)
    return df[(df[col] >= start_dt) & (df[col] <= end_dt)]


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

def report_raw_listens(df: pd.DataFrame, topn: int = None):
    """Generate a simple Raw Listens report."""
    result = df.head(topn) if (topn is not None and topn > 0) else df
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
    Refactored to be generic across entity types.
    """
    # Determine the columns to group by
    if group_col == "artist":
        cols = ["artist"]
    elif group_col == "album":
        cols = ["artist", "album"]
    else:  # track
        cols = ["artist", "track_name"]
    
    # Prepare structure for empty returns
    empty_cols = cols + ["unique_liked_tracks"]

    if not liked_mbids:
        return pd.DataFrame(columns=empty_cols)

    liked_df = df[df["recording_mbid"].isin(liked_mbids)]
    if liked_df.empty:
        return pd.DataFrame(columns=empty_cols)

    # Generic aggregation
    grouped = liked_df.groupby(cols)["recording_mbid"].nunique().reset_index()
    grouped = grouped.rename(columns={"recording_mbid": "unique_liked_tracks"})
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
):
    """Generate a Top-N report for artists, albums, or tracks."""

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

    # Likes-based filtering
    if min_likes > 0:
        likes_df = _compute_unique_likes(df, liked_mbids, group_col)
        # Determine join columns based on group_col
        join_cols = ["artist"]
        if group_col == "album": join_cols = ["artist", "album"]
        elif group_col == "track": join_cols = ["artist", "track_name"]

        grouped = grouped.merge(likes_df, on=join_cols, how="left")
        grouped["unique_liked_tracks"] = grouped["unique_liked_tracks"].fillna(0).astype(int)
        grouped = grouped[grouped["unique_liked_tracks"] >= min_likes]

    # Thresholds
    if min_listens > 0 or min_minutes > 0:
        grouped = grouped[
            (grouped["total_listens"] >= min_listens)
            | (grouped["total_hours_listened"] >= (min_minutes / 60.0))
        ]

    sorted_df = grouped.sort_values(by, ascending=False)
    result = sorted_df if (topn is None or topn == 0) else sorted_df.head(topn)

    # Dynamic Column Ordering
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
    """Generate the 'New Music by Year' report."""
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
# Genre Flavor Report (Weighted by Listens)
# ------------------------------------------------------------

def report_genre_flavor(df: pd.DataFrame):
    """
    Generate 'Genre Flavor' report: Top genres weighted by listen counts.
    
    Expected input: An artist-level DataFrame with 'total_listens' and 'Genres' (or 'artist_genres').
    The function explodes the pipe-separated genres and sums the listens for each.
    """
    # Look for the consolidated 'Genres' column first, then fallback to 'artist_genres'
    source_col = "Genres" if "Genres" in df.columns else "artist_genres"
    
    if source_col not in df.columns:
        # Return empty if enrichment didn't happen
        return pd.DataFrame(columns=["Genre", "Listens"]), {"entity": "Genre", "metric": "Listens"}

    # Filter to relevant columns and copy to avoid side effects
    work = df[["total_listens", source_col]].copy()
    
    # Remove rows with no genres
    work = work[work[source_col].notna() & (work[source_col] != "")]
    
    # Split pipe-separated string into list
    work["Genre"] = work[source_col].astype(str).str.split("|")
    
    # Explode list into rows (duplicates total_listens for each genre)
    exploded = work.explode("Genre")
    
    # Clean whitespace
    exploded["Genre"] = exploded["Genre"].str.strip()
    
    # Group by Genre and sum listens
    grouped = exploded.groupby("Genre")["total_listens"].sum().reset_index()
    grouped = grouped.rename(columns={"total_listens": "Listens"})
    
    # Sort descending by Listens
    grouped = grouped.sort_values("Listens", ascending=False).reset_index(drop=True)
    
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
    Generate 'Favorite Artist Trend' report.
    Divides the filtered time range into `bins` periods.
    For each period, finds the top `topn` artists.
    
    Note: `topn` is capped at 20 to prevent data overload.
    """
    # Enforce TopN cap (prevent generating massive tables)
    effective_topn = min(topn, 20) if topn else 20
    
    if df.empty:
        return pd.DataFrame(columns=["Period Start", "Rank", "Artist", "Listens"]), {}

    df = df.copy()
    
    # Create time bins
    # pd.cut splits the time range into equal intervals
    df["period"] = pd.cut(df["listened_at"], bins=bins)
    
    # Count listens per artist within each period
    grouped = df.groupby(["period", "artist"], observed=True).size().reset_index(name="listens")
    
    # Sort: Period ascending, Listens descending
    grouped = grouped.sort_values(["period", "listens"], ascending=[True, False])
    
    # Extract top N for each period
    result_rows = []
    periods = grouped["period"].unique()
    
    for p in periods:
        # Get data for this specific period
        block = grouped[grouped["period"] == p]
        
        # Take top N
        top_block = block.head(effective_topn).copy()
        
        # Assign rank (1 to N)
        top_block["Rank"] = range(1, len(top_block) + 1)
        
        # Format date string (Start of period)
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