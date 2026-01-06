"""
user.py
User entity and caching for BrainzMRI.
"""

import gzip
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Set, Dict, Any, Optional

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
    Return a sorted list of cached usernames based on the user cache directory.
    """
    cache_root = get_cache_root()
    users_root = os.path.join(cache_root, "users")
    if not os.path.exists(users_root):
        return []
    names = []
    for entry in os.listdir(users_root):
        full = os.path.join(users_root, entry)
        if os.path.isdir(full):
            names.append(entry)
    return sorted(names)


@dataclass
class User:
    """
    Represents a BrainzMRI user and their canonical listens/feedback.

    For Step 4, this is focused on ListenBrainz ZIP ingestion and
    simple on-disk caching. Other sources (API, Last.fm, etc.) can
    be added later without breaking this interface.
    """

    username: str
    listens_df: pd.DataFrame = field(repr=False)
    liked_mbids: Set[str] = field(repr=False)
    cache_dir: str
    sources: list[Dict[str, Any]] = field(default_factory=list)

    # -------------------------
    # Construction helpers
    # -------------------------

    @staticmethod
    def _derive_username(user_info: Dict[str, Any]) -> str:
        """
        Derive a username from ListenBrainz user_info.

        Tries a few common keys and falls back to 'default' if none found.
        """
        for key in ("musicbrainz_id", "user_name", "username", "name"):
            if user_info.get(key):
                return str(user_info[key])
        return "default"

    @classmethod
    def from_listenbrainz_zip(
        cls,
        zip_path: str,
        cache_root: Optional[str] = None,
    ) -> "User":
        """
        Create a User from a ListenBrainz export ZIP and immediately
        write a cache snapshot to disk.

        This does NOT touch the GUI; it's purely a data operation.
        """
        user_info, feedback, listens = parsing.parse_listenbrainz_zip(zip_path)
        username = cls._derive_username(user_info)

        df = parsing.normalize_listens(listens, origin=["listenbrainz_zip"])
        liked = parsing.load_feedback(feedback)

        if cache_root is None:
            cache_root = get_cache_root()
        cache_dir = get_user_cache_dir(username)

        user = cls(
            username=username,
            listens_df=df,
            liked_mbids=liked,
            cache_dir=cache_dir,
            sources=[],
        )

        user._record_source_from_zip(zip_path)
        user.save_cache()
        return user

    @classmethod
    def from_cache(
        cls,
        username: str,
        cache_root: Optional[str] = None,
    ) -> "User":
        """
        Load a User from an existing cache on disk.

        Raises FileNotFoundError if required cache files are missing.
        """
        if cache_root is None:
            cache_root = get_cache_root()

        cache_dir = get_user_cache_dir(username)

        listens_path = os.path.join(cache_dir, "listens.jsonl.gz")
        likes_path = os.path.join(cache_dir, "likes.json")
        sources_path = os.path.join(cache_dir, "sources.json")

        if not os.path.exists(listens_path):
            raise FileNotFoundError(f"No cached listens found for user '{username}'.")
        if not os.path.exists(likes_path):
            raise FileNotFoundError(f"No cached likes found for user '{username}'.")
        if not os.path.exists(sources_path):
            raise FileNotFoundError(f"No cached sources found for user '{username}'.")

        listens_df = _load_listens_jsonl_gz(listens_path)

        with open(likes_path, "r", encoding="utf-8") as f:
            liked_mbids = set(json.load(f))

        with open(sources_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sources = data.get("sources", [])

        return cls(
            username=username,
            listens_df=listens_df,
            liked_mbids=liked_mbids,
            cache_dir=cache_dir,
            sources=sources,
        )

    # -------------------------
    # Cache I/O
    # -------------------------

    def save_cache(self) -> None:
        """
        Write listens, likes, and sources to the user cache directory.

        - listens.jsonl.gz : canonical listens
        - likes.json       : list of recording MBIDs
        - sources.json     : metadata about ingestion sources
        """
        listens_path = os.path.join(self.cache_dir, "listens.jsonl.gz")
        likes_path = os.path.join(self.cache_dir, "likes.json")
        sources_path = os.path.join(self.cache_dir, "sources.json")

        _save_listens_jsonl_gz(self.listens_df, listens_path)

        with open(likes_path, "w", encoding="utf-8") as f:
            json.dump(sorted(self.liked_mbids), f, indent=2)

        with open(sources_path, "w", encoding="utf-8") as f:
            json.dump({"sources": self.sources}, f, indent=2)

    def _record_source_from_zip(self, zip_path: str) -> None:
        """Append a ListenBrainz ZIP source record to self.sources."""
        self.sources.append(
            {
                "type": "listenbrainz_zip",
                "path": os.path.abspath(zip_path),
                "last_loaded": datetime.now(timezone.utc).isoformat(),
            }
        )

    # -------------------------
    # Convenience accessors
    # -------------------------

    def get_listens(self) -> pd.DataFrame:
        """Return the canonical listens DataFrame."""
        return self.listens_df

    def get_liked_mbids(self) -> Set[str]:
        """Return the set of liked recording MBIDs."""
        return self.liked_mbids


# -------------------------
# Helper functions
# -------------------------


def _save_listens_jsonl_gz(df: pd.DataFrame, path: str) -> None:
    """
    Save a canonical listens DataFrame as gzip-compressed JSONL.
    Each row is stored as a JSON object on its own line.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Convert timestamps to ISO strings
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
    """
    Load a canonical listens DataFrame from gzip-compressed JSONL.
    """
    records = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    if not records:
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

    # Build DataFrame first
    df = pd.DataFrame.from_records(records)

    # Convert ISO strings back to datetime
    if "listened_at" in df.columns:
        df["listened_at"] = pd.to_datetime(df["listened_at"], utc=True)

    return df