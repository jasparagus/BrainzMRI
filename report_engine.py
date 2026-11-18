"""
report_engine.py
Controller logic for generating reports.
Acts as the bridge between GUI inputs, Aggregation logic, and Enrichment.
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional, Dict, Any, Callable, Tuple

from datetime import datetime, timedelta, timezone

import reporting
import enrichment


class ReportEngine:
    """
    Encapsulates report generation logic.
    """

    def __init__(self) -> None:
        self._handlers = {
            "Top Artists": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "artist", "by": "total_listens"},
                "report_type_key": "artist",
                "status": "Artist report generated.",
            },
            "Top Albums": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "album", "by": "total_listens"},
                "report_type_key": "album",
                "status": "Album report generated.",
            },
            "Top Tracks": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "track", "by": "total_listens"},
                "report_type_key": "track",
                "status": "Track report generated.",
            },
            "Genre Flavor": {
                # Logic handled explicitly in generate_report pipeline
                "func": None, 
                "kwargs": {},
                "report_type_key": "genre_flavor",
                "status": "Genre Flavor report generated.",
            },
            "Favorite Artist Trend": {
                "func": reporting.report_entity_trend,
                "kwargs": {"entity": "artist"},
                "report_type_key": "trend",
                "status": "Artist Trend report generated.",
            },
            "Favorite Track Trend": {
                "func": reporting.report_entity_trend,
                "kwargs": {"entity": "track"},
                "report_type_key": "trend",
                "status": "Track Trend report generated.",
            },
            "Favorite Album Trend": {
                "func": reporting.report_entity_trend,
                "kwargs": {"entity": "album"},
                "report_type_key": "trend",
                "status": "Album Trend report generated.",
            },
            "New Music By Year": {
                "func": reporting.report_new_music_by_year,
                "kwargs": {},
                "report_type_key": "new_music",
                "status": "New Music analysis complete.",
            },
            "Raw Listens": {
                "func": reporting.report_raw_listens,
                "kwargs": {},
                "report_type_key": "raw",
                "status": "Raw history loaded.",
            },
            "Likes": {
                # Specialized pipeline: loads resolver cache + Last.fm loves
                "func": None,
                "kwargs": {},
                "report_type_key": "likes",
                "status": "Likes audit generated.",
            },
            "Likes for Days": {
                # Specialized pipeline: resolved likes -> >= min_listens -> MB durations -> TopN compilation
                "func": None,
                "kwargs": {},
                "report_type_key": "likes_for_days",
                "status": "Likes for Days report generated.",
            },
            "Listen Count vs. Time": {
                "func": reporting.report_listen_count_vs_time,
                "kwargs": {},
                "report_type_key": "listen_rate",
                "status": "Listen Count report generated.",
            }
        }

    def get_status(self, mode: str) -> str:
        return self._handlers.get(mode, {}).get("status", "Report generated.")

    def generate_report(
        self,
        df: pd.DataFrame,
        mode: str,
        liked_mbids: set,
        time_start_days: int = 0,
        time_end_days: int = 0,
        rec_start_days: int = 0,
        rec_end_days: int = 0,
        first_start_days: int = 0, # NEW
        first_end_days: int = 0,   # NEW
        min_listens: int = 0,
        min_minutes: float = 0.0,
        min_likes: int = 0,
        topn: int = 100,
        do_enrich: bool = False,
        enrichment_mode: str = "Cache Only",
        force_cache_update: bool = False,
        deep_query: bool = False,
        progress_callback: Optional[Callable] = None,
        is_cancelled: Optional[Callable] = None,
        lastfm_loves: list = None,
    ) -> Tuple[pd.DataFrame, Dict[str, Any], str, bool, str]:
        """
        Master orchestration method.
        """
        logging.info(f"Report Requested: Mode='{mode}' | Filters: Time={time_start_days}-{time_end_days}, Recency={rec_start_days}-{rec_end_days}, First={first_start_days}-{first_end_days}, TopN={topn} | Enrichment: {do_enrich} ({enrichment_mode})")
        
        handler = self._handlers.get(mode)
        if not handler:
            raise ValueError(f"Unknown report mode: {mode}")

        # --- GUARD CLAUSE: EMPTY DATA ---
        # Likes and Likes for Days can work with empty/minimal df (delegated to specialized handlers)
        if df.empty and mode not in ("Likes", "Likes for Days"):
            logging.warning(f"Report '{mode}' aborted: Source DataFrame is empty.")
            return pd.DataFrame(), {}, handler["report_type_key"], False, "No data available."

        # --------------------------------------------------------
        # 1. Pre-Filtering (Time Range)
        # --------------------------------------------------------
        if time_start_days > 0 or time_end_days > 0:
            df = reporting.filter_by_days(df, "listened_at", time_start_days, time_end_days)
            
        # --------------------------------------------------------
        # 2. Pipeline Execution
        # --------------------------------------------------------
        
        result = pd.DataFrame()
        result_meta = {}
        last_enriched = False
        enrichment_stats = {}
        report_type_key = handler["report_type_key"]
        
        # Standard Args for most reports
        base_kwargs = handler["kwargs"].copy()
        base_kwargs.update({
            "topn": topn,
            "min_listens": min_listens, 
            "min_minutes": min_minutes,
            "min_likes": min_likes,
            "liked_mbids": liked_mbids,
            "recency_range": (rec_start_days, rec_end_days) if (rec_start_days or rec_end_days) else None,
            "first_range": (first_start_days, first_end_days) if (first_start_days or first_end_days) else None # NEW
        })

        if progress_callback:
            progress_callback(10, 100, "Initializing report...")

        # --- SPECIALIZED PIPELINE: LIKES AUDIT ---
        if mode == "Likes":
            if progress_callback: progress_callback(20, 100, "Building likes audit...")
            
            # Load resolver cache for MBID lookups
            resolver_cache = enrichment.get_resolver_cache()
            
            raw_result = reporting.report_likes(
                df=df,
                liked_mbids=liked_mbids,
                lastfm_loves=lastfm_loves,
                resolver_cache=resolver_cache,
            )
            
            if isinstance(raw_result, tuple):
                result, result_meta = raw_result
            else:
                result, result_meta = raw_result, {}

        # --- SPECIALIZED PIPELINE: LIKES FOR DAYS ---
        elif mode == "Likes for Days":
            if progress_callback: progress_callback(10, 100, "Retrieving resolved likes...")

            resolver_cache = enrichment.get_resolver_cache()
            resolved_likes_df = reporting.get_resolved_likes(
                df=df,
                liked_mbids=liked_mbids,
                lastfm_loves=lastfm_loves,
                resolver_cache=resolver_cache
            )

            if is_cancelled and is_cancelled():
                logging.info("Report generation cancelled after retrieving resolved likes.")
                return pd.DataFrame(), {}, "", False, "Cancelled."

            if resolved_likes_df.empty:
                logging.warning("No resolved likes found.")
                return pd.DataFrame(), {}, handler["report_type_key"], False, "No resolved likes found."

            effective_min_listens = max(1, min_listens)
            listen_label = f"{effective_min_listens}+ listens" if effective_min_listens > 1 else "1+ listen"

            # Pre-filter candidates with >= effective_min_listens to avoid unnecessary API calls
            if progress_callback:
                progress_callback(25, 100, f"Filtering tracks with {listen_label} (from {len(resolved_likes_df)} resolved likes)...")

            mbid_counts = {}
            if "recording_mbid" in df.columns:
                valid_mbids = df[df["recording_mbid"].notna() & (df["recording_mbid"] != "")]["recording_mbid"]
                mbid_counts = valid_mbids.value_counts().to_dict()

            name_counts = {}
            if "artist" in df.columns and "track_name" in df.columns:
                name_counts = df.groupby([df["artist"].str.lower().str.strip(), df["track_name"].str.lower().str.strip()]).size().to_dict()

            seen_mbids = set()
            seen_names = set()
            candidate_tracks = []
            for _, row in resolved_likes_df.iterrows():
                mbid = str(row.get("recording_mbid", "")).strip()
                if not mbid or mbid.lower() in ("none", "nan", "") or mbid in seen_mbids:
                    continue
                artist = str(row.get("artist", "")).strip()
                track_name = str(row.get("track_name", "")).strip()
                norm_name = (artist.lower(), track_name.lower()) if (artist and track_name) else None
                if norm_name and norm_name in seen_names:
                    continue
                c_mbid = mbid_counts.get(mbid, 0)
                c_name = name_counts.get(norm_name, 0) if norm_name else 0
                if max(c_mbid, c_name) >= effective_min_listens:
                    seen_mbids.add(mbid)
                    if norm_name:
                        seen_names.add(norm_name)
                    candidate_tracks.append({
                        "recording_mbid": mbid,
                        "artist": artist,
                        "track_name": track_name,
                        "album": str(row.get("album", "")).strip()
                    })

            if not candidate_tracks:
                logging.warning(f"No liked tracks found with {effective_min_listens} or more listens.")
                return pd.DataFrame(), {}, handler["report_type_key"], False, f"No liked tracks found with {listen_label}."

            if is_cancelled and is_cancelled():
                logging.info("Report generation cancelled before duration fetch.")
                return pd.DataFrame(), {}, "", False, "Cancelled."

            # Fetch durations with persistent caching and progress feedback
            if progress_callback:
                progress_callback(40, 100, f"Fetching durations for {len(candidate_tracks)} qualifying tracks ({listen_label})...")

            def duration_progress(cur, tot, msg):
                if progress_callback and tot > 0:
                    scaled = int(40 + (cur / tot) * 45)
                    progress_callback(scaled, 100, msg)

            durations_map = enrichment.fetch_recording_durations(
                tracks=candidate_tracks,
                force_cache_update=force_cache_update,
                progress_callback=duration_progress,
                is_cancelled=is_cancelled
            )

            if is_cancelled and is_cancelled():
                logging.info("Report generation cancelled during duration fetch.")
                return pd.DataFrame(), {}, "", False, "Cancelled."

            if progress_callback: progress_callback(90, 100, "Compiling Top-N lists...")

            track_df, artist_df, album_df, result_meta = reporting.report_likes_for_days(
                df=df,
                resolved_likes_df=resolved_likes_df,
                durations_map=durations_map,
                topn=topn,
                min_listens=effective_min_listens
            )

            result = track_df

        # --- SPECIALIZED PIPELINE: GENRE FLAVOR ---
        elif mode == "Genre Flavor":
            # Step A: Aggregate by Artist (Proxy Step)
            if progress_callback: progress_callback(20, 100, "Aggregating artists...")
            
            artist_kwargs = base_kwargs.copy()
            artist_kwargs["group_col"] = "artist"
            artist_kwargs["by"] = "total_listens"
            artist_kwargs["df"] = df
            
            raw_artist_result = reporting.report_top(**artist_kwargs)
            if isinstance(raw_artist_result, tuple):
                df_artists = raw_artist_result[0]
            else:
                df_artists = raw_artist_result
                
            if is_cancelled and is_cancelled():
                logging.info("Report generation cancelled during aggregation.")
                return pd.DataFrame(), {}, "", False, "Cancelled."

            # Step B: Enrich Artist Data
            if do_enrich and not df_artists.empty:
                if progress_callback: progress_callback(50, 100, "Enriching artist metadata...")
                
                df_artists, enrichment_stats = enrichment.enrich_report(
                    df=df_artists,
                    enrichment_mode=enrichment_mode,
                    force_cache_update=force_cache_update,
                    progress_callback=progress_callback,
                    is_cancelled=is_cancelled,
                    deep_query=False
                )
                last_enriched = True
            
            if is_cancelled and is_cancelled():
                logging.info("Report generation cancelled during enrichment.")
                return pd.DataFrame(), {}, "", False, "Cancelled."

            # Step C: Generate Flavor Report (Transform)
            if progress_callback: progress_callback(80, 100, "Calculating genre weights...")
            
            raw_result = reporting.report_genre_flavor(df_artists)
            
            if isinstance(raw_result, tuple):
                result, result_meta = raw_result
            else:
                result, result_meta = raw_result, {}

        # --- STANDARD PIPELINE (Aggregate -> Enrich) ---
        else:
            func = handler["func"]
            base_kwargs["df"] = df
            
            if progress_callback: progress_callback(20, 100, "Aggregating data...")
            
            raw_result = func(**base_kwargs)

            if isinstance(raw_result, tuple):
                result, result_meta = raw_result
            else:
                result, result_meta = raw_result, {}

            if is_cancelled and is_cancelled():
                logging.info("Report generation cancelled.")
                return pd.DataFrame(), {}, "", False, "Cancelled."

            # Apply cached MBID resolutions to track-level standard reports (Raw Listens, Imported Playlist, Top Tracks)
            if not result.empty and "track_name" in result.columns and "artist" in result.columns:
                result = enrichment.apply_resolver_cache(result)
                if liked_mbids and "recording_mbid" in result.columns and "Likes" in result.columns:
                    result["Likes"] = result["recording_mbid"].apply(lambda x: 1 if x in liked_mbids else 0).astype(int)

            # Enrich Result
            if do_enrich and not result.empty:
                if progress_callback: progress_callback(50, 100, "Enriching report...")
                
                result, enrichment_stats = enrichment.enrich_report(
                    df=result,
                    enrichment_mode=enrichment_mode,
                    force_cache_update=force_cache_update,
                    progress_callback=progress_callback,
                    is_cancelled=is_cancelled,
                    deep_query=deep_query
                )
                last_enriched = True
                result = reporting.apply_column_order(result)

        # --------------------------------------------------------
        # 3. Finalize
        # --------------------------------------------------------
        if progress_callback:
            progress_callback(100, 100, "Complete.")

        if not result_meta:
            result_meta = {
                "entity": report_type_key, 
                "topn": topn, 
                "metric": "listens", 
                "days": None
            }

        base_msg = self.get_status(mode).rstrip(".")
        if mode == "Likes for Days":
            eff_min = max(1, min_listens)
            status_text = f"{base_msg} ({len(result)} Rows, {eff_min}+ Listens)."
        else:
            status_text = f"{base_msg} ({len(result)} Rows)."
        
        if last_enriched and enrichment_stats:
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

        logging.info(f"Report generation complete. Rows: {len(result)}")
        return result, result_meta, report_type_key, last_enriched, status_text