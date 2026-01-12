"""
tests/test_parsing.py
Tests for the parsing.py module (ETL logic).
"""

import pytest
import pandas as pd
import parsing

def test_parse_listenbrainz_zip(sample_zip_path):
    """Verify we can unzip and extract raw data correctly."""
    user_info, feedback, listens = parsing.parse_listenbrainz_zip(sample_zip_path)
    
    assert user_info["user_name"] == "test_user"
    assert len(feedback) == 3
    assert len(listens) == 3

def test_normalize_listens(mock_listen_data):
    """Verify raw JSON is converted to the canonical DataFrame schema."""
    df = parsing.normalize_listens(mock_listen_data)
    
    # Check 1: Row count
    # We had 3 input listens, but one was a collaboration (Queen & Bowie).
    # The normalizer splits multi-artist credits into separate rows.
    # Expected: 1 (Daft Punk) + 1 (Mystery) + 2 (Queen + Bowie) = 4 rows
    assert len(df) == 4
    
    # Check 2: Columns exist
    expected_cols = [
        "artist", "artist_mbid", "album", "track_name", 
        "duration_ms", "listened_at", "recording_mbid"
    ]
    for col in expected_cols:
        assert col in df.columns

    # Check 3: Data Integrity (Daft Punk)
    dp_row = df[df["track_name"] == "One More Time"].iloc[0]
    assert dp_row["artist"] == "Daft Punk"
    assert dp_row["album"] == "Discovery"
    assert dp_row["duration_ms"] == 320000
    assert dp_row["recording_mbid"] == "b4c52086-6e46-43b8-9366-4c449a0a0346"
    
    # Check 4: Data Integrity (Unknown)
    uk_row = df[df["track_name"] == "Mystery Track"].iloc[0]
    assert uk_row["artist"] == "Unknown Artist"
    assert uk_row["album"] == "Unknown"
    assert pd.isna(uk_row["recording_mbid"]) or uk_row["recording_mbid"] is None

def test_load_feedback(mock_feedback_data):
    """Verify we only extract 'liked' tracks (score=1)."""
    likes = parsing.load_feedback(mock_feedback_data)
    
    assert len(likes) == 1
    assert "b4c52086-6e46-43b8-9366-4c449a0a0346" in likes
    assert "bad-track-mbid" not in likes