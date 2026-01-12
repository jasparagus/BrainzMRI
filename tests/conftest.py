"""
tests/conftest.py
Pytest fixtures for BrainzMRI.
Creates synthetic ListenBrainz export data for testing.
"""

import pytest
import json
import os
import zipfile
import tempfile
from datetime import datetime, timezone

@pytest.fixture
def mock_listen_data():
    """
    Returns a list of raw listen dictionaries as they appear in the JSONL.
    Includes edge cases: missing MBIDs, multi-artist credits, etc.
    """
    return [
        # 1. Standard Track with full metadata
        {
            "listened_at": 1704067200,  # 2024-01-01 00:00:00 UTC
            "track_metadata": {
                "artist_name": "Daft Punk",
                "track_name": "One More Time",
                "release_name": "Discovery",
                "mbid_mapping": {
                    "artists": [
                        {"artist_mbid": "056e4f3e-d505-4dad-8ec1-d04f521cbb56", "artist_credit_name": "Daft Punk"}
                    ],
                    "recording_mbid": "b4c52086-6e46-43b8-9366-4c449a0a0346",
                    "release_mbid": "2d652875-430c-4e67-8730-1fb6809fb034"
                },
                "additional_info": {
                    "duration_ms": 320000
                }
            }
        },
        # 2. Minimal Track (No MBIDs, No Album)
        {
            "listened_at": 1704070800,
            "track_metadata": {
                "artist_name": "Unknown Artist",
                "track_name": "Mystery Track",
                "release_name": None,
                "mbid_mapping": {},
                "additional_info": {}
            }
        },
        # 3. Multi-Artist Track (Should result in 2 rows in normalized DF)
        {
            "listened_at": 1704074400,
            "track_metadata": {
                "artist_name": "Queen & David Bowie",
                "track_name": "Under Pressure",
                "mbid_mapping": {
                    "artists": [
                        {"artist_mbid": "0383dadf-2a4e-4d10-a46a-e9e041da8eb3", "artist_credit_name": "Queen"},
                        {"artist_mbid": "5441c29d-3602-4898-b1a1-b77fa23b8e50", "artist_credit_name": "David Bowie"}
                    ],
                    "recording_mbid": "f62660c7-e633-4b6f-bffb-d29b2b005ca7"
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
    # Create a temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "test_export.zip")
        
        with zipfile.ZipFile(zip_path, "w") as z:
            # 1. user.json
            user_info = {"user_name": "test_user", "musicbrainz_id": "test-mbid"}
            z.writestr("user.json", json.dumps(user_info))
            
            # 2. feedback.jsonl
            feedback_str = "\n".join(json.dumps(row) for row in mock_feedback_data)
            z.writestr("feedback.jsonl", feedback_str)
            
            # 3. listens/listens.jsonl
            listens_str = "\n".join(json.dumps(row) for row in mock_listen_data)
            z.writestr("listens/listens.jsonl", listens_str)
            
        yield zip_path