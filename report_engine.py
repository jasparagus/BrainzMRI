import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, Callable

from datetime import datetime, timedelta, timezone

import reporting
import enrichment


class ReportEngine:
    """
    Encapsulates report generation logic.
    """

    def __init__(self) -> None:
        self._handlers = {
            "By Artist": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "artist", "by": "total_listens"},
                "report_type_key": "artist",
                "status": "Artist report generated.",
            },
            "By Album": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "album", "by": "total_listens"},
                "report_type_key": "album",
                "status": "Album report generated.",
            },
            "By Track": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "track", "by": "total_listens"},
                "report_type_key": "track",
                "status": "Track report generated.",
            },
            "Genre Flavor": {
                "func": reporting.report_genre_flavor, 
                "kwargs": {},
                "report_type_key": "genre_flavor",
                "status": "Genre Flavor report generated.",
            },
            "Favorite Artist Trend": {
                "func": reporting.report_artist_trend,
                "kwargs": {"bins": 15}, 
                "report_type_key": "artist_trend",
                "status": "Artist Trend report generated.",
            },
            "New Music By Year": {
                "func": reporting.report_new_music_by_year,
                "kwargs": {},
                "report_type_key": "new_music_by_year",
                "status": "New Music by Year report generated.",
            },
            "Raw Listens": {
                "func": reporting.report_raw_listens,
                "kwargs": {},
                "report_type_key": "raw",
                "status": "Raw listens displayed.",
            },
        }

    def get_status(self, mode: str) -> str:
        handler = self._handlers.get(mode)
        if not handler:
            return "Report generated."
        return handler.get("status", "Report generated.")

    def generate_report(
        self,
        base_df,
        mode: str,
        liked_mbids,
        *,
        time_start_days: int,
        time_end_days: int,
        rec_start_days: int,
        rec_end_days: int,
        min_listens: int,
        min_minutes: float,
        min_likes: int,
        topn: int,
        do_enrich: bool,
        enrichment_mode: str,
        force_cache_update: bool,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ):
        """
        Generate a report for the given mode and parameters.
        """
        if base_df is None:
            raise ValueError("No listens data available.")

        # Initial progress signal
        if progress_callback:
            progress_callback(0, 100, "Filtering data...")

        df = base_df.copy()

        # Time range filter (on listens)
        if (not (time_start_days == 0 and time_end_days == 0) and
            mode not in ["New Music By Year"]):
            df = reporting.filter_by_days(
                df,
                "listened_at",
                time_start_days,
                time_end_days,
            )

        # Recency filter (Refactored to use reporting.filter_by_recency)
        if mode not in ["Raw Listens", "New Music By Year", "Favorite Artist Trend"]:
            if not (rec_start_days == 0 and rec_end_days == 0):
                # Determine entity cols for recency grouping
                if mode == "By Artist" or mode == "Genre Flavor":
                    entity_cols = ["artist"]
                elif mode == "By Album":
                    entity_cols = ["artist", "album"]
                elif mode == "By Track":
                    entity_cols = ["artist", "track_name"]
                else:
                    entity_cols = ["artist"]

                df = reporting.filter_by_recency(df, entity_cols, rec_start_days, rec_end_days)

        # After time/recency filtering, protect against empty inputs
        if df.empty and mode not in ["New Music By Year"]:
            report_type_key = self._handlers.get(mode, {}).get("report_type_key", "unknown")
            return (
                df,          # empty result
                None,        # no meta
                report_type_key,
                False,       # not enriched
                "No data available for the selected time range/recency filters."
            )

        if progress_callback:
            progress_callback(20, 100, "Aggregating...")

        # --------------------------------------------------------
        # SPECIAL PIPELINE: Genre Flavor
        # --------------------------------------------------------
        if mode == "Genre Flavor":
            # 1. Aggregate to Artists first
            grouped_artists, _ = reporting.report_top(
                df, 
                group_col="artist", 
                topn=0,
                min_listens=min_listens,
                min_minutes=min_minutes,
                min_likes=min_likes,
                liked_mbids=liked_mbids
            )
            
            enrichment_stats = {}
            
            # 2. Enrich the aggregated artists
            if do_enrich and not grouped_artists.empty:
                if progress_callback:
                    progress_callback(30, 100, "Enriching artists for Genre Flavor...")
                
                grouped_artists["_username"] = base_df["_username"].iloc[0]
                
                grouped_artists, enrichment_stats = enrichment.enrich_report(
                    grouped_artists,
                    "artist",
                    enrichment_mode,
                    force_cache_update=force_cache_update,
                    progress_callback=progress_callback,
                    is_cancelled=is_cancelled
                )
            
            # 3. Calculate Flavor Report
            result, meta = reporting.report_genre_flavor(grouped_artists)
            
            last_enriched = do_enrich
            report_type_key = "genre_flavor"

        # --------------------------------------------------------
        # STANDARD PIPELINE
        # --------------------------------------------------------
        else:
            handler = self._handlers.get(mode)
            if handler is None:
                raise ValueError(f"Unsupported report type: {mode}")
            func = handler["func"]
            kwargs = handler["kwargs"].copy()
            report_type_key = handler["report_type_key"]

            if func is reporting.report_top:
                if liked_mbids is None: liked_mbids = set()
                kwargs.update({
                    "days": None,
                    "topn": topn,
                    "min_listens": min_listens,
                    "min_minutes": min_minutes,
                    "min_likes": min_likes,
                    "liked_mbids": liked_mbids,
                })
                result, meta = func(df, **kwargs)

            elif func is reporting.report_artist_trend:
                kwargs["topn"] = topn
                result, meta = func(df, **kwargs)

            elif func == reporting.report_new_music_by_year:
                result, meta = func(base_df)

            elif func is reporting.report_raw_listens:
                # Updated: Pass liked_mbids for the "Liked" column
                result, meta = func(df, topn=topn, liked_mbids=liked_mbids)

            else:
                result, meta = func(df, **kwargs)

            # Optional enrichment
            last_enriched = False
            enrichment_stats = {}
            
            if do_enrich and mode not in ["Raw Listens", "New Music By Year", "Favorite Artist Trend"]:
                if not result.empty:
                    result = result.copy()
                    result["_username"] = base_df["_username"].iloc[0]

                    if progress_callback:
                        progress_callback(30, 100, "Starting enrichment...")

                    result, enrichment_stats = enrichment.enrich_report(
                        result,
                        report_type_key,
                        enrichment_mode,
                        force_cache_update=force_cache_update,
                        progress_callback=progress_callback,
                        is_cancelled=is_cancelled
                    )
                    last_enriched = True
                    
                    result = reporting.apply_column_order(result)

        if progress_callback:
            progress_callback(100, 100, "Complete.")

        status_text = self.get_status(mode)
        
        if last_enriched and enrichment_stats:
            if is_cancelled and is_cancelled():
                status_text += " [Enrichment Cancelled]"
            
            key_map = {
                "artist": "artists", 
                "album": "albums", 
                "track": "tracks",
                "genre_flavor": "artists" 
            }
            stat_key = key_map.get(report_type_key)
            
            if stat_key and stat_key in enrichment_stats:
                s = enrichment_stats[stat_key]
                extra = (
                    f" Enrichment: {s['processed']} Processed "
                    f"({s['cache_hits']} Cached | "
                    f"{s['newly_fetched']} Fetched | "
                    f"{s['empty']} Empty)"
                )
                if s['fallbacks'] > 0:
                    extra = extra[:-1] + f" | {s['fallbacks']} Fallbacks)"
                
                status_text += extra

        return result, meta, report_type_key, last_enriched, status_text