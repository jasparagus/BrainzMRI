"""
tests/conftest.py
Pytest fixtures for BrainzMRI.
Creates synthetic ListenBrainz export data and temporary User environments.
"""

import pytest
import json
import os
import zipfile
import tempfile
import shutil
from datetime import datetime, timezone, timedelta

# Import the User class (assuming user.py is in the python path)
# If running from root, this works.
from user import User

@pytest.fixture
def mock_listen_data():
    """
    Returns a list of raw listen dictionaries as they appear in the JSONL.
    Includes edge cases: missing MBIDs, multi-artist credits, etc.
    """
    now = datetime.now(timezone.utc)
    return [
        # 1. Standard Track with full metadata (Recent)
        {
            "listened_at": int(now.timestamp()),
            "track_metadata": {
                "artist_name": "Daft Punk",
                "track_name": "One More Time",
                "release_name": "Discovery",
                "mbid_mapping": {
                    "recording_mbid": "b4c52086-6e46-43b8-9366-4c449a0a0346",
                    "release_mbid": "2d652875-4306-44c2-9856-4d29623719c8"
                }
            }
        },
        # 2. Track with Missing MBIDs (Older)
        {
            "listened_at": int((now - timedelta(days=2)).timestamp()),
            "track_metadata": {
                "artist_name": "Unknown Artist",
                "track_name": "Mystery Track",
                "release_name": "Mystery Album"
            }
        },
        # 3. Track with complex characters (for Sort Key testing)
        {
            "listened_at": int((now - timedelta(days=5)).timestamp()),
            "track_metadata": {
                "artist_name": "Æther Realm",
                "track_name": "The Sun, The Moon, The Star",
                "release_name": "Tarot",
                "mbid_mapping": {
                    "recording_mbid": "complex-char-mbid"
                }
            }
        }
    ]

@pytest.fixture
def mock_feedback_data():
    """Returns raw feedback (likes) data."""
    return [
        {"recording_mbid": "b4c52086-6e46-43b8-9366-4c449a0a0346", "score": 1},  # Like
        {"recording_mbid": "bad-track-mbid", "score": -1},                       # Dislike
        {"recording_mbid": "neutral-track", "score": 0},                         # Neutral
    ]

@pytest.fixture
def sample_zip_path(mock_listen_data, mock_feedback_data):
    """
    Creates a temporary physical ZIP file mimicking a real LB export.
    Returns the path to the ZIP file.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "test_export.zip")
        
        with zipfile.ZipFile(zip_path, "w") as z:
            # 1. user.json
            user_info = {"user_name": "test_user", "musicbrainz_id": "test-mbid"}
            z.writestr("user.json", json.dumps(user_info))
            
            # 2. feedback.jsonl
            feedback_str = "\n".join([json.dumps(x) for x in mock_feedback_data])
            z.writestr("feedback.jsonl", feedback_str)
            
            # 3. listens/listens.jsonl
            listens_str = "\n".join([json.dumps(x) for x in mock_listen_data])
            z.writestr("listens/listens.jsonl", listens_str)
            
        yield zip_path

@pytest.fixture
def temp_user():
    """
    Creates a User instance with a dedicated temporary cache directory.
    Useful for testing sync_likes and persistence.
    """
    with tempfile.TemporaryDirectory() as tmp_cache:
        # We need to patch the get_cache_root logic or just manually set paths,
        # but since User relies on global helpers, we might simulate 'from_sources'
        # or manually instantiate.
        
        # For testing, we create a user and force their cache_dir to our temp location
        u = User("test_user", "token_123")
        u.cache_dir = os.path.join(tmp_cache, "users", "test_user")
        os.makedirs(u.cache_dir, exist_ok=True)
        
        # Initialize empty state
        u.likes_file = os.path.join(u.cache_dir, "likes.json")
        u.listens_file = os.path.join(u.cache_dir, "listens.jsonl.gz")
        u.liked_mbids = set()
        
        yield u