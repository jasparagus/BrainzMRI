"""
tests/test_parsing.py
Tests for the parsing.py module (ETL logic).
"""

import pytest
import pandas as pd
import os
import tempfile
import parsing

# ... (Existing tests: test_parse_listenbrainz_zip, test_normalize_listens, test_load_feedback) ...
# ... (Keep them as is) ...

def test_parse_listenbrainz_zip(sample_zip_path):
    """Verify we can unzip and extract raw data correctly."""
    user_info, feedback, listens = parsing.parse_listenbrainz_zip(sample_zip_path)
    
    assert user_info["user_name"] == "test_user"
    assert len(feedback) == 3
    assert len(listens) == 3

def test_normalize_listens(mock_listen_data):
    """Verify raw JSON is converted to the canonical DataFrame schema."""
    df = parsing.normalize_listens(mock_listen_data)
    assert len(df) == 4
    expected_cols = [
        "artist", "artist_mbid", "album", "track_name", 
        "duration_ms", "listened_at", "recording_mbid"
    ]
    for col in expected_cols:
        assert col in df.columns

def test_load_feedback(mock_feedback_data):
    """Verify we only extract 'liked' tracks (score=1)."""
    likes = parsing.load_feedback(mock_feedback_data)
    assert len(likes) == 1
    assert "b4c52086-6e46-43b8-9366-4c449a0a0346" in likes

# --- New Tests for CSV Import ---

def test_parse_generic_csv_success():
    """Verify robust CSV mapping with 'messy' but valid headers."""
    # Mimic the user's provided 'Mix - Goat-EST.csv' headers
    csv_content = """Track name,Artist name,Album,Playlist name,Type,ISRC
"Polyphia - G.O.A.T.",Polyphia,New Levels New Devils,Mix 1,Playlist,
"Rush - YYZ",Rush,Moving Pictures,Mix 1,Playlist,
"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as tmp:
        tmp.write(csv_content)
        tmp_path = tmp.name
        
    try:
        df = parsing.parse_generic_csv(tmp_path)
        
        # Check Columns
        assert "artist" in df.columns
        assert "track_name" in df.columns
        assert "album" in df.columns
        
        # Check Mapping
        row = df.iloc[0]
        assert row["artist"] == "Polyphia"
        assert row["track_name"] == "Polyphia - G.O.A.T."
        assert row["album"] == "New Levels New Devils"
        assert row["origin"] == ["csv_import"]
        
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def test_parse_generic_csv_failure():
    """Verify rejection of CSV with ambiguous 'Album Artist' but no 'Artist'."""
    # This header has 'Album Artist' but NO 'Artist' column
    csv_content = """Track Title,Album Artist,Album,Length
"Song A",The Band,Greatest Hits,3:00
"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as tmp:
        tmp.write(csv_content)
        tmp_path = tmp.name
        
    try:
        # Should raise ValueError because we strictly exclude "Album Artist" 
        # from being the main artist column
        with pytest.raises(ValueError, match="Could not determine 'Artist' column"):
            parsing.parse_generic_csv(tmp_path)
            
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)