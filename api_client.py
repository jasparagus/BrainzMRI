"""
api_client.py
Centralized HTTP client for MusicBrainz, ListenBrainz, and Last.fm.
Handles rate limiting, retries, and error logging.
"""

import time
import requests
import urllib.parse
import logging
from config import config

class BaseClient:
    """Base class for API clients with common retry logic."""
    def __init__(self, base_url, rate_limit_delay=1.1):
        self.base_url = base_url
        self.delay = rate_limit_delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})

    def _request(self, method, endpoint, params=None, json_data=None, headers=None):
        url = f"{self.base_url}{endpoint}"
        
        # [RESTORED] Log the request for debugging
        logging.info(f"API Request: {method} {url}")
        
        attempts = 0
        while attempts < config.max_retries:
            try:
                resp = self.session.request(method, url, params=params, json=json_data, headers=headers)
                
                # Handle 429 Rate Limit
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5))
                    logging.warning(f"Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    attempts += 1
                    continue
                
                if resp.status_code == 404:
                    return None # Not found is not an exception
                
                resp.raise_for_status()
                return resp.json()

            except (requests.exceptions.ConnectionError, ConnectionResetError) as e:
                logging.warning(f"Connection error: {e}. Retrying in 5s...")
                time.sleep(5)
                attempts += 1
            except Exception as e:
                logging.error(f"API Request Failed: {e}")
                raise e
        
        logging.error(f"Max retries exceeded for {url}")
        return None


class MusicBrainzClient(BaseClient):
    def __init__(self):
        super().__init__(config.musicbrainz_api_root, rate_limit_delay=1.1)

    def get_entity_tags(self, entity_type, mbid):
        """Fetch tags for an artist or recording."""
        endpoint = f"{entity_type}/{mbid}"
        data = self._request("GET", endpoint, params={"inc": "tags", "fmt": "json"})
        if not data: return []
        
        tags = [t["name"] for t in data.get("tags", [])]
        time.sleep(self.delay)
        return tags

    def get_release_group_tags(self, release_mbid):
        """Hop from Release -> Release Group to get tags."""
        # 1. Get Release to find Group ID
        rel_data = self._request("GET", f"release/{release_mbid}", params={"inc": "release-groups", "fmt": "json"})
        if not rel_data: return []
        
        rg_list = rel_data.get("release-groups", [])
        if not rg_list: return []
        
        rg_id = rg_list[0]["id"]
        
        # 2. Get Tags for Group
        rg_data = self._request("GET", f"release-group/{rg_id}", params={"inc": "tags", "fmt": "json"})
        time.sleep(self.delay)
        if not rg_data: return []
        
        return [t["name"] for t in rg_data.get("tags", [])]

    def search_entity_tags(self, entity_type, query, result_key):
        """Search by name/query."""
        encoded_query = urllib.parse.quote(query)
        # Note: requests handles basic encoding, but complex lucene queries benefit from explicit care
        data = self._request("GET", entity_type, params={"query": query, "fmt": "json"})
        
        if not data: return []
        results = data.get(result_key, [])
        if not results: return []
        
        # Return tags of first match
        return [t["name"] for t in results[0].get("tags", [])]

    def search_recording_details(self, artist, track, album=None):
        """
        Search for a recording MBID.
        Returns dict {'mbid': ..., 'album': ...} or None.
        """
        # FIX: Strict NaN Guard
        if not artist or str(artist).lower() == "nan": return None
        if not track or str(track).lower() == "nan": return None
        
        query = f'artist:"{artist}" AND recording:"{track}"'
        
        # Only add album if it's a valid string
        if album and str(album).lower() not in ["", "nan", "none", "unknown"]:
            query += f' AND release:"{album}"'
            
        data = self._request("GET", "recording", params={"query": query, "fmt": "json", "limit": 1})
        time.sleep(self.delay)
        
        if not data: return None
        recs = data.get("recordings", [])
        if not recs: return None
        
        match = recs[0]
        res = {"mbid": match["id"]}
        
        # Try to extract an album title if present
        if "releases" in match and match["releases"]:
            res["album"] = match["releases"][0].get("title", "")
            
        return res


class LastFMClient(BaseClient):
    def __init__(self):
        super().__init__(config.lastfm_api_root, rate_limit_delay=0.5)
        self.api_key = config.lastfm_api_key

    def get_tags(self, method, key, **kwargs):
        if not self.api_key: return []
        
        params = {
            "method": method,
            "api_key": self.api_key,
            "format": "json"
        }
        params.update(kwargs)
        
        data = self._request("GET", "", params=params)
        if not data: return []
        
        # Handle nested response logic
        root = data.get("toptags", {})
        tags = root.get("tag", [])
        
        # Last.fm returns single dict if only 1 tag, list otherwise
        if isinstance(tags, dict): tags = [tags]
        
        return [t["name"] for t in tags]

    def get_user_loved_tracks(self, username: str, limit: int = None) -> list[dict]:
        """
        Fetch all loved tracks for a user.
        Returns list of dicts: {'artist': str, 'track': str, 'mbid': str|None}
        """
        if not self.api_key: return []

        method = "user.getLovedTracks"
        params = {
            "method": method,
            "user": username, 
            "api_key": self.api_key,
            "format": "json",
            "limit": 100
        }
        
        all_loves = []
        page = 1
        
        while True:
            params["page"] = page
            data = self._request("GET", "", params=params)
            
            if not data or "lovedtracks" not in data:
                break
                
            tracks = data["lovedtracks"].get("track", [])
            if not tracks:
                break
                
            if isinstance(tracks, dict): 
                tracks = [tracks]
                
            for t in tracks:
                artist = t.get("artist", {})
                if isinstance(artist, dict): artist = artist.get("name", "")
                elif isinstance(artist, str): artist = artist # Last.fm quirkiness
                
                all_loves.append({
                    "artist": artist,
                    "track": t.get("name", ""),
                    "mbid": t.get("mbid", "")
                })
            
            # Pagination
            attr = data["lovedtracks"].get("@attr", {})
            total_pages = int(attr.get("totalPages", 1))
            
            if limit and len(all_loves) >= limit:
                return all_loves[:limit]
            
            if page >= total_pages:
                break
                
            page += 1
            time.sleep(self.delay)
            
        return all_loves


class ListenBrainzClient(BaseClient):
    def __init__(self, token=None, dry_run=False):
        super().__init__(config.listenbrainz_api_root, rate_limit_delay=1.1)
        self.token = token
        self.dry_run = dry_run

    def get_user_listens(self, username, min_ts=None, max_ts=None, count=100):
        params = {"count": count}
        if min_ts: params["min_ts"] = min_ts
        if max_ts: params["max_ts"] = max_ts
        
        endpoint = f"user/{username}/listens"
        return self._request("GET", endpoint, params=params)

    def get_user_likes(self, username, offset=0, count=100):
        """Fetch likes (feedback) using get-feedback endpoint."""
        endpoint = f"feedback/user/{username}/get-feedback"
        params = {"score": 1, "offset": offset, "count": count}
        return self._request("GET", endpoint, params=params)

    def submit_feedback(self, recording_mbid, score):
        if self.dry_run:
            logging.info(f"[DRY RUN] Feedback: {recording_mbid} -> {score}")
            return
            
        if not self.token:
            raise ValueError("No User Token provided.")
            
        headers = {"Authorization": f"Token {self.token}"}
        payload = {"recording_mbid": recording_mbid, "score": score}
        
        self._request("POST", "feedback/recording-feedback", json_data=payload, headers=headers)

    def create_playlist(self, name, tracks):
        """
        Create a JSPF playlist.
        tracks: list of dicts {'title', 'artist', 'release', 'recording_mbid'}
        """
        if self.dry_run:
            logging.info(f"[DRY RUN] Create Playlist '{name}' with {len(tracks)} tracks.")
            return

        if not self.token: raise ValueError("No Token.")

        jspf = {
            "playlist": {
                "title": name,
                "track": []
            }
        }
        
        for t in tracks:
            entry = {
                "title": t.get("title"),
                "creator": t.get("artist"),
                "album": t.get("album"),
                "identifier": f"https://musicbrainz.org/recording/{t.get('mbid')}"
            }
            jspf["playlist"]["track"].append(entry)
            
        headers = {"Authorization": f"Token {self.token}"}
        self._request("POST", "playlist/create", json_data=jspf, headers=headers)