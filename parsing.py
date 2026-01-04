import zipfile
import json
import pandas as pd
import os
from datetime import datetime, UTC
from tkinter import Tk, filedialog


def select_zip_file() -> str:
    """Open a file dialog for selecting a ListenBrainz export ZIP file."""
    root = Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select ListenBrainz Export ZIP",
        filetypes=[("ZIP files", "*.zip")],
    )
    return file_path


def parse_listenbrainz_zip(zip_path: str):
    """Parse ListenBrainz export ZIP and extract user info, feedback, and listens."""
    with zipfile.ZipFile(zip_path, "r") as z:
        user_info = json.loads(z.read("user.json").decode("utf-8"))

        feedback = []
        if "feedback.jsonl" in z.namelist():
            with z.open("feedback.jsonl") as f:
                for line in f:
                    feedback.append(json.loads(line.decode("utf-8")))

        listens = []
        for name in z.namelist():
            if name.startswith("listens/") and name.endswith(".jsonl"):
                with z.open(name) as f:
                    for line in f:
                        listens.append(json.loads(line.decode("utf-8")))

    return user_info, feedback, listens


def normalize_listens(listens, zip_path: str | None = None) -> pd.DataFrame:
    """Normalize raw ListenBrainz listen objects into a flat DataFrame."""
    records = []

    log_file = None
    if zip_path:
        base_dir = os.path.dirname(zip_path)
        reports_dir = os.path.join(base_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        log_file = os.path.join(reports_dir, "missing_album_info.txt")

        if os.path.exists(log_file):
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("")

    for l in listens:
        meta = l.get("track_metadata", {})
        mbid_mapping = meta.get("mbid_mapping") or {}

        # Artist extraction
        artists = []
        if "artists" in mbid_mapping and mbid_mapping["artists"]:
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

        album_name = meta.get("release_name", "Unknown")

        if album_name == "Unknown" and log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(
                    f"[WARN] Unknown album- Artist='{artists[0]}', "
                    f"Track='{meta.get('track_name','Unknown')}', Album='Unknown'\n"
                )

        # Duration
        info = meta.get("additional_info", {}) or {}
        duration_ms = info.get("duration_ms")
        if duration_ms is None and "duration" in info:
            duration_ms = info["duration"] * 1000

        listened_at = l.get("listened_at")
        listened_dt = datetime.fromtimestamp(listened_at, UTC) if listened_at else None

        # Recording MBID
        recording_mbid = None
        if meta.get("mbid_mapping"):
            recording_mbid = meta["mbid_mapping"].get("recording_mbid")
        elif meta.get("additional_info") and meta["additional_info"].get(
            "lastfm_recording_mbid"
        ):
            recording_mbid = meta["additional_info"]["lastfm_recording_mbid"]

        # Artist → MBID map
        artist_mbid_map = {}
        if "artists" in mbid_mapping and mbid_mapping["artists"]:
            for a in mbid_mapping["artists"]:
                name = a.get("artist_credit_name")
                mbid = a.get("artist_mbid")
                if name:
                    artist_mbid_map[name] = mbid

        for artist in artists:
            records.append(
                {
                    "artist": artist,
                    "artist_mbid": artist_mbid_map.get(artist),
                    "album": album_name,
                    "track_name": meta.get("track_name", "Unknown"),
                    "duration_ms": duration_ms or 0,
                    "listened_at": listened_dt,
                    "recording_mbid": recording_mbid,
                }
            )

    return pd.DataFrame(records)


def load_feedback(feedback):
    """Extract liked recording MBIDs from feedback entries."""
    likes = set()
    for row in feedback:
        if row.get("score") == 1 and row.get("recording_mbid"):
            likes.add(row["recording_mbid"])
    return likes


# CLI entry point preserved
if __name__ == "__main__":
    zip_path = select_zip_file()
    if not zip_path:
        raise SystemExit("No ZIP file selected.")

    user_info, feedback, listens = parse_listenbrainz_zip(zip_path)
    df = normalize_listens(listens, zip_path)
    print(df.head())