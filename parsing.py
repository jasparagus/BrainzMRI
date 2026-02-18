"""
parsing.py
Data ingestion, normalization, and key generation logic for BrainzMRI.
"""

import zipfile
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional
import unicodedata
import pandas as pd
import logging


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

        artist_name = meta.get("artist_name", "")
        track_name = meta.get("track_name", "")
        album_name = meta.get("release_name", "")

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

# ------------------------------------------------------------
# Playlist Import (CSV, XSPF, JSPF, TXT)
# ------------------------------------------------------------

def parse_playlist(file_path: str) -> pd.DataFrame:
    """
    Master dispatcher for playlist import.
    Detects format by extension and delegates to specific parser.
    Returns a normalized DataFrame with consistent schema.
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".csv":
        df = parse_generic_csv(file_path)
    elif ext == ".jspf":
        df = parse_jspf(file_path)
    elif ext == ".xspf":
        df = parse_xspf(file_path)
    elif ext == ".txt":
        df = parse_txt_playlist(file_path)
    else:
        # Fallback to CSV if unknown, or raise error
        raise ValueError(f"Unsupported playlist format: {ext}")

    # Final Normalization for all formats
    # Ensure standard columns exist
    required_cols = ["artist", "track_name", "album", "duration_ms", "listened_at", "recording_mbid"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None
            
    # Sanitize strings
    df["artist"] = df["artist"].fillna("").astype(str)
    df["track_name"] = df["track_name"].fillna("").astype(str)
    df["album"] = df["album"].fillna("").astype(str)
    
    # Ensure duration is int (0 if missing)
    df["duration_ms"] = df["duration_ms"].fillna(0).astype(int)
    
    # Ensure IDs are strings or None
    for col in ["recording_mbid", "release_mbid", "artist_mbid"]:
        if col not in df.columns:
            df[col] = None
        else:
            df[col] = df[col].astype(str).replace({"nan": None, "None": None, "NaN": None, "": None})

    df["origin"] = "playlist_import"
    
    # Generate keys
    make_track_key_series(df)
    
    return df

def parse_generic_csv(csv_path: str) -> pd.DataFrame:
    """
    Parse a generic CSV.
    Expects columns: Artist, Track Name (case insensitive).
    Optional: Album, MBID, Timestamp.
    """
    df = pd.read_csv(csv_path)

    # Normalize headers
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    # CLEANUP: Drop unnamed/junk columns and empty columns
    # This prevents UI crashes when 18+ junk columns are passed to Treeview
    df = df.loc[:, ~df.columns.str.contains('^unnamed')]
    df = df.dropna(axis=1, how='all')

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

    return df

def parse_jspf(file_path: str) -> pd.DataFrame:
    """
    Parse a JSPF (JSON XSPF) playlist.
    Supports basic JSPF and ListenBrainz JSPF extensions.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    playlist = data.get("playlist", {})
    tracks = playlist.get("track", [])
    
    rows = []
    for t in tracks:
        row = {
            "track_name": t.get("title", "Unknown"),
            "artist": t.get("creator", "Unknown"),
            "album": t.get("album", "Unknown"),
            "duration_ms": t.get("duration", 0),
            "recording_mbid": None
        }
        
        # Try to extract MBID from identifier
        # Standard JSPF identifier is a list or string
        identifiers = t.get("identifier")
        if identifiers:
            if isinstance(identifiers, str):
                identifiers = [identifiers]
            for ident in identifiers:
                if "musicbrainz.org/recording/" in ident:
                    row["recording_mbid"] = ident.split("recording/")[-1]
                    break
        
        # LB Extension fallback for MBID
        if not row["recording_mbid"]:
            ext = t.get("extension", {})
            lb_ext = ext.get("https://musicbrainz.org/doc/jspf#track", {})
            # simpler JSPF might just put mbid in additional_metadata? 
            # Check LB specific structure if needed, but 'identifier' is the standard place.
            pass

        rows.append(row)
        
    if not rows:
        return pd.DataFrame(columns=["artist", "track_name", "album"])
        
    return pd.DataFrame(rows)

def parse_xspf(file_path: str) -> pd.DataFrame:
    """
    Parse an XSPF (XML) playlist.
    """
    tree = ET.parse(file_path)
    root = tree.getroot()
    # Namespace handling
    ns = {'ns': 'http://xspf.org/ns/0/'} 

    rows = []
    # trackList is usually a direct child of playlist
    track_list = root.find("ns:trackList", ns)
    if track_list is not None:
        for track in track_list.findall("ns:track", ns):
            title = track.find("ns:title", ns)
            creator = track.find("ns:creator", ns)
            album = track.find("ns:album", ns)
            duration = track.find("ns:duration", ns) # in ms
            
            row = {
                "track_name": title.text if title is not None else "Unknown",
                "artist": creator.text if creator is not None else "Unknown",
                "album": album.text if album is not None else "Unknown",
                "duration_ms": int(duration.text) if duration is not None and duration.text.isdigit() else 0,
                "recording_mbid": None
            }
            
            # Extract MBID from identifier
            # <identifier>http://musicbrainz.org/recording/...</identifier>
            identifier = track.find("ns:identifier", ns)
            if identifier is not None and identifier.text:
                if "musicbrainz.org/recording/" in identifier.text:
                    row["recording_mbid"] = identifier.text.split("recording/")[-1]
            
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["artist", "track_name", "album"])
        
    return pd.DataFrame(rows)

def parse_txt_playlist(file_path: str) -> pd.DataFrame:
    """
    Parse a TXT playlist, specifically targeting the YouTube Music copy-paste format.
    Format is blocks of: Title \n Artist \n Album \n Duration
    Handles cases where Duration is missing (separated by empty lines).
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Normalize: Ensure unified newlines and wrap in newlines to catch start/end tokens
    content = '\n' + content.replace('\r\n', '\n') + '\n'
    
    # Split by DELIMITER.
    # A delimiter is EITHER:
    # 1. A Duration Line (e.g. "4:00" or " 4:00 ")
    # 2. A Significant Gap (2 or more empty lines, i.e., 3+ consecutive newlines)
    #
    # Regex Breakdown:
    # \n\s*                  : Start with newline (and optional whitespace)
    # (?:
    #   (\d{1,2}:\d{2}(?::\d{2})?)  : Group 1: Duration (MM:SS or HH:MM:SS)
    #   \s*\n                       : Must be followed by newline
    # |
    #   (?:\s*\n){2,}               : OR: 2 or more lines of just whitespace/newlines
    # )
    regex = r'\n\s*(?:(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:\n)|(?:\s*\n){2,})'
    
    parts = re.split(regex, content)
    
    # parts[0] = Text before first delimiter
    # parts[1] = Delimiter Capture Group 1 (Duration) OR None (if Gap)
    # parts[2] = Text after first delimiter
    # ...
    
    rows = []
    
    if len(parts) > 1:
        current_block_text = parts[0]
        
        for i in range(1, len(parts), 2):
            duration_str = parts[i] # Can be None if it was a Gap match
            
            # Parse Duration
            duration_ms = 0
            if duration_str:
                try:
                    d_parts = list(map(int, duration_str.split(':')))
                    if len(d_parts) == 2:
                        duration_ms = ((d_parts[0] * 60) + d_parts[1]) * 1000
                    elif len(d_parts) == 3:
                         duration_ms = ((d_parts[0] * 3600) + (d_parts[1] * 60) + d_parts[2]) * 1000
                except ValueError:
                    pass

            # Parse Block text collected in previous iteration (or start)
            text_block = current_block_text.strip()
            if text_block:
                lines = [line.strip() for line in text_block.split('\n') if line.strip()]
                
                if len(lines) >= 2:
                    title = lines[0]
                    album = lines[-1]
                    
                    if len(lines) > 2:
                        artist_lines = lines[1:-1]
                        raw_artist = " ".join(artist_lines)
                        # Cleaning logic from original script
                        artist = re.sub(r'\s+([,&])\s+', r'\1 ', raw_artist)
                        artist = artist.replace(" ,", ",").replace(" &", " &")
                    else:
                        artist = lines[1]
                        album = "Unknown Album" # Fallback if only 2 lines (Title, Artist)
                    
                    rows.append({
                        "track_name": title,
                        "artist": artist,
                        "album": album,
                        "duration_ms": duration_ms
                    })
            
            # Prepare for next loop
            if i + 1 < len(parts):
                current_block_text = parts[i+1]
                
    return pd.DataFrame(rows)


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