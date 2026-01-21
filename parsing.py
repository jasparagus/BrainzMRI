"""
parsing.py
Data ingestion, normalization, and key generation logic for BrainzMRI.
"""

import zipfile
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
import unicodedata
import pandas as pd


# ------------------------------------------------------------
# Key Generation (Centralized)
# ------------------------------------------------------------

def _clean_str(val: Any) -> str:
    """Normalize string for key generation: lower, strip, safe str."""
    if val is None or pd.isna(val):
        return ""
    return str(val).strip().lower()


def make_track_key(artist: str, track: str, album: str = "") -> str:
    """
    Generate a consistent unique key for a track.
    Format: "artist|track|album" (album optional)
    """
    a = _clean_str(artist)
    t = _clean_str(track)
    alb = _clean_str(album)
    # Use pipe separator as it's rare in names
    return f"{a}|{t}|{alb}"


def make_album_key(artist: str, album: str) -> str:
    """
    Generate a consistent unique key for an album.
    Format: "artist|album"
    """
    a = _clean_str(artist)
    alb = _clean_str(album)
    return f"{a}|{alb}"


def make_track_key_series(df: pd.DataFrame) -> pd.Series:
    """
    Vectorized key generation for a DataFrame.
    Expects columns: 'artist', 'track_name', and optional 'album'.
    """
    # Vectorized string processing for speed

    # 1. Artist
    if "artist" in df.columns:
        s_art = df["artist"].fillna("").astype(str).str.strip().str.lower()
    else:
        s_art = pd.Series([""] * len(df), index=df.index)

    # 2. Track
    if "track_name" in df.columns:
        s_track = df["track_name"].fillna("").astype(str).str.strip().str.lower()
    else:
        s_track = pd.Series([""] * len(df), index=df.index)

    # 3. Album (Optional)
    if "album" in df.columns:
        s_alb = df["album"].fillna("").astype(str).str.strip().str.lower()
    else:
        s_alb = pd.Series([""] * len(df), index=df.index)

    return s_art + "|" + s_track + "|" + s_alb


# ------------------------------------------------------------
# ListenBrainz Ingestion
# ------------------------------------------------------------

def parse_listenbrainz_zip(zip_path: str) -> tuple[dict[str, Any], list, list]:
    """
    Parse a ListenBrainz export ZIP and extract user info, feedback, and listens.
    """
    with zipfile.ZipFile(zip_path, "r") as z:
        # User info
        try:
            user_info_bytes = z.read("user.json")
            user_info = json.loads(user_info_bytes.decode("utf-8"))
        except KeyError:
            user_info = {}

        # Feedback (optional file)
        feedback: list[dict[str, Any]] = []
        if "feedback.jsonl" in z.namelist():
            with z.open("feedback.jsonl") as f:
                for line in f:
                    try:
                        feedback.append(json.loads(line.decode("utf-8")))
                    except json.JSONDecodeError:
                        continue

        # Listens
        listens: list[dict[str, Any]] = []
        for name in z.namelist():
            if name.startswith("listens/") and name.endswith(".jsonl"):
                with z.open(name) as f:
                    for line in f:
                        try:
                            listens.append(json.loads(line.decode("utf-8")))
                        except json.JSONDecodeError:
                            continue

    return user_info, feedback, listens


def normalize_listens(raw_listens: list[dict[str, Any]], origin: str = "zip_import") -> pd.DataFrame:
    """
    Convert raw ListenBrainz JSON objects into the canonical DataFrame schema.
    """
    if not raw_listens:
        return pd.DataFrame(
            columns=[
                "artist", "artist_mbid", "album", "track_name",
                "duration_ms", "listened_at", "recording_mbid",
                "release_mbid", "origin"
            ]
        )

    rows = []
    for record in raw_listens:
        if record is None: continue

        # Handle API format (record) vs ZIP format (record)
        # Usually LB exports have 'track_metadata' inside.
        meta = record.get("track_metadata", {})

        # Fallback if structure is flat (rare but possible in some API endpoints)
        if not meta:
            meta = record

        artist_name = meta.get("artist_name", "Unknown")
        track_name = meta.get("track_name", "Unknown")
        album_name = meta.get("release_name", "Unknown")

        # Additional info - FIX: Handle explicit nulls in JSON
        add_info = meta.get("additional_info") or {}

        # Extract MBIDs
        # They can be in mapping/mbid_mapping OR directly in additional_info
        # FIX: Handle explicit nulls in JSON
        mb_maps = meta.get("mbid_mapping") or {}

        artist_mbid = mb_maps.get("artist_mbids", [None])[0] or mb_maps.get("artist_mbid")
        recording_mbid = mb_maps.get("recording_mbid") or add_info.get("recording_mbid")
        release_mbid = mb_maps.get("release_mbid") or add_info.get("release_mbid")

        # Fallback for artist_mbid if it's a list in additional_info
        if not artist_mbid:
            am = add_info.get("artist_mbids")
            if am and isinstance(am, list) and len(am) > 0:
                artist_mbid = am[0]

        duration = add_info.get("duration_ms") or add_info.get("duration") or 0

        # Timestamp
        listened_at_ts = record.get("listened_at")
        if listened_at_ts:
            dt = datetime.fromtimestamp(listened_at_ts, timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        rows.append({
            "artist": artist_name,
            "artist_mbid": str(artist_mbid) if artist_mbid else None,
            "album": album_name,
            "track_name": track_name,
            "duration_ms": int(duration) if duration else 0,
            "listened_at": dt,
            "recording_mbid": str(recording_mbid) if recording_mbid else None,
            "release_mbid": str(release_mbid) if release_mbid else None,
            "origin": origin
        })

    return pd.DataFrame(rows)


def load_feedback(feedback_list: list[dict[str, Any]]) -> set[str]:
    """
    Extract a set of recording_mbids from a list of feedback objects.
    Only includes items with score=1 (Likes).
    """
    likes = set()
    for item in feedback_list:
        # DEFENSIVE FIX: Handle None items in list
        if item is None:
            continue

        score = item.get("score")
        mbid = item.get("recording_mbid")

        # DEFENSIVE FIX: Handle None track_metadata
        if not mbid:
            tm = item.get("track_metadata")
            if tm and isinstance(tm, dict):
                mbid = tm.get("recording_mbid")

        if score == 1 and mbid:
            likes.add(mbid)
    return likes


def load_listens_from_zip(zip_path: str) -> tuple[pd.DataFrame, set[str]]:
    """
    Convenience wrapper to load all data from a ZIP into a DataFrame and Likes Set.
    """
    _, feedback_raw, listens_raw = parse_listenbrainz_zip(zip_path)

    df = normalize_listens(listens_raw, origin="zip_import")
    likes = load_feedback(feedback_raw)

    return df, likes


# ------------------------------------------------------------
# Generic CSV Import
# ------------------------------------------------------------

def parse_generic_csv(csv_path: str) -> pd.DataFrame:
    """
    Parse a generic CSV.
    Expects columns: Artist, Track Name (case insensitive).
    Optional: Album, MBID, Timestamp.
    """
    df = pd.read_csv(csv_path)

    # Normalize headers
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    # Map to schema
    # Required
    if "artist" not in df.columns or "track_name" not in df.columns:
        # Try heuristics
        if "track" in df.columns:
            df.rename(columns={"track": "track_name"}, inplace=True)
        if "name" in df.columns:
            df.rename(columns={"name": "track_name"}, inplace=True)

    if "artist" not in df.columns or "track_name" not in df.columns:
        raise ValueError("CSV must contain 'Artist' and 'Track Name' columns.")

    # Optional / Defaults
    if "album" not in df.columns:
        df["album"] = "Unknown"

    if "listened_at" not in df.columns:
        # Default to now if missing
        df["listened_at"] = datetime.now(timezone.utc)
    else:
        df["listened_at"] = pd.to_datetime(df["listened_at"], utc=True)

    if "duration_ms" not in df.columns:
        df["duration_ms"] = 0

    # Ensure ID columns exist
    for col in ["recording_mbid", "release_mbid", "artist_mbid"]:
        if col not in df.columns:
            df[col] = None

    df["origin"] = "csv_import"

    return df


# ------------------------------------------------------------
# Sort Normalization
# ------------------------------------------------------------

def normalize_sort_key(series: pd.Series) -> pd.Series:
    """
    Normalize a series of strings for sorting logic only.
    - Lowercase
    - Expand ligatures (Æ -> ae) manually
    - Strip accents/diacritics (é -> e)
    - Remove leading "The "
    """
    # 1. Ensure string and lowercase
    s = series.astype(str).str.lower()

    # 2. Remove "the " prefix
    s = s.str.replace(r"^the\s+", "", regex=True)

    # 3. Manual Ligature Expansion
    ligatures = {
        "æ": "ae",
        "œ": "oe",
        "ß": "ss",
    }
    for char, replacement in ligatures.items():
        s = s.str.replace(char, replacement, regex=False)

    # 4. Unicode Normalization
    def _clean_text(val):
        if not isinstance(val, str):
            return str(val)

        # Decompose
        norm = unicodedata.normalize("NFKD", val)
        # Strip combining chars
        return "".join([c for c in norm if not unicodedata.combining(c)])

    return s.apply(_clean_text)