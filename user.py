"""
user.py
User entity and caching for BrainzMRI.
"""

import gzip
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Set, Dict, Any, Optional, List

import pandas as pd
import parsing


def get_app_root() -> str:
    """Return the application root directory (where this file lives)."""
    return os.path.abspath(os.path.dirname(__file__))


def get_cache_root() -> str:
    """Return the root cache directory for BrainzMRI."""
    app_root = get_app_root()
    cache_root = os.path.join(app_root, "cache")
    os.makedirs(cache_root, exist_ok=True)
    return cache_root


def get_user_cache_dir(username: str) -> str:
    """Return the cache directory for a specific user."""
    cache_root = get_cache_root()
    users_root = os.path.join(cache_root, "users")
    os.makedirs(users_root, exist_ok=True)

    user_dir = os.path.join(users_root, username)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def get_cached_usernames() -> list[str]:
    """
    Return a sorted list of cached usernames based on the user cache directory structure.
    """
    cache_root = get_cache_root()
    users_root = os.path.join(cache_root, "users")
    if not os.path.exists(users_root):
        return []
    
    names = []
    for entry in os.listdir(users_root):
        full_path = os.path.join(users_root, entry)
        if os.path.isdir(full_path):
            names.append(entry)
    return sorted(names)


@dataclass
class User:
    """
    Represents a BrainzMRI User.
    Manages loading/saving of personal data (listens, likes, api tokens).
    """
    username: str
    listens_df: pd.DataFrame = field(repr=False)
    liked_mbids: Set[str] = field(repr=False)
    cache_dir: str
    sources: dict = field(default_factory=dict)
    listenbrainz_token: Optional[str] = None
    
    # Thread safety for concurrent saves (Crawler + Likes Sync)
    _io_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def from_sources(
        cls,
        username: str,
        lastfm_username: Optional[str] = None,
        listenbrainz_username: Optional[str] = None,
        listenbrainz_token: Optional[str] = None,
        listenbrainz_zips: Optional[List[Dict[str, Any]]] = None,
        cache_root: Optional[str] = None
    ) -> "User":
        """
        Create a new User from scratch (import mode).
        """
        if cache_root is None:
            cache_root = get_cache_root()
            
        cache_dir = get_user_cache_dir(username)
        
        sources = {
            "lastfm_username": lastfm_username or None,
            "listenbrainz_username": listenbrainz_username or None,
            "listenbrainz_zips": listenbrainz_zips or [],
        }

        # Create empty user
        user = cls(
            username=username,
            listens_df=_empty_listens_df(),
            liked_mbids=set(),
            cache_dir=cache_dir,
            sources=sources,
            listenbrainz_token=listenbrainz_token
        )
        
        # Initial Save
        user.save_cache()
        return user

    @classmethod
    def from_cache(cls, username: str, cache_root: Optional[str] = None) -> "User":
        """
        Load an existing user from the local cache.
        """
        if cache_root is None:
            cache_root = get_cache_root()
            
        cache_dir = get_user_cache_dir(username)
        listens_path = os.path.join(cache_dir, "listens.jsonl.gz")
        likes_path = os.path.join(cache_dir, "likes.json")
        sources_path = os.path.join(cache_dir, "sources.json")
        auth_path = os.path.join(cache_dir, "auth.json")

        if os.path.exists(listens_path):
            listens_df = _load_listens_jsonl_gz(listens_path)
        else:
            listens_df = _empty_listens_df()

        if os.path.exists(likes_path):
            with open(likes_path, "r", encoding="utf-8") as f:
                liked_mbids = set(json.load(f))
        else:
            liked_mbids = set()

        if not os.path.exists(sources_path):
            raise FileNotFoundError(f"No cached sources found for user '{username}'.")

        with open(sources_path, "r", encoding="utf-8") as f:
            sources = json.load(f)
            
        listenbrainz_token = None
        if os.path.exists(auth_path):
            try:
                with open(auth_path, "r", encoding="utf-8") as f:
                    auth_data = json.load(f)
                    listenbrainz_token = auth_data.get("listenbrainz_token")
            except Exception:
                pass

        return cls(
            username=username,
            listens_df=listens_df,
            liked_mbids=liked_mbids,
            cache_dir=cache_dir,
            sources=sources,
            listenbrainz_token=listenbrainz_token
        )

    def save_cache(self) -> None:
        """Persist user data to disk. Thread-safe."""
        listens_path = os.path.join(self.cache_dir, "listens.jsonl.gz")
        likes_path = os.path.join(self.cache_dir, "likes.json")
        sources_path = os.path.join(self.cache_dir, "sources.json")
        auth_path = os.path.join(self.cache_dir, "auth.json")

        with self._io_lock:
            _save_listens_jsonl_gz(self.listens_df, listens_path)

            with open(likes_path, "w", encoding="utf-8") as f:
                json.dump(sorted(self.liked_mbids), f, indent=2)

            with open(sources_path, "w", encoding="utf-8") as f:
                json.dump(self.sources, f, indent=2)
                
            auth_data = {"listenbrainz_token": self.listenbrainz_token}
            with open(auth_path, "w", encoding="utf-8") as f:
                json.dump(auth_data, f, indent=2)
    
    def sync_likes(self, new_mbids: Set[str]) -> None:
        """
        Replace internal liked_mbids with a fresh set from the server and save.
        Thread-safe.
        """
        with self._io_lock:
            self.liked_mbids = new_mbids
            # We call inner save logic here to avoid re-entering lock if we called save_cache()
            # But since RLock isn't guaranteed by default Lock, we duplicate just the likes save
            # or use a helper. 
            # Safest is to just save the likes file specifically to avoid overhead of saving everything.
            likes_path = os.path.join(self.cache_dir, "likes.json")
            with open(likes_path, "w", encoding="utf-8") as f:
                json.dump(sorted(self.liked_mbids), f, indent=2)

    def ingest_listenbrainz_zip(self, zip_path: str) -> None:
        """
        Parse a ZIP file and merge it into the current history.
        REFACTORED: Uses centralized parsing logic from parsing.py
        """
        # Call the unified loader instead of manual steps
        df_new, likes_new = parsing.load_listens_from_zip(zip_path)

        with self._io_lock:
            # Merge Listens
            if self.listens_df is None or self.listens_df.empty:
                combined = df_new.copy()
            else:
                combined = pd.concat([self.listens_df, df_new], ignore_index=True)

            # Deduplicate
            if not combined.empty:
                # We assume unique on artist/album/track/timestamp
                dedupe_cols = ["artist", "album", "track_name", "listened_at", "recording_mbid"]
                # Filter cols that actually exist
                existing_cols = [c for c in dedupe_cols if c in combined.columns]
                if existing_cols:
                    combined = combined.drop_duplicates(subset=existing_cols, keep="first")

            self.listens_df = combined
            self.liked_mbids.update(likes_new)

            # Record Source
            zips_list = self.sources.get("listenbrainz_zips") or []
            zips_list.append({
                "path": os.path.abspath(zip_path),
                "ingested_at": datetime.now(timezone.utc).isoformat()
            })
            self.sources["listenbrainz_zips"] = zips_list

        self.save_cache()

    def get_listens(self) -> pd.DataFrame:
        return self.listens_df

    def get_liked_mbids(self) -> Set[str]:
        return self.liked_mbids

    def get_lastfm_username(self) -> Optional[str]:
        return self.sources.get("lastfm_username")

    def get_listenbrainz_username(self) -> Optional[str]:
        return self.sources.get("listenbrainz_username")

    def update_sources(self, lastfm_username: Optional[str], listenbrainz_username: Optional[str], listenbrainz_token: Optional[str]) -> None:
        with self._io_lock:
            self.sources["lastfm_username"] = lastfm_username or None
            self.sources["listenbrainz_username"] = listenbrainz_username or None
            self.listenbrainz_token = listenbrainz_token or None
        self.save_cache()

    # -------------------------
    # Incremental Update Support
    # -------------------------

    @property
    def intermediate_cache_path(self) -> str:
        """Path to the temporary intermediate cache file."""
        return os.path.join(self.cache_dir, "intermediate_listens.jsonl")

    def get_latest_listen_timestamp(self) -> int:
        """
        Return the UNIX timestamp of the most recent listen in the primary cache.
        Returns 0 if no listens exist.
        """
        if self.listens_df is None or self.listens_df.empty:
            return 0
        
        # Ensure listened_at is datetime
        if not pd.api.types.is_datetime64_any_dtype(self.listens_df["listened_at"]):
            return 0
            
        try:
            # Get max, convert to UTC timestamp
            latest = self.listens_df["listened_at"].max()
            return int(latest.timestamp())
        except Exception:
            return 0

    def load_intermediate_listens(self) -> pd.DataFrame:
        """
        Load the intermediate cache if it exists. 
        Returns normalized DataFrame or empty DataFrame.
        """
        path = self.intermediate_cache_path
        if not os.path.exists(path):
            return _empty_listens_df()
            
        records = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
        except Exception:
            # If corrupt, discard/return empty
            return _empty_listens_df()
            
        if not records:
            return _empty_listens_df()
            
        # These records are raw listen objects from API.
        # Normalize them to match the main DataFrame schema.
        return parsing.normalize_listens(records, origin=["api_incremental"])

    def append_to_intermediate_cache(self, raw_listens: List[Dict[str, Any]]) -> None:
        """
        Append raw API listen objects to the intermediate JSONL file.
        """
        path = self.intermediate_cache_path
        with self._io_lock:
            with open(path, "a", encoding="utf-8") as f:
                for listen in raw_listens:
                    f.write(json.dumps(listen, ensure_ascii=False) + "\n")

    def merge_intermediate_cache(self) -> None:
        """
        Loads intermediate cache, merges with main cache, deduplicates, saves, 
        and deletes the intermediate file.
        """
        df_new = self.load_intermediate_listens()
        if df_new.empty:
            # Just clean up file if empty
            with self._io_lock:
                if os.path.exists(self.intermediate_cache_path):
                    os.remove(self.intermediate_cache_path)
            return

        with self._io_lock:
            if self.listens_df is None or self.listens_df.empty:
                combined = df_new.copy()
            else:
                combined = pd.concat([self.listens_df, df_new], ignore_index=True)

            # Dedupe based on content
            dedupe_cols = ["artist", "album", "track_name", "listened_at", "recording_mbid"]
            existing_cols = [c for c in dedupe_cols if c in combined.columns]
            
            if existing_cols:
                # Sort to ensure we keep the most "complete" or recent version if duplicates exist
                combined = combined.sort_values(by="listened_at", ascending=False)
                combined = combined.drop_duplicates(subset=existing_cols, keep="first")

            self.listens_df = combined
            # Save handles file I/O
        
        self.save_cache()
        
        # Delete intermediate
        with self._io_lock:
            if os.path.exists(self.intermediate_cache_path):
                os.remove(self.intermediate_cache_path)

    def discard_intermediate_cache(self) -> None:
        """Force delete the intermediate cache."""
        with self._io_lock:
            if os.path.exists(self.intermediate_cache_path):
                os.remove(self.intermediate_cache_path)


# -------------------------
# Helper functions
# -------------------------

def _empty_listens_df() -> pd.DataFrame:
    """Return an empty canonical listens DataFrame with the expected columns."""
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
            records.append(json.loads(line))
    
    if not records:
        return _empty_listens_df()
        
    df = pd.DataFrame.from_records(records)
    
    # Restore datetime objects
    if "listened_at" in df.columns:
        df["listened_at"] = pd.to_datetime(df["listened_at"], utc=True)
        
    return df