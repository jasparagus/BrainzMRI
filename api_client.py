"""
api_client.py
Network layer for BrainzMRI. Handles API requests to MusicBrainz and Last.fm.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional

# Constants
NETWORK_DELAY_SECONDS = 1.0
LASTFM_API_ROOT = "https://ws.audioscrobbler.com/2.0/"
MUSICBRAINZ_API_ROOT = "https://musicbrainz.org/ws/2/"

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