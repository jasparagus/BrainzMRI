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
    return os.path.join(config.get_user_cache_dir(username), "lastfm_loves.json")


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


def fetch_and_cache_listenbrainz_likes(
    user,
    client=None,
    progress_callback=None,
    is_cancelled=None
) -> set[str]:
    """
    Fetch all liked recording MBIDs (score=1) from ListenBrainz with full pagination
    and atomically update the user's likes.json cache.
    If cancelled or if an API error occurs mid-pagination, existing cached likes are preserved.
    """
    import parsing
    from api_client import ListenBrainzClient

    lb_user = user.get_listenbrainz_username()
    if not lb_user:
        return user.get_liked_mbids()

    if client is None:
        client = ListenBrainzClient(user.listenbrainz_token)

    offset = 0
    count = 500
    all_likes_data = []

    while True:
        if is_cancelled and is_cancelled():
            logging.info("ListenBrainz Likes Sync: Aborted due to cancellation.")
            return user.get_liked_mbids()

        resp = client.get_user_likes(lb_user, offset=offset, count=count)
        if resp is None or not isinstance(resp, dict):
            raise RuntimeError(f"ListenBrainz Likes API returned invalid response at offset {offset}: {resp}")

        likes_page = resp.get("feedback", [])
        if not likes_page and "likes" in resp:
            likes_page = resp["likes"]
        elif not likes_page and "payload" in resp:
            likes_page = (resp.get("payload") or {}).get("likes", [])

        if not likes_page:
            break

        all_likes_data.extend(likes_page)
        offset += len(likes_page)

        if progress_callback:
            progress_callback(len(all_likes_data))

        total_count = resp.get("total_count")
        if total_count is None and "payload" in resp:
            total_count = (resp.get("payload") or {}).get("total_count")

        if total_count is not None and len(all_likes_data) >= total_count:
            break
        if len(likes_page) < count:
            break

        client.wait_for_rate_limit()

    if is_cancelled and is_cancelled():
        logging.info("ListenBrainz Likes Sync: Aborted due to cancellation.")
        return user.get_liked_mbids()

    new_mbids = parsing.load_feedback(all_likes_data)
    user.sync_likes(new_mbids)
    logging.info(f"ListenBrainz Likes Sync Complete. Saved {len(new_mbids)} items.")
    return new_mbids
