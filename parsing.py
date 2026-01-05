import zipfile
import json
from datetime import datetime, UTC
from typing import Iterable, List, Tuple, Dict, Any, Set

import pandas as pd


def parse_listenbrainz_zip(zip_path: str) -> Tuple[Dict[str, Any], list, list]:
    """
    Parse a ListenBrainz export ZIP and extract user info, feedback, and listens.

    Parameters
    ----------
    zip_path : str
        Path to the ListenBrainz export ZIP file.

    Returns
    -------
    user_info : dict
        User metadata from user.json.
    feedback : list[dict]
        Raw feedback entries from feedback.jsonl (may be empty).
    listens : list[dict]
        Raw listen entries from listens/*.jsonl.
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

    Parameters
    ----------
    listens : iterable of dict
        Raw listen objects as returned from parse_listenbrainz_zip.
    origin : iterable of str, optional
        One or more origin tags to attach to each listen.
        For ListenBrainz ZIP imports this should be ["listenbrainz_zip"].

    Returns
    -------
    df : pandas.DataFrame
        Canonical listens table with at least these columns:
        - artist (str)
        - artist_mbid (str, optional)
        - album (str)
        - track_name (str)
        - duration_ms (int)
        - listened_at (datetime, UTC)
        - recording_mbid (str, optional)
        - release_mbid (str, optional, currently not populated)
        - origin (list[str])
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

    Parameters
    ----------
    feedback : iterable of dict
        Raw feedback entries as returned from parse_listenbrainz_zip.

    Returns
    -------
    likes : set of str
        Set of recording MBIDs that have a positive score.
    """
    likes: Set[str] = set()
    for row in feedback:
        if row.get("score") == 1 and row.get("recording_mbid"):
            likes.add(row["recording_mbid"])
    return likes
    
    
def load_listens_from_zip(zip_path: str) -> tuple[pd.DataFrame, Set[str]]:
    """
    Convenience loader for the GUI.

    Parse a ListenBrainz export ZIP, normalize listens into the canonical schema,
    and extract liked recording MBIDs from feedback.

    Parameters
    ----------
    zip_path : str
        Path to the ListenBrainz export ZIP file.

    Returns
    -------
    df : pandas.DataFrame
        Canonical listens DataFrame.
    likes : set of str
        Set of liked recording MBIDs from feedback.
    """
    user_info, feedback, listens = parse_listenbrainz_zip(zip_path)
    df = normalize_listens(listens, origin=["listenbrainz_zip"])
    likes = load_feedback(feedback)
    return df, likes