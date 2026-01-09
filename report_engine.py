import pandas as pd
import numpy as np
from typing import Optional, Dict, Any

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
                "kwargs": {"group_col": "artist", "by": "total_tracks"},
                "report_type_key": "artist",
                "status": "Artist report generated.",
            },
            "By Album": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "album", "by": "total_tracks"},
                "report_type_key": "album",
                "status": "Album report generated.",
            },
            "By Track": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "track", "by": "total_tracks"},
                "report_type_key": "track",
                "status": "Track report generated.",
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
    ):
        """
        Generate a report for the given mode and parameters.
        """
        if base_df is None:
            raise ValueError("No listens data available.")

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

        # Recency filter
        if mode not in ["Raw Listens", "New Music By Year"]:
            if not (rec_start_days == 0 and rec_end_days == 0):
                now = datetime.now(timezone.utc)
                min_dt = now - timedelta(days=rec_end_days)
                max_dt = now - timedelta(days=rec_start_days)

                if mode == "By Artist":
                    entity_cols = ["artist"]
                elif mode == "By Album":
                    entity_cols = ["artist", "album"]
                elif mode == "By Track":
                    entity_cols = ["artist", "track_name"]
                else:
                    entity_cols = ["artist"]

                true_last = (
                    df.groupby(entity_cols)["listened_at"]
                    .max()
                    .reset_index()
                    .rename(columns={"listened_at": "true_last_listened"})
                )

                allowed = true_last[
                    (true_last["true_last_listened"] >= min_dt)
                    & (true_last["true_last_listened"] <= max_dt)
                ]

                df = df.merge(allowed[entity_cols], on=entity_cols, how="inner")

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

        # Get details from handler
        handler = self._handlers.get(mode)
        if handler is None:
            raise ValueError(f"Unsupported report type: {mode}")
        func = handler["func"]
        kwargs = handler["kwargs"].copy()
        report_type_key = handler["report_type_key"]

        # Call appropriate reporting function
        if func is reporting.report_top:
            if liked_mbids is None:
                liked_mbids = set()
            kwargs.update(
                {
                    "days": None,    # Legacy days filter
                    "topn": topn,
                    "min_listens": min_listens,
                    "min_minutes": min_minutes,
                    "min_likes": min_likes,
                    "liked_mbids": liked_mbids,
                }
            )
            result, meta = func(df, **kwargs)

        elif func == reporting.report_new_music_by_year:
            result, meta = func(base_df)

        elif func is reporting.report_raw_listens:
            result, meta = func(df, topn=topn)

        else:
            result, meta = func(df, **kwargs)

        # Optional enrichment
        last_enriched = False
        enrichment_stats = {}
        
        if do_enrich and mode not in ["Raw Listens", "New Music By Year"]:
            if not result.empty:
                # Inject username
                result = result.copy()
                result["_username"] = base_df["_username"].iloc[0]

                result, enrichment_stats = enrichment.enrich_report(
                    result,
                    report_type_key,
                    enrichment_mode,
                    force_cache_update=force_cache_update,
                )
                last_enriched = True

        # Generate status text
        status_text = self.get_status(mode)
        
        if last_enriched and enrichment_stats:
            # Observability: Add stats to status text
            # E.g. "Enrichment: Processed 50 Artists (20 cached, 30 looked up, 5 fallbacks)."
            
            # Pick the stats relevant to the report mode
            key_map = {"artist": "artists", "album": "albums", "track": "tracks"}
            stat_key = key_map.get(report_type_key)
            
            if stat_key and stat_key in enrichment_stats:
                s = enrichment_stats[stat_key]
                # Format: "Artist Report generated. Enrichment: 100 Processed (50 Cached | 50 Lookups)"
                extra = (
                    f" Enrichment: {s['processed']} Processed "
                    f"({s['cache_hits']} Cached | "
                    f"{s['mb_lookups'] + s['lastfm_lookups']} Lookups | "
                    f"{s['fallbacks']} Fallbacks)"
                )
                status_text += extra

        return result, meta, report_type_key, last_enriched, status_text