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
        full_url = url
        if params:
            full_url += "?" + urllib.parse.urlencode(params)
        logging.info(f"API Request: {method} {full_url}")
        
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

            except requests.exceptions.HTTPError as e:
                # Handle Server Errors (5xx) with Retry
                status = e.response.status_code
                if status in [500, 502, 503, 504]:
                    logging.warning(f"API Server Error ({status}): {e}. Retrying in 5s...")
                    time.sleep(5)
                    attempts += 1
                else:
                    # Client Errors (400, 401, 403, etc) -> Fail Immediately
                    logging.error(f"API Client Error: {e}")
                    raise e

            except (requests.exceptions.ConnectionError, ConnectionResetError) as e:
                logging.warning(f"Connection error: {e}. Retrying in 5s...")
                time.sleep(5)
                attempts += 1
            except Exception as e:
                logging.error(f"API Request Failed: {e}")
                raise e
        
        logging.error(f"Max retries exhausted for {url}")
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

    def _clean_title(self, text):
        """Remove common noise from track titles for fallback search."""
        import re
        if not text: return ""
        # Remove (Extension) types
        t = re.sub(r"\s*[\(\[]\s*(fit\.|feat\.|ft\.|with|featuring).+?[\)\]]", "", text, flags=re.IGNORECASE)
        t = re.sub(r"\s*[\(\[]\s*(remix|instrumental|live|demo|edit|remaster|remastered).+?[\)\]]", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*-\s*(remix|instrumental|live|demo|edit|remaster|remastered).*", "", t, flags=re.IGNORECASE)
        return t.strip()

    def search_recording_details(self, artist, track, album=None):
        """
        Search for a recording MBID.
        Returns dict {'mbid': ..., 'album': ...} or None.
        """
        # FIX: Strict NaN Guard
        if not artist or str(artist).lower() == "nan": return None
        if not track or str(track).lower() == "nan": return None
        
        # Scorer function
        from difflib import SequenceMatcher
        def similar(a, b): return SequenceMatcher(None, a.lower(), b.lower()).ratio()

        def perform_search(q_artist, q_track, q_album):
            query = f'artist:"{q_artist}" AND recording:"{q_track}"'
            if q_album and str(q_album).lower() not in ["", "nan", "none", "unknown"]:
                query += f' AND release:"{q_album}"'
            
            data = self._request("GET", "recording", params={"query": query, "fmt": "json", "limit": 5})
            time.sleep(self.delay)
            if not data: return []
            return data.get("recordings", [])

        # 1. Strict Search
        recs = perform_search(artist, track, album)
        
        # 2. Fallback: Cleaned Search (if no results or low confidence could be checked, but simpler to just try if empty)
        if not recs:
            clean_track = self._clean_title(track)
            if clean_track != track:
                logging.info(f"Retrying search with cleaned title: '{clean_track}'")
                recs = perform_search(artist, clean_track, album)

        if not recs: return None

        best_match = None
        best_score = -1

        for r in recs:
            score = 0
            
            # Check Artist (Highest Priority)
            credits = r.get("artist-credit", [])
            artist_name = credits[0].get("name", "") if credits else ""
            if isinstance(artist_name, dict): artist_name = artist_name.get("name", "") 
            
            art_score = similar(artist, artist_name)
            if art_score < 0.4: continue # Loose filter
            score += art_score * 10
            
            # Check Album
            r_album = ""
            if "releases" in r and r["releases"]:
                r_album = r["releases"][0].get("title", "")
            
            if album and str(album).lower() not in ["", "nan", "none", "unknown"]:
                if r_album:
                    alb_score = similar(album, r_album)
                    score += alb_score * 5
            
            # Check Title
            r_title = r.get("title", "")
            title_score = similar(track, r_title)
            score += title_score * 3

            # Penalize "Live" / "Remix" / "Karaoke"
            r_title_lower = r_title.lower()
            track_lower = track.lower()
            
            # If query didn't ask for Live, penalize
            if "live" in r_title_lower and "live" not in track_lower: score -= 3
            if "remix" in r_title_lower and "remix" not in track_lower: score -= 3
            if "instrumental" in r_title_lower and "instrumental" not in track_lower: score -= 3
            if "karaoke" in r_title_lower: score -= 5
            
            # Boost "Official" status if available in release info (hard to check in search results easily, ignoring for now)
            
            if score > best_score:
                best_score = score
                best_match = r

        if not best_match: 
            return None # Don't just return first trash result

        res = {"mbid": best_match["id"]}
        if "releases" in best_match and best_match["releases"]:
            res["album"] = best_match["releases"][0].get("title", "")
            
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
        Create a JSPF playlist on ListenBrainz.
        tracks: list of dicts {'title', 'artist', 'album', 'mbid'}
        """
        if self.dry_run:
            logging.info(f"[DRY RUN] Create Playlist '{name}' with {len(tracks)} tracks.")
            return

        if not self.token: raise ValueError("No Token.")

        jspf = {
            "playlist": {
                "title": name,
                "extension": {
                    "https://musicbrainz.org/doc/jspf#playlist": {
                        "public": True
                    }
                },
                "track": []
            }
        }
        
        for t in tracks:
            entry = {
                "title": t.get("title"),
                "creator": t.get("artist"),
                "album": t.get("album"),
                "identifier": [f"https://musicbrainz.org/recording/{t.get('mbid')}"]
            }
            jspf["playlist"]["track"].append(entry)
            
        headers = {"Authorization": f"Token {self.token}"}
        self._request("POST", "playlist/create", json_data=jspf, headers=headers)


# ===========================================================================
# Cover Art Archive Client
# ===========================================================================

class CoverArtClient:
    """Fetch album cover thumbnails from the Cover Art Archive."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})
        self.delay = config.network_delay  # Respect global wait time

    def download_cover(self, release_mbid: str, dest_path: str, size: int = 250) -> bool:
        """Download front cover to dest_path. Returns True on success."""
        url = f"https://coverartarchive.org/release/{release_mbid}/front-{size}"
        try:
            time.sleep(self.delay)
            resp = self.session.get(url, allow_redirects=True, timeout=15)
            if resp.status_code == 200:
                with open(dest_path, "wb") as f:
                    f.write(resp.content)
                return True
            logging.debug(f"Cover art not found for {release_mbid}: HTTP {resp.status_code}")
            return False
        except Exception as e:
            logging.debug(f"Cover art download failed for {release_mbid}: {e}")
            return False