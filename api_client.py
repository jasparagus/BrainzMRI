"""
api_client.py
Network layer for BrainzMRI. Handles API requests to MusicBrainz, Last.fm, and ListenBrainz.
"""

import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
import http.client
from typing import Dict, Any, List, Optional

# Constants
NETWORK_DELAY_SECONDS = 1.0
MAX_RETRIES = 5  # Increased for stability
LASTFM_API_ROOT = "https://ws.audioscrobbler.com/2.0/"
MUSICBRAINZ_API_ROOT = "https://musicbrainz.org/ws/2/"
LISTENBRAINZ_API_ROOT = "https://api.listenbrainz.org/1/"

class MusicBrainzClient:
    """
    Client for the MusicBrainz API (v2).
    Handles rate limiting and User-Agent headers.
    """
    
    def __init__(self):
        self.user_agent = "BrainzMRI/1.0 (https://github.com/jasparagus/BrainzMRI)"

    def _request(self, path: str, params: Dict[str, str]) -> Dict[str, Any]:
        """Execute a GET request against MusicBrainz with retries."""
        query = urllib.parse.urlencode(params)
        url = f"{MUSICBRAINZ_API_ROOT}{path}?{query}"
        
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent},
        )
        
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.load(resp)
                time.sleep(NETWORK_DELAY_SECONDS)
                return result
            except (urllib.error.URLError, http.client.IncompleteRead) as e:
                last_error = e
                err_str = str(e)
                
                # STABILITY FIX: Handle Connection Reset (WinError 10054) specifically
                if "10054" in err_str or "Connection reset" in err_str:
                    print(f"MB Connection Reset. Cooling down 5s... (Attempt {attempt+1}/{MAX_RETRIES})")
                    time.sleep(5.0)
                    continue
                
                # Standard exponential backoff: 1s, 2s, 4s...
                time.sleep(1 * (2 ** attempt))
            except Exception as e:
                # Non-network errors (parsing, etc) fail immediately
                print(f"Non-retriable error in MB lookup: {e}")
                return {}
        
        print(f"MB Lookup failed after {MAX_RETRIES} attempts: {last_error}")
        return {}

    def _extract_tags(self, data: Dict[str, Any]) -> List[str]:
        """Extract flat tag list from MB response."""
        tags = []
        for key in ["tags", "genres"]:
            items = data.get(key, [])
            for item in items:
                name = item.get("name")
                if name:
                    tags.append(name)
        return tags

    def get_entity_tags(self, entity_type: str, mbid: str) -> List[str]:
        if not mbid: return []
        data = self._request(f"{entity_type}/{mbid}", {"fmt": "json", "inc": "tags+genres"})
        return self._extract_tags(data)

    def search_entity_tags(self, entity_type: str, query: str, result_list_key: str) -> List[str]:
        data = self._request(entity_type, {"query": query, "fmt": "json", "limit": "1"})
        results = data.get(result_list_key, [])
        if results:
            return self._extract_tags(results[0])
        return []

    def search_recording_details(self, artist: str, track: str, release: str = None, threshold: int = 85) -> Optional[Dict[str, str]]:
        """
        Search for a recording and return its MBID and Metadata (Album, etc).
        Returns {'mbid': '...', 'album': '...', 'title': '...'} or None.
        """
        if not artist or not track:
            return None

        # Lucene Query
        query_parts = [f'artist:"{artist}"', f'recording:"{track}"']
        
        if release and release.lower() != "unknown":
            query_parts.append(f'release:"{release}"')
            
        q = " AND ".join(query_parts)
        
        data = self._request("recording", {"query": q, "fmt": "json", "limit": "3"})
        results = data.get("recordings", [])
        
        if not results:
            return None
            
        best = results[0]
        try:
            score = int(best.get("score", "0"))
        except ValueError:
            score = 0
            
        if score >= threshold:
            # Extract basic details
            info = {
                "mbid": best.get("id"),
                "title": best.get("title", track), # Use MB title if available
                "album": "Unknown"
            }
            
            # Try to find an album (release) name
            releases = best.get("releases", [])
            if releases:
                # Prioritize a release that matches our query if possible, otherwise first
                # For now, just taking the first one is standard behavior
                info["album"] = releases[0].get("title", "Unknown")
            
            return info
            
        return None


class LastFMClient:
    """
    Client for the Last.fm API.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("BRAINZMRI_LASTFM_API_KEY", "")

    def _request(self, params: Dict[str, str]) -> Dict[str, Any]:
        if not self.api_key: return {}
        params = params.copy()
        params["api_key"] = self.api_key
        params["format"] = "json"
        
        query = urllib.parse.urlencode(params)
        url = f"{LASTFM_API_ROOT}?{query}"
        req = urllib.request.Request(url)
        
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.load(resp)
                time.sleep(NETWORK_DELAY_SECONDS)
                return result
            except (urllib.error.URLError, http.client.IncompleteRead) as e:
                last_error = e
                time.sleep(1 * (2 ** attempt))
            except Exception:
                return {}
        
        return {}

    def _extract_tags(self, data: Dict[str, Any], root_key: str) -> List[str]:
        toplevel = data.get(root_key) or {}
        tags_block = toplevel.get("toptags") or toplevel.get("tags") or {}
        tags_list = tags_block.get("tag") or []
        if isinstance(tags_list, dict): tags_list = [tags_list]
        return [t.get("name") for t in tags_list if t.get("name")]

    def get_tags(self, method: str, root_key: str, **kwargs) -> List[str]:
        params = {"method": method, **kwargs}
        data = self._request(params)
        return self._extract_tags(data, root_key)


class ListenBrainzClient:
    """
    Client for the ListenBrainz API.
    Handles authenticated WRITE operations (Feedback, Playlists) and READ operations (User Listens).
    """

    def __init__(self, token: Optional[str] = None, dry_run: bool = False):
        self.token = token
        self.dry_run = dry_run
        self.user_agent = "BrainzMRI/1.0 (https://github.com/jasparagus/BrainzMRI)"

    def _request_generic(self, endpoint: str, method: str, params: Dict[str, Any] = None, data: bytes = None) -> Dict[str, Any]:
        """
        Core request handler for ListenBrainz.
        """
        url = f"{LISTENBRAINZ_API_ROOT}{endpoint}"
        
        headers = {
            "User-Agent": self.user_agent,
        }
        
        # Add Auth if available (required for writes, optional for reads but good practice)
        if self.token:
            headers["Authorization"] = f"Token {self.token}"

        if method == "POST":
            headers["Content-Type"] = "application/json"
            
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"

        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method
        )

        last_error = None
        for attempt in range(MAX_RETRIES):
            print(req)  # debugging
            print(url)  # debugging
            print(data)  # debugging
            print(headers)  # debugging
            print(method)  # debugging
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if 200 <= resp.status < 300:
                        return json.load(resp)
                    raise RuntimeError(f"API returned status {resp.status}")
            
            except urllib.error.HTTPError as e:
                # 429 Too Many Requests
                if e.code == 429:
                    print(f"Rate Limited (429). Sleeping 5s...")
                    time.sleep(5.0)
                    continue

                if e.code in [500, 502, 503, 504]:
                    last_error = e
                    time.sleep(1 * (2 ** attempt))
                    continue
                
                # Fatal errors (400 Bad Request, 401 Auth) should fail immediately
                try:
                    err_body = e.read().decode("utf-8")
                    print(f"[API ERROR BODY]: {err_body}")
                    raise RuntimeError(f"ListenBrainz API Error {e.code}: {err_body}")
                except Exception:
                    raise RuntimeError(f"ListenBrainz API Error {e.code}")

            except (urllib.error.URLError, http.client.IncompleteRead) as e:
                # Connection reset, DNS failure, etc.
                last_error = e
                if "10054" in str(e) or "Connection reset" in str(e):
                     time.sleep(5.0)
                else:
                     time.sleep(1 * (2 ** attempt))
                continue
            
            except Exception as e:
                raise RuntimeError(f"Network Error: {e}")

        # If we exit loop, we failed
        raise RuntimeError(f"Network Error after {MAX_RETRIES} attempts: {last_error}")

    def _get(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._request_generic(endpoint, "GET", params=params)

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.dry_run:
            print(f"--- [DRY RUN] POST REQUEST ---")
            print(f"URL: {endpoint}")
            print(f"PAYLOAD:\n{json.dumps(payload, indent=2)}")
            return {"status": "ok", "dry_run": True}
            
        data = json.dumps(payload).encode("utf-8")
        return self._request_generic(endpoint, "POST", data=data)

    # --- Write Methods ---

    def submit_feedback(self, recording_mbid: str, score: int) -> Dict[str, Any]:
        """
        Submit feedback for a track.
        """
        if score not in (-1, 0, 1):
            raise ValueError("Score must be -1, 0, or 1.")
        
        if not recording_mbid:
            raise ValueError("Cannot submit feedback: Missing Recording MBID.")

        payload = {
            "recording_mbid": recording_mbid,
            "score": score
        }
        return self._post("feedback/recording-feedback", payload)

    def create_playlist(self, name: str, tracks: List[Dict[str, str]], description: str = "") -> Dict[str, Any]:
        """
        Create a new playlist on ListenBrainz using JSPF format.
        """
        playlist_tracks = []
        
        for t in tracks:
            # Basic info
            track_obj = {
                "title": t.get("title", "Unknown Title"),
                "creator": t.get("artist", "Unknown Artist"),
            }
            if t.get("album"):
                track_obj["album"] = t.get("album")
                
            # Identifier must be a single string URI
            if t.get("mbid"):
                track_obj["identifier"] = f"https://musicbrainz.org/recording/{t['mbid']}"
            
            playlist_tracks.append(track_obj)

        # The extension block with 'public' is mandatory
        jspf = {
            "playlist": {
                "title": name,
                "annotation": description,
                "extension": {
                    "https://musicbrainz.org/doc/jspf#playlist": {
                        "public": False
                    }
                },
                "track": playlist_tracks
            }
        }
        
        return self._post("playlist/create", jspf)

    # --- Read Methods ---
    def get_user_listens(self, username: str, max_ts: int = None, count: int = 100) -> Dict[str, Any]:
        """
        Fetch listens for a user.
        :param max_ts: UNIX timestamp. If provided, returns listens BEFORE this time.
        :param count: Number of listens to retrieve (max 100).
        """
        params = {
            "count": count
        }
        if max_ts:
            params["max_ts"] = max_ts
        
        # Added urllib.parse.quote(username)
        return self._get(f"user/{urllib.parse.quote(username)}/listens", params)
        
        
    def get_user_likes(self, username: str, offset: int = 0, count: int = 100) -> Dict[str, Any]:
        """
        Fetch a page of user likes (feedback with score 1).
        """
        params = {
            "score": 1,
            "count": count,
            "offset": offset
        }
        # Use urllib.parse.quote() to handle special characters in username safely
        return self._get(f"feedback/user/{urllib.parse.quote(username)}/get-feedback", params)        