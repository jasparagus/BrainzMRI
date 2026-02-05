"""
user.py
User entity and caching for BrainzMRI.
"""

import gzip
import json
import os
import threading
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Set, Dict, Any, Optional, List

import pandas as pd
import parsing
from config import config  # REFACTORED: Import config


def get_user_cache_dir(username: str) -> str:
    """Return the cache directory for a specific user."""
    users_root = os.path.join(config.cache_dir, "users")
    os.makedirs(users_root, exist_ok=True)

    user_dir = os.path.join(users_root, username)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def get_cached_usernames() -> list[str]:
    """
    Return a sorted list of cached usernames.
    Determined by subdirectories in cache/users/.
    """
    users_root = os.path.join(config.cache_dir, "users")
    if not os.path.exists(users_root):
        return []
    
    names = []
    for entry in os.scandir(users_root):
        if entry.is_dir():
            # Check if user.json exists to confirm it's valid
            if os.path.exists(os.path.join(entry.path, "user.json")):
                names.append(entry.name)
    return sorted(names)


# ------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------

def _make_empty_listens_df() -> pd.DataFrame:
    """Return an empty canonical listens DataFrame with the expected columns."""
    # REVERTED: Do not enforce types here to avoid instability with empty DFs.
    # Type handling is now deferred to reporting.py
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


def _save_listens_jsonl_gz(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df = df.copy()
    if "listened_at" in df.columns:
        df["listened_at"] = df["listened_at"].apply(
            lambda x: x.isoformat() if hasattr(x, "isoformat") else x
        )
    records = df.to_dict(orient="records")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load_listens_jsonl_gz(path: str) -> pd.DataFrame:
    records = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                records.append(rec)
            except json.JSONDecodeError:
                continue
    
    if not records:
        return _make_empty_listens_df()

    df = pd.DataFrame(records)
    
    if "listened_at" in df.columns:
        df["listened_at"] = pd.to_datetime(df["listened_at"], utc=True)
        
    return df


@dataclass
class User:
    username: str
    lastfm_username: str = ""
    lastfm_api_key: str = ""  # New Field
    listenbrainz_username: str = ""
    listenbrainz_token: str = ""
    
    # Internal Set of Liked MBIDs (Recording IDs)
    liked_recording_mbids: Set[str] = field(default_factory=set)
    
    # I/O Lock for thread safety
    _io_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def from_sources(cls, username: str, lastfm_username: str = "", lastfm_api_key: str = "", listenbrainz_username: str = "", listenbrainz_token: str = "", listenbrainz_zips: list = None) -> "User":
        """
        Create a new User, initialize cache, and optionally ingest ZIPs.
        """
        user = cls(username, lastfm_username, lastfm_api_key, listenbrainz_username, listenbrainz_token)
        user.save_cache()  # Initialize structure
        
        if listenbrainz_zips:
            for zip_path in listenbrainz_zips:
                user.ingest_listenbrainz_zip(zip_path)
                
        logging.info(f"Created new user: {username}")
        return user

    @classmethod
    def from_cache(cls, username: str) -> "User":
        """Load a user from the local cache directory."""
        user_dir = get_user_cache_dir(username)
        user_json_path = os.path.join(user_dir, "user.json")
        
        if not os.path.exists(user_json_path):
            raise FileNotFoundError(f"User '{username}' not found in cache.")
            
        with open(user_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        user = cls(
            username=data["username"],
            lastfm_username=data.get("lastfm_username", ""),
            lastfm_api_key=data.get("lastfm_api_key", ""),
            listenbrainz_username=data.get("listenbrainz_username", ""),
            listenbrainz_token=data.get("listenbrainz_token", "")
        )
        
        # Load Likes
        likes_path = os.path.join(user_dir, "likes.json")
        if os.path.exists(likes_path):
            try:
                with open(likes_path, "r", encoding="utf-8") as f:
                    likes_data = json.load(f)
                    user.liked_recording_mbids = set(likes_data.get("liked_mbids", []))
            except Exception:
                pass
        
        logging.info(f"Loaded user: {username}")
        return user

    def save_cache(self) -> None:
        """Persist user metadata to user.json."""
        with self._io_lock:
            user_dir = get_user_cache_dir(self.username)
            data = {
                "username": self.username,
                "lastfm_username": self.lastfm_username,
                "lastfm_api_key": self.lastfm_api_key,
                "listenbrainz_username": self.listenbrainz_username,
                "listenbrainz_token": self.listenbrainz_token,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(os.path.join(user_dir, "user.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

    def _save_likes(self):
        """Persist likes to likes.json."""
        # Note: Caller should hold lock if needed, but atomic write is generally safe
        user_dir = get_user_cache_dir(self.username)
        data = {
            "liked_mbids": list(self.liked_recording_mbids)
        }
        with open(os.path.join(user_dir, "likes.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=None)

    # ------------------------------------------------------------
    # Source Management Methods
    # ------------------------------------------------------------

    def get_lastfm_username(self) -> str:
        return self.lastfm_username

    def get_listenbrainz_username(self) -> str:
        return self.listenbrainz_username

    def update_sources(self, lastfm_username: str, lastfm_api_key: str, listenbrainz_username: str, listenbrainz_token: str):
        """Update user credentials and save."""
        self.lastfm_username = lastfm_username or ""
        self.lastfm_api_key = lastfm_api_key or ""
        self.listenbrainz_username = listenbrainz_username or ""
        self.listenbrainz_token = listenbrainz_token or ""
        self.save_cache()
        logging.info(f"Updated sources/credentials for user: {self.username}")

    # ------------------------------------------------------------
    # Ingestion Methods
    # ------------------------------------------------------------

    def ingest_listenbrainz_zip(self, zip_path: str) -> None:
        """Ingest a ListenBrainz ZIP export."""
        logging.info(f"Ingesting ZIP for {self.username}: {zip_path}")
        new_df, new_likes = parsing.load_listens_from_zip(zip_path)
        
        with self._io_lock:
            # 1. Merge Listens
            current_df = self._load_listens_df()
            merged_df = pd.concat([current_df, new_df]).drop_duplicates(
                subset=["listened_at", "track_name", "artist"]
            ).sort_values("listened_at", ascending=False)
            
            self._save_listens_df(merged_df)
            
            # 2. Merge Likes
            self.liked_recording_mbids.update(new_likes)
            self._save_likes()
        
        logging.info(f"Ingestion complete. Total history: {len(merged_df)} rows.")

    def sync_likes(self, new_mbids: Set[str]):
        """Replace local likes with a fresh set from the server (Atomic Replacement)."""
        with self._io_lock:
            self.liked_recording_mbids = new_mbids
            self._save_likes()

    def get_listens(self) -> pd.DataFrame:
        """Return the user's entire listening history."""
        with self._io_lock:
            return self._load_listens_df()

    def get_liked_mbids(self) -> Set[str]:
        return self.liked_recording_mbids

    # ------------------------------------------------------------
    # Storage Helpers
    # ------------------------------------------------------------

    def _load_listens_df(self) -> pd.DataFrame:
        path = os.path.join(get_user_cache_dir(self.username), "listens.jsonl.gz")
        if not os.path.exists(path):
            return _make_empty_listens_df()
        return _load_listens_jsonl_gz(path)

    def _save_listens_df(self, df: pd.DataFrame):
        path = os.path.join(get_user_cache_dir(self.username), "listens.jsonl.gz")
        _save_listens_jsonl_gz(df, path)

    # ------------------------------------------------------------
    # Sync / Crawl Logic (The Island Strategy)
    # ------------------------------------------------------------

    def get_latest_listen_timestamp(self) -> int:
        """Get the timestamp of the most recent listen in the main DB."""
        df = self.get_listens()
        if df.empty:
            return 0
        return int(df["listened_at"].max().timestamp())

    def append_to_intermediate_cache(self, listens: list[dict]):
        """Append raw API listen objects to the 'Island' cache."""
        path = os.path.join(get_user_cache_dir(self.username), "listens_intermediate.jsonl")
        
        # Write mode 'a' (append)
        with self._io_lock:
            with open(path, "a", encoding="utf-8") as f:
                for listen in listens:
                    f.write(json.dumps(listen) + "\n")

    def load_intermediate_listens(self) -> pd.DataFrame:
        """Load the 'Island' cache as a DataFrame."""
        path = os.path.join(get_user_cache_dir(self.username), "listens_intermediate.jsonl")
        if not os.path.exists(path):
            return pd.DataFrame()
            
        raw_listens = []
        with self._io_lock:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        raw_listens.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        
        if not raw_listens:
            return pd.DataFrame()
            
        # Normalize using parsing logic
        return parsing.normalize_listens(raw_listens, origin="api_sync")

    def merge_intermediate_cache(self):
        """Merge the 'Island' into the 'Continent' and delete the intermediate file."""
        island_df = self.load_intermediate_listens()
        if island_df.empty:
            return

        with self._io_lock:
            continent_df = self._load_listens_df()
            
            merged_df = pd.concat([continent_df, island_df]).drop_duplicates(
                subset=["listened_at", "track_name", "artist"]
            ).sort_values("listened_at", ascending=False)
            
            self._save_listens_df(merged_df)
            
            # Delete intermediate file
            path = os.path.join(get_user_cache_dir(self.username), "listens_intermediate.jsonl")
            if os.path.exists(path):
                os.remove(path)

    def get_listenbrainz_username(self) -> str:
        return self.listenbrainz_username