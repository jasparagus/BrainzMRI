from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any

from datetime import datetime, timedelta, timezone

import reporting
import enrichment


class ReportEngine:
    """
    Encapsulates report generation logic.

    Responsible for:
    - Time range filtering
    - Recency filtering
    - Thresholding and Top N
    - Calling reporting functions
    - Optional enrichment
    """

    def __init__(self) -> None:
        self._handlers = {
            "By Artist": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "artist", "by": "total_tracks"},
                "status": "Artist report generated.",
            },
            "By Album": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "album", "by": "total_tracks"},
                "status": "Album report generated.",
            },
            "By Track": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "track", "by": "total_tracks"},
                "status": "Track report generated.",
            },
            "All Liked Artists": {
                "func": reporting.report_artists_with_likes,
                "kwargs": {},
                "status": "Liked artists report generated.",
            },
            "New Music By Year": {
                "func": reporting.report_new_music_by_year,
                "kwargs": {},
                "status": "New Music by Year report generated.",
            },
            "Raw Listens": {
                "func": reporting.report_raw_listens,
                "kwargs": {},
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
        topn: int,
        do_enrich: bool,
        enrich_source: str,
    ):
        """
        Generate a report for the given mode and parameters.

        Notes:
        - "New Music by Year" report requires the unfiltered listens dataset
        
        Returns
        -------
        result_df : DataFrame
        meta : dict | None
        report_type_key : str
        last_enriched : bool
        status_text : str
        """
        if base_df is None:
            raise ValueError("No listens data available.")

        df = base_df.copy()

        # Time range filter (on listens)
        if not (time_start_days == 0 and time_end_days == 0):
            df = reporting.filter_by_days(
                df,
                "listened_at",
                time_start_days,
                time_end_days,
            )

        # Recency filter (skip for Raw Listens)
        if mode != "Raw Listens":
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

        handler = self._handlers.get(mode)
        print(handler)
        if handler is None:
            raise ValueError(f"Unsupported report type: {mode}")

        # Special case: New Music by Year ignores ALL filters, run now
        if mode == "New Music by Year":
            result = report_new_music_by_year(base_df)
            meta = None
            report_type_key = "new_music_by_year"
            last_enriched = False
            status_text = self.get_status(mode)
            return result, meta, report_type_key, last_enriched, status_text

        func = handler["func"]
        kwargs = handler["kwargs"].copy()

        # Call appropriate reporting function
        if func is reporting.report_top:
            kwargs.update(
                {
                    "days": None,
                    "topn": topn,
                    "min_listens": min_listens,
                    "min_minutes": min_minutes,
                }
            )
            result, meta = func(df, **kwargs)

        elif func is reporting.report_artists_with_likes:
            if liked_mbids is None:
                liked_mbids = set()
            result, meta = func(
                df,
                liked_mbids,
                min_listens=min_listens,
                min_minutes=min_minutes,
                topn=topn,
            )

        elif func is reporting.report_raw_listens:
            result, meta = func(df, topn=topn)

        else:
            result, meta = func(df, **kwargs)

        # Determine report_type_key
        if mode == "By Artist":
            report_type_key = "artist"
        elif mode == "By Album":
            report_type_key = "album"
        elif mode == "By Track":
            report_type_key = "track"
        elif mode == "All Liked Artists":
            report_type_key = "liked_artists"
        else:
            report_type_key = "raw"

        # After time-range filtering, protect against empty results
        if df.empty:
            return (
                df,          # empty result
                None,        # no meta
                report_type_key,
                False,       # not enriched
                "No data available for the selected time range."
            )

        # Optional enrichment (skip for Raw Listens)
        last_enriched = False
        if do_enrich and mode != "Raw Listens":
            # Inject username into the report DataFrame
            result = result.copy()
            result["_username"] = base_df["_username"].iloc[0]

            result = enrichment.enrich_report(
                result,
                report_type_key,
                enrich_source,
            )
            last_enriched = True

        status_text = self.get_status(mode)
        return result, meta, report_type_key, last_enriched, status_text
