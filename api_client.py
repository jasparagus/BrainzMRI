"""
api_client.py
Network layer for BrainzMRI. Handles API requests to MusicBrainz, Last.fm, and ListenBrainz.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional, Union

# Constants
NETWORK_DELAY_SECONDS = 1.0
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
        """Execute a GET request against MusicBrainz."""
        query = urllib.parse.urlencode(params)
        url = f"{MUSICBRAINZ_API_ROOT}{path}?{query}"
        
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent},
        )
        
        # Blocking call with simple rate limiting
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.load(resp)
            time.sleep(NETWORK_DELAY_SECONDS)
            return result
        except Exception:
            return {}

    def _extract_tags(self, data: Dict[str, Any]) -> List[str]:
        """Extract flat tag list from MB response."""
        tags = []
        # Combine user tags and genres
        for key in ["tags", "genres"]:
            items = data.get(key, [])
            for item in items:
                name = item.get("name")
                if name:
                    tags.append(name)
        return tags

    def get_entity_tags(self, entity_type: str, mbid: str) -> List[str]:
        """
        Fetch tags for a specific entity by MBID.
        entity_type: 'recording', 'release', 'artist'
        """
        if not mbid:
            return []
        
        data = self._request(
            f"{entity_type}/{mbid}", 
            {"fmt": "json", "inc": "tags+genres"}
        )
        return self._extract_tags(data)

    def search_entity_tags(self, entity_type: str, query: str, result_list_key: str) -> List[str]:
        """
        Search for an entity and return tags from the top result.
        """
        data = self._request(
            entity_type, 
            {"query": query, "fmt": "json", "limit": "1"}
        )
        
        results = data.get(result_list_key, [])
        if results:
            return self._extract_tags(results[0])
        return []


class LastFMClient:
    """
    Client for the Last.fm API.
    Requires an API key (defaults to env var BRAINZMRI_LASTFM_API_KEY).
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("BRAINZMRI_LASTFM_API_KEY", "")

    def _request(self, params: Dict[str, str]) -> Dict[str, Any]:
        """Execute a GET request against Last.fm."""
        if not self.api_key:
            return {}
            
        params = params.copy()
        params["api_key"] = self.api_key
        params["format"] = "json"
        
        query = urllib.parse.urlencode(params)
        url = f"{LASTFM_API_ROOT}?{query}"
        req = urllib.request.Request(url)
        
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.load(resp)
            time.sleep(NETWORK_DELAY_SECONDS)
            return result
        except Exception:
            return {}

    def _extract_tags(self, data: Dict[str, Any], root_key: str) -> List[str]:
        """Extract tags from Last.fm response structure."""
        toplevel = data.get(root_key) or {}
        tags_block = toplevel.get("toptags") or toplevel.get("tags") or {}
        tags_list = tags_block.get("tag") or []
        
        if isinstance(tags_list, dict): 
            tags_list = [tags_list]
            
        return [t.get("name") for t in tags_list if t.get("name")]

    def get_tags(self, method: str, root_key: str, **kwargs) -> List[str]:
        """
        Generic helper for Last.fm tag fetching.
        method: e.g., 'track.getInfo'
        root_key: e.g., 'track' (the top level key in the response)
        kwargs: arguments for the API call (artist=..., track=...)
        """
        params = {"method": method, **kwargs}
        data = self._request(params)
        return self._extract_tags(data, root_key)


class ListenBrainzClient:
    """
    Client for the ListenBrainz API.
    Handles authenticated WRITE operations (Feedback, Playlists).
    
    Includes a 'dry_run' mode for safety testing.
    """

    def __init__(self, token: Optional[str] = None, dry_run: bool = False):
        self.token = token
        self.dry_run = dry_run
        self.user_agent = "BrainzMRI/1.0 (https://github.com/jasparagus/BrainzMRI)"

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a POST request to ListenBrainz.
        """
        if not self.token:
            raise ValueError("ListenBrainz User Token is required for write operations.")

        url = f"{LISTENBRAINZ_API_ROOT}{endpoint}"
        json_data = json.dumps(payload).encode("utf-8")
        
        if self.dry_run:
            print(f"[DRY RUN] POST {url}")
            print(f"[DRY RUN] Payload: {json.dumps(payload, indent=2)}")
            return {"status": "ok", "dry_run": True}

        req = urllib.request.Request(
            url,
            data=json_data,
            headers={
                "Authorization": f"Token {self.token}",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    return json.load(resp)
                raise RuntimeError(f"API returned status {resp.status}")
        except urllib.error.HTTPError as e:
            # Try to read error message from body
            try:
                err_body = e.read().decode("utf-8")
                raise RuntimeError(f"ListenBrainz API Error {e.code}: {err_body}")
            except Exception:
                raise RuntimeError(f"ListenBrainz API Error {e.code}")
        except Exception as e:
            raise RuntimeError(f"Network Error: {e}")

    def submit_feedback(self, recording_mbid: str, score: int) -> Dict[str, Any]:
        """
        Submit feedback for a track.
        score: 1 (Like), 0 (Neutral), -1 (Dislike)
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
        
        tracks: List of dicts containing:
            - 'title': Track Name (Required)
            - 'artist': Artist Name (Required)
            - 'album': Album Name (Optional)
            - 'mbid': Recording MBID (Optional but Recommended)
        """
        playlist_tracks = []
        
        for t in tracks:
            track_obj = {
                "title": t.get("title", "Unknown Title"),
                "creator": t.get("artist", "Unknown Artist"),
            }
            
            if t.get("album"):
                track_obj["album"] = t.get("album")
                
            # Add MusicBrainz extension if MBID exists
            if t.get("mbid"):
                track_obj["extension"] = {
                    "https://musicbrainz.org/doc/jspf#track": {
                        "recording_identifier": f"https://musicbrainz.org/recording/{t['mbid']}"
                    }
                }
            
            playlist_tracks.append(track_obj)

        jspf = {
            "playlist": {
                "title": name,
                "annotation": description,
                "creator": "BrainzMRI",
                "track": playlist_tracks
            }
        }
        
        return self._post("playlist/create", jspf)