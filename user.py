"""
user.py
User entity and caching for BrainzMRI.
"""

import gzip
import json
import os
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
    """

    username: str  # App username
    listens_df: pd.DataFrame = field(repr=False)
    liked_mbids: Set[str] = field(repr=False)
    cache_dir: str
    sources: dict = field(default_factory=dict)
    
    # Auth tokens (New in v3.1)
    listenbrainz_token: Optional[str] = None

    # -------------------------
    # Construction helpers
    # -------------------------

    @classmethod
    def from_sources(
        cls,
        username: str,
        lastfm_username: Optional[str] = None,
        listenbrainz_username: Optional[str] = None,
        listenbrainz_token: Optional[str] = None,
        listenbrainz_zips: Optional[List[Dict[str, Any]]] = None,
        cache_root: Optional[str] = None,
    ) -> "User":
        """
        Create a new User from source metadata only.
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
            listenbrainz_token=listenbrainz_token,
        )

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
        """
        if cache_root is None:
            cache_root = get_cache_root()

        cache_dir = get_user_cache_dir(username)

        listens_path = os.path.join(cache_dir, "listens.jsonl.gz")
        likes_path = os.path.join(cache_dir, "likes.json")
        sources_path = os.path.join(cache_dir, "sources.json")
        auth_path = os.path.join(cache_dir, "auth.json") # New separate file for tokens

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
            
        # Load Auth (handle missing file for backward compat)
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
            listenbrainz_token=listenbrainz_token,
        )

    # -------------------------
    # Cache I/O
    # -------------------------

    def save_cache(self) -> None:
        """
        Write listens, likes, sources, and auth to the user cache directory.
        """
        listens_path = os.path.join(self.cache_dir, "listens.jsonl.gz")
        likes_path = os.path.join(self.cache_dir, "likes.json")
        sources_path = os.path.join(self.cache_dir, "sources.json")
        auth_path = os.path.join(self.cache_dir, "auth.json")

        _save_listens_jsonl_gz(self.listens_df, listens_path)

        with open(likes_path, "w", encoding="utf-8") as f:
            json.dump(sorted(self.liked_mbids), f, indent=2)

        with open(sources_path, "w", encoding="utf-8") as f:
            json.dump(self.sources, f, indent=2)
            
        # Save tokens securely-ish (in a separate file)
        auth_data = {"listenbrainz_token": self.listenbrainz_token}
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, indent=2)

    # -------------------------
    # Ingestion from sources
    # -------------------------

    def ingest_listenbrainz_zip(self, zip_path: str) -> None:
        """
        Ingest a ListenBrainz ZIP into this user's canonical listens and likes.
        """
        user_info, feedback, listens = parsing.parse_listenbrainz_zip(zip_path)

        df_new = parsing.normalize_listens(listens, origin=["listenbrainz_zip"])
        likes_new = parsing.load_feedback(feedback)

        if self.listens_df is None or self.listens_df.empty:
            combined = df_new.copy()
        else:
            combined = pd.concat([self.listens_df, df_new], ignore_index=True)

        # Dedupe
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
        self.liked_mbids.update(likes_new)

        zips_list = self.sources.get("listenbrainz_zips") or []
        zips_list.append(
            {
                "path": os.path.abspath(zip_path),
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.sources["listenbrainz_zips"] = zips_list

        self.save_cache()

    # -------------------------
    # Convenience accessors
    # -------------------------

    def get_listens(self) -> pd.DataFrame:
        return self.listens_df

    def get_liked_mbids(self) -> Set[str]:
        return self.liked_mbids

    def get_lastfm_username(self) -> Optional[str]:
        return self.sources.get("lastfm_username")

    def get_listenbrainz_username(self) -> Optional[str]:
        return self.sources.get("listenbrainz_username")

    def update_sources(
        self,
        lastfm_username: Optional[str],
        listenbrainz_username: Optional[str],
        listenbrainz_token: Optional[str],
    ) -> None:
        """
        Update source metadata and auth tokens.
        """
        self.sources["lastfm_username"] = lastfm_username or None
        self.sources["listenbrainz_username"] = listenbrainz_username or None
        self.listenbrainz_token = listenbrainz_token or None
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
    if "listened_at" in df.columns:
        df["listened_at"] = pd.to_datetime(df["listened_at"], utc=True)

    return df