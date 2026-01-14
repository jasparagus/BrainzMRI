"""
tests/test_api_payloads.py
Verifies that API clients generate correct JSON payloads, 
specifically checking against regression of JSPF format bugs.
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from api_client import ListenBrainzClient

class MockResponse:
    def __init__(self, status_code, json_data):
        self.status = status_code
        self.json_data = json_data
        
    def read(self):
        return json.dumps(self.json_data).encode("utf-8")
    
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass

@pytest.fixture
def lb_client():
    return ListenBrainzClient(token="test_token", dry_run=False)

def test_playlist_jspf_structure(lb_client):
    """
    CRITICAL: Verify JSPF payload structure.
    - 'identifier' must be a String (not a list).
    - 'extension' must include public: False.
    - 'creator' should be absent.
    """
    
    tracks = [
        {"title": "Track A", "artist": "Artist A", "album": "Album A", "mbid": "mbid-123"},
        {"title": "Track B", "artist": "Artist B"} # No MBID
    ]
    
    # We patch urllib to capture the request being sent
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = MockResponse(200, {"status": "ok"})
        
        lb_client.create_playlist("Test Playlist", tracks)
        
        # Get the request object passed to urlopen
        args, _ = mock_urlopen.call_args
        request = args[0]
        
        # Extract JSON body
        payload = json.loads(request.data)
        
        playlist = payload["playlist"]
        
        # 1. Check Extension (Public Flag)
        assert "extension" in playlist
        ext_key = "https://musicbrainz.org/doc/jspf#playlist"
        assert ext_key in playlist["extension"]
        assert playlist["extension"][ext_key]["public"] is False
        
        # 2. Check Creator (Should be absent)
        assert "creator" not in playlist
        
        # 3. Check Tracks
        sent_tracks = playlist["track"]
        assert len(sent_tracks) == 2
        
        # Track 1 (Has MBID)
        t1 = sent_tracks[0]
        assert "identifier" in t1
        # REGRESSION CHECK: Must be str, not list
        assert isinstance(t1["identifier"], str) 
        assert t1["identifier"] == "https://musicbrainz.org/recording/mbid-123"
        
        # Track 2 (No MBID)
        t2 = sent_tracks[1]
        assert "identifier" not in t2

def test_feedback_payload(lb_client):
    """Verify feedback (Like) payload structure."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = MockResponse(200, {"status": "ok"})
        
        lb_client.submit_feedback("mbid-like", 1)
        
        args, _ = mock_urlopen.call_args
        payload = json.loads(args[0].data)
        
        assert payload["recording_mbid"] == "mbid-like"
        assert payload["score"] == 1
        assert isinstance(payload["score"], int)