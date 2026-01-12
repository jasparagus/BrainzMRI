"""
tests/test_reporting.py
Tests for the reporting.py module (Aggregation and Math).
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone
import parsing
import reporting

# Helper to create a DataFrame from the raw dict fixture
@pytest.fixture
def basic_df(mock_listen_data):
    return parsing.normalize_listens(mock_listen_data)

def test_filter_by_days(basic_df):
    """Verify time filtering logic."""
    # The fixture data has dates:
    # 2024-01-01 00:00 (Daft Punk)
    # 2024-01-01 01:00 (Unknown)
    # 2024-01-01 02:00 (Queen + Bowie)
    
    # We need to mock "now" because filter_by_days uses datetime.now(timezone.utc)
    # Instead of mocking the system clock (messy), we'll cheat by checking 
    # relative deltas or just ensuring the logic allows passing custom ranges.
    
    # Actually, filter_by_days is relative to "now". 
    # Since the fixture data is in 2024, and "now" is 2026, 
    # a small range like "0-30 days ago" should return Empty.
    
    empty_result = reporting.filter_by_days(basic_df, "listened_at", start_days=0, end_days=30)
    assert empty_result.empty, "Data from 2024 should not appear in the last 30 days"

    # A large range (0-10000 days) should include everything
    full_result = reporting.filter_by_days(basic_df, "listened_at", start_days=0, end_days=10000)
    assert len(full_result) == len(basic_df)

def test_report_top_artists(basic_df):
    """Verify Top N aggregation counts."""
    # Basic Top Artists report
    result, meta = reporting.report_top(basic_df, group_col="artist", by="total_listens")
    
    # We expect:
    # Daft Punk: 1
    # Unknown Artist: 1
    # Queen: 1
    # David Bowie: 1
    
    assert len(result) == 4
    assert meta["entity"] == "Artists"
    
    # Check specific count
    daft_punk = result[result["artist"] == "Daft Punk"].iloc[0]
    assert daft_punk["total_listens"] == 1
    # Check duration (320000ms = 320s = ~5.3 min = ~0.1 hours)
    assert daft_punk["total_hours_listened"] == 0.1

def test_report_top_tracks_grouping(basic_df):
    """Verify By Track grouping uses (Artist + Track Name)."""
    # Create a duplicate row to test aggregation
    # Normalize returns a new DF, so we can concat safely
    df_doubled = pd.concat([basic_df, basic_df])
    
    result, meta = reporting.report_top(df_doubled, group_col="track", by="total_listens")
    
    # We expect 4 unique tracks (since Queen/Bowie split is same track name, different artists)
    # Wait, "Under Pressure" is the track. 
    # Row 1: Artist=Queen, Track=Under Pressure
    # Row 2: Artist=Bowie, Track=Under Pressure
    # These are distinct rows in the 'By Track' report because we group by [artist, track_name]
    
    assert len(result) == 4
    
    # Counts should be 2 for each because we doubled the dataframe
    row = result[(result["artist"] == "Daft Punk") & (result["track_name"] == "One More Time")].iloc[0]
    assert row["total_listens"] == 2

def test_genre_flavor_logic(basic_df):
    """
    Verify weighted genre calculations.
    We must artificially inject the 'Genres' column since enrichment isn't running.
    """
    df = basic_df.copy()
    
    # Setup scenario:
    # Daft Punk (1 listen) -> "Electronic|House"
    # Queen (1 listen)     -> "Rock"
    # Bowie (1 listen)     -> "Rock|Glam"
    # Unknown (1 listen)   -> "" (No genre)
    
    # Map genres to the dataframe
    genre_map = {
        "Daft Punk": "Electronic|House",
        "Queen": "Rock",
        "David Bowie": "Rock|Glam",
        "Unknown Artist": ""
    }
    df["Genres"] = df["artist"].map(genre_map)
    
    # We first need to aggregate by artist (as the engine does) before feeding to report_genre_flavor
    # But report_genre_flavor handles the explosion logic on whatever DF it gets 
    # provided it has 'total_listens'. 
    # Let's manually create the input state expected by report_genre_flavor
    
    input_df = pd.DataFrame([
        {"artist": "Daft Punk", "total_listens": 10, "Genres": "Electronic|House"},
        {"artist": "Queen", "total_listens": 5, "Genres": "Rock"},
        {"artist": "Bowie", "total_listens": 5, "Genres": "Rock|Glam"},
        {"artist": "Unknown", "total_listens": 100, "Genres": ""} # Should be ignored
    ])
    
    result, meta = reporting.report_genre_flavor(input_df)
    
    # Expected Math:
    # Electronic: 10
    # House: 10
    # Rock: 5 (Queen) + 5 (Bowie) = 10
    # Glam: 5
    
    assert len(result) == 4
    
    # Check Rock
    rock = result[result["Genre"] == "Rock"].iloc[0]
    assert rock["Listens"] == 10
    
    # Check Electronic
    electro = result[result["Genre"] == "Electronic"].iloc[0]
    assert electro["Listens"] == 10
    
    # Check Glam
    glam = result[result["Genre"] == "Glam"].iloc[0]
    assert glam["Listens"] == 5