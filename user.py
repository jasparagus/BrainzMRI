"""
user.py
User entity and caching for BrainzMRI.
"""

import gzip
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Set, Dict, Any, Optional, List, Tuple

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

    The user is now source-oriented:
    - App username (internal ID, folder name)
    - Optional Last.fm username
    - Optional ListenBrainz username
    - Zero or more ListenBrainz ZIP sources (metadata only)

    Canonical listens and likes are stored in:
    - listens.jsonl.gz : canonical listens
    - likes.json       : list of recording MBIDs
    - sources.json     : metadata about ingestion sources
    """

    username: str  # App username
    listens_df: pd.DataFrame = field(repr=False)
    liked_mbids: Set[str] = field(repr=False)
    cache_dir: str
    sources: dict = field(default_factory=dict)

    # -------------------------
    # Construction helpers
    # -------------------------

    @classmethod
    def from_sources(
        cls,
        username: str,
        lastfm_username: Optional[str] = None,
        listenbrainz_username: Optional[str] = None,
        listenbrainz_zips: Optional[List[Dict[str, Any]]] = None,
        cache_root: Optional[str] = None,
    ) -> "User":
        """
        Create a new User from source metadata only.

        This does NOT ingest any ZIPs; it only initializes:
        - sources.json
        - an empty listens_df / liked_mbids

        ZIP ingestion is performed explicitly via ingest_zip().
        """
        if cache_root is None:
            cache_root = get_cache_root()

        cache_dir = get_user_cache_dir(username)

        sources = {
            "lastfm_username": lastfm_username or None,
            "listenbrainz_username": listenbrainz_username or None,
            "listenbrainz_zips": listenbrainz_zips or [],
        }

        user = cls(
            username=username,
            listens_df=_empty_listens_df(),
            liked_mbids=set(),
            cache_dir=cache_dir,
            sources=sources,
        )

        user.save_cache()  # persist initial sources.json + empty data
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

        # listens.jsonl.gz may be missing for a newly created user with no ingested ZIPs
        if os.path.exists(listens_path):
            listens_df = _load_listens_jsonl_gz(listens_path)
        else:
            listens_df = _empty_listens_df()

        # likes.json may also be missing in that case
        if os.path.exists(likes_path):
            with open(likes_path, "r", encoding="utf-8") as f:
                liked_mbids = set(json.load(f))
        else:
            liked_mbids = set()

        # sources.json is required for a valid user
        if not os.path.exists(sources_path):
            raise FileNotFoundError(f"No cached sources found for user '{username}'.")

        with open(sources_path, "r", encoding="utf-8") as f:
            sources = json.load(f)

        return cls(
            username=username,
            listens_df=listens_df,
            liked_mbids=liked_mbids,
            cache_dir=cache_dir,
            sources=sources,
        )

    # Legacy constructor retained for compatibility if needed elsewhere.
    # Not used by the new GUI flow, but preserved to avoid breaking external callers.
    @classmethod
    def from_listenbrainz_zip(
        cls,
        zip_path: str,
        cache_root: Optional[str] = None,
    ) -> "User":
        """
        Legacy helper: Create a User from a ListenBrainz export ZIP and immediately
        write a cache snapshot to disk, deriving username from user_info.

        The new GUI should prefer from_sources() + ingest_zip().
        """
        user_info, feedback, listens = parsing.parse_listenbrainz_zip(zip_path)
        username = cls._derive_username(user_info)

        df = parsing.normalize_listens(listens, origin=["listenbrainz_zip"])
        liked = parsing.load_feedback(feedback)

        if cache_root is None:
            cache_root = get_cache_root()
        cache_dir = get_user_cache_dir(username)

        sources = {
            "lastfm_username": None,
            "listenbrainz_username": None,
            "listenbrainz_zips": [
                {
                    "path": os.path.abspath(zip_path),
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }

        user = cls(
            username=username,
            listens_df=df,
            liked_mbids=liked,
            cache_dir=cache_dir,
            sources=sources,
        )

        user.save_cache()
        return user

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

    # -------------------------
    # Cache I/O
    # -------------------------

    def save_cache(self) -> None:
        """
        Write listens, likes, and sources to the user cache directory.

        - listens.jsonl.gz : canonical listens (may be empty)
        - likes.json       : list of recording MBIDs (may be empty)
        - sources.json     : metadata about ingestion sources
        """
        listens_path = os.path.join(self.cache_dir, "listens.jsonl.gz")
        likes_path = os.path.join(self.cache_dir, "likes.json")
        sources_path = os.path.join(self.cache_dir, "sources.json")

        _save_listens_jsonl_gz(self.listens_df, listens_path)

        with open(likes_path, "w", encoding="utf-8") as f:
            json.dump(sorted(self.liked_mbids), f, indent=2)

        with open(sources_path, "w", encoding="utf-8") as f:
            json.dump(self.sources, f, indent=2)

    # -------------------------
    # Ingestion from sources
    # -------------------------

    def ingest_listenbrainz_zip(self, zip_path: str) -> None:
        """
        Ingest a ListenBrainz ZIP into this user's canonical listens and likes.

        Behavior:
        - Parse ZIP
        - Normalize listens
        - Append to existing listens
        - Dedupe (using existing logic from parsing / canonicalization layer)
        - Merge likes
        - Update listens.jsonl.gz, likes.json
        - Append ZIP metadata to sources["listenbrainz_zips"]
        """
        # Parse raw data from ZIP
        user_info, feedback, listens = parsing.parse_listenbrainz_zip(zip_path)

        df_new = parsing.normalize_listens(listens, origin=["listenbrainz_zip"])
        likes_new = parsing.load_feedback(feedback)

        # Append + dedupe listens
        if self.listens_df is None or self.listens_df.empty:
            combined = df_new.copy()
        else:
            combined = pd.concat([self.listens_df, df_new], ignore_index=True)

        # Dedupe: reuse canonicalization semantics
        # For now, we dedupe based on a subset of columns:
        # (artist, album, track_name, listened_at, recording_mbid)
        if not combined.empty:
            dedupe_cols = [
                "artist",
                "album",
                "track_name",
                "listened_at",
                "recording_mbid",
            ]
            existing_cols = [c for c in dedupe_cols if c in combined.columns]
            if existing_cols:
                combined = combined.drop_duplicates(subset=existing_cols, keep="first")

        self.listens_df = combined

        # Merge likes
        self.liked_mbids.update(likes_new)

        # Record ZIP source metadata
        zips_list = self.sources.get("listenbrainz_zips") or []
        zips_list.append(
            {
                "path": os.path.abspath(zip_path),
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.sources["listenbrainz_zips"] = zips_list

        # Persist updated cache
        self.save_cache()

    # -------------------------
    # Convenience accessors
    # -------------------------

    def get_listens(self) -> pd.DataFrame:
        """Return the canonical listens DataFrame."""
        return self.listens_df

    def get_liked_mbids(self) -> Set[str]:
        """Return the set of liked recording MBIDs."""
        return self.liked_mbids

    def get_lastfm_username(self) -> Optional[str]:
        return self.sources.get("lastfm_username")

    def get_listenbrainz_username(self) -> Optional[str]:
        return self.sources.get("listenbrainz_username")

    def update_sources(
        self,
        lastfm_username: Optional[str],
        listenbrainz_username: Optional[str],
    ) -> None:
        """
        Update top-level source metadata (usernames) without touching ZIPs or listens.
        """
        self.sources["lastfm_username"] = lastfm_username or None
        self.sources["listenbrainz_username"] = listenbrainz_username or None
        self.save_cache()


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
        return _empty_listens_df()

    # Build DataFrame first
    df = pd.DataFrame.from_records(records)

    # Convert ISO strings back to datetime
    if "listened_at" in df.columns:
        df["listened_at"] = pd.to_datetime(df["listened_at"], utc=True)

    return df