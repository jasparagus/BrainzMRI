import zipfile
import json
import os
from datetime import datetime, UTC, timezone
from typing import Iterable, List, Tuple, Dict, Any, Set, Optional

import pandas as pd


def parse_listenbrainz_zip(zip_path: str) -> Tuple[Dict[str, Any], list, list]:
    """
    Parse a ListenBrainz export ZIP and extract user info, feedback, and listens.
    """
    with zipfile.ZipFile(zip_path, "r") as z:
        # User info
        user_info_bytes = z.read("user.json")
        user_info = json.loads(user_info_bytes.decode("utf-8"))

        # Feedback (optional file)
        feedback: List[Dict[str, Any]] = []
        if "feedback.jsonl" in z.namelist():
            with z.open("feedback.jsonl") as f:
                for line in f:
                    feedback.append(json.loads(line.decode("utf-8")))

        # Listens
        listens: List[Dict[str, Any]] = []
        for name in z.namelist():
            if name.startswith("listens/") and name.endswith(".jsonl"):
                with z.open(name) as f:
                    for line in f:
                        listens.append(json.loads(line.decode("utf-8")))

    return user_info, feedback, listens


def normalize_listens(
    listens: Iterable[Dict[str, Any]],
    origin: Iterable[str] | None = None,
) -> pd.DataFrame:
    """
    Normalize raw ListenBrainz listen objects into a flat canonical DataFrame.
    """
    origin_list: List[str] = list(origin) if origin is not None else ["listenbrainz_zip"]
    records: List[Dict[str, Any]] = []

    for l in listens:
        meta = l.get("track_metadata", {}) or {}
        mbid_mapping = meta.get("mbid_mapping") or {}
        additional_info = meta.get("additional_info", {}) or {}

        # Artist extraction
        artists: List[str] = []
        if mbid_mapping.get("artists"):
            artists = [
                a.get("artist_credit_name")
                for a in mbid_mapping["artists"]
                if a.get("artist_credit_name")
            ]
        else:
            if meta.get("artist_name"):
                artists = [meta["artist_name"]]
            else:
                artists = ["Unknown"]

        # Album
        album_name = meta.get("release_name") or "Unknown"

        # Duration in ms
        duration_ms = additional_info.get("duration_ms")
        if duration_ms is None and "duration" in additional_info:
            try:
                duration_ms = int(additional_info["duration"]) * 1000
            except (TypeError, ValueError):
                duration_ms = None
        if duration_ms is None:
            duration_ms = 0

        # Listened at (UTC)
        listened_at = l.get("listened_at")
        listened_dt = datetime.fromtimestamp(listened_at, UTC) if listened_at else None

        # Recording MBID
        recording_mbid = None
        if mbid_mapping.get("recording_mbid"):
            recording_mbid = mbid_mapping["recording_mbid"]
        elif additional_info.get("lastfm_recording_mbid"):
            recording_mbid = additional_info["lastfm_recording_mbid"]

        # Artist MBID map
        artist_mbid_map: Dict[str, str | None] = {}
        if mbid_mapping.get("artists"):
            for a in mbid_mapping["artists"]:
                name = a.get("artist_credit_name")
                mbid = a.get("artist_mbid")
                if name:
                    artist_mbid_map[name] = mbid

        # Release MBID (not always present, keep for future use)
        release_mbid = mbid_mapping.get("release_mbid")

        track_name = meta.get("track_name") or "Unknown"

        # One row per artist for multi artist credits
        for artist in artists:
            records.append(
                {
                    "artist": artist,
                    "artist_mbid": artist_mbid_map.get(artist),
                    "album": album_name,
                    "track_name": track_name,
                    "duration_ms": duration_ms,
                    "listened_at": listened_dt,
                    "recording_mbid": recording_mbid,
                    "release_mbid": release_mbid,
                    "origin": origin_list.copy(),
                }
            )

    if not records:
        # Return an empty DataFrame with the canonical columns
        return pd.DataFrame(
            columns=[
                "artist",
                "artist_mbid",
                "album",
                "track_name",
                "duration_ms",
                "listened_at",
                "recording_mbid",
                "release_mbid",
                "origin",
            ]
        )

    return pd.DataFrame.from_records(records)


def load_feedback(feedback: Iterable[Dict[str, Any]]) -> Set[str]:
    """
    Extract liked recording MBIDs from feedback entries.
    """
    likes: Set[str] = set()
    for row in feedback:
        if row.get("score") == 1 and row.get("recording_mbid"):
            likes.add(row["recording_mbid"])
    return likes
    
    
def load_listens_from_zip(zip_path: str) -> tuple[pd.DataFrame, Set[str]]:
    """
    Convenience loader for the GUI.
    """
    user_info, feedback, listens = parse_listenbrainz_zip(zip_path)
    df = normalize_listens(listens, origin=["listenbrainz_zip"])
    likes = load_feedback(feedback)
    return df, likes


# ------------------------------------------------------------
# CSV Import Logic (Phase 2.1)
# ------------------------------------------------------------

def parse_generic_csv(filepath: str) -> pd.DataFrame:
    """
    Parse an arbitrary CSV file and attempt to map it to the canonical schema.
    
    Heuristics:
    - Finds a column containing "artist" (excluding "album") -> 'artist'
    - Finds a column containing "album" -> 'album'
    - Finds a column containing "track" or "title" -> 'track_name'
    
    Raises ValueError if required columns cannot be uniquely identified.
    """
    try:
        # Read without index, infer headers
        raw_df = pd.read_csv(filepath)
    except Exception as e:
        raise ValueError(f"Failed to read CSV: {e}")

    # clean headers: lowercase, strip whitespace
    raw_cols = {c: c.lower().strip() for c in raw_df.columns}
    
    # --- 1. Identify Artist Column ---
    # Must contain 'artist', must NOT contain 'album' (avoids 'Album Artist')
    artist_candidates = [
        orig for orig, clean in raw_cols.items() 
        if "artist" in clean and "album" not in clean
    ]
    
    if not artist_candidates:
        raise ValueError("Unable to parse: Could not determine 'Artist' column.")
    
    # If multiple, prefer exact match 'artist' or 'artist name' if possible, else take first
    artist_col = artist_candidates[0]
    
    # --- 2. Identify Album Column ---
    album_candidates = [
        orig for orig, clean in raw_cols.items() 
        if "album" in clean
    ]
    if not album_candidates:
        raise ValueError("Unable to parse: Could not determine 'Album' column.")
    album_col = album_candidates[0]
    
    # --- 3. Identify Track Column ---
    track_candidates = [
        orig for orig, clean in raw_cols.items() 
        if "track" in clean or "title" in clean
    ]
    if not track_candidates:
        raise ValueError("Unable to parse: Could not determine 'Track'/'Title' column.")
    track_col = track_candidates[0]
    
    # --- Construct Canonical DataFrame ---
    df = pd.DataFrame()
    
    # Map and fill missing values with "Unknown"
    df["artist"] = raw_df[artist_col].fillna("Unknown").astype(str)
    df["album"] = raw_df[album_col].fillna("Unknown").astype(str)
    df["track_name"] = raw_df[track_col].fillna("Unknown").astype(str)
    
    # Fill canonical technical columns
    df["duration_ms"] = 0
    df["listened_at"] = datetime.now(timezone.utc) # Mark import time as listen time? Or None?
    # Better to leave listened_at as NaT or current time. 
    # For a "Playlist", current time makes sense as "Imported At", 
    # but for history analysis, it might skew "Last Listened". 
    # Let's assume Import Time for now so they appear at the top of "Recent".
    
    df["recording_mbid"] = None
    df["artist_mbid"] = None
    df["release_mbid"] = None
    df["origin"] = "csv_import"
    
    # Convert origin to list to match schema
    df["origin"] = df["origin"].apply(lambda x: [x])

    return df