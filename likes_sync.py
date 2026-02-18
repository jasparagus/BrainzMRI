"""
likes_sync.py
Lightweight Last.fm loves fetch/cache and cross-platform like utilities.
"""

import json
import os
import logging

from config import config


def get_lastfm_loves_path(username: str) -> str:
    """Return the path to the user's cached Last.fm loves file."""
    return os.path.join(config.cache_dir, username, "lastfm_loves.json")


def fetch_and_cache_lastfm_loves(user) -> list[dict]:
    """
    Fetch loved tracks from Last.fm and cache to lastfm_loves.json.
    Returns list of dicts: {'artist': str, 'track': str, 'mbid': str|None}
    """
    from api_client import LastFMClient
    lfm_client = LastFMClient()

    lfm_user = user.lastfm_username
    if not lfm_user:
        raise ValueError("No Last.fm username configured.")
    if not lfm_client.api_key:
        raise ValueError("Last.fm API Key is missing.\nPlease add 'lastfm_api_key' to your config.json.")

    loves = lfm_client.get_user_loved_tracks(lfm_user)

    # Cache to disk
    path = get_lastfm_loves_path(user.username)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(loves, f, indent=2)

    logging.info(f"Cached {len(loves)} Last.fm loves for {user.username}")
    return loves


def load_cached_lastfm_loves(username: str) -> list[dict]:
    """
    Load previously cached Last.fm loves from disk.
    Returns empty list if no cache exists.
    """
    path = get_lastfm_loves_path(username)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"Failed to load Last.fm loves cache: {e}")
        return []