"""
tests/test_resolver.py
Tests the Metadata Resolver logic in enrichment.py.
Verifies that DataFrames are correctly updated with new MBIDs and Album names.
"""

import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
import enrichment

@pytest.fixture
def messy_df():
    """A DataFrame with some missing MBIDs."""
    return pd.DataFrame([
        # Row 0: Fully valid (Should be ignored)
        {"artist": "Known", "track_name": "Song", "album": "Alb", "recording_mbid": "existing-id"},
        # Row 1: Missing MBID, Unknown Album (Should be resolved)
        {"artist": "Target", "track_name": "Hit", "album": "Unknown", "recording_mbid": None},
        # Row 2: Missing MBID, Has Album (Should be resolved, album preserved if not unknown)
        {"artist": "Target", "track_name": "Hit", "album": "Real Album", "recording_mbid": ""},
    ])

def test_resolve_missing_mbids_logic(messy_df):
    """
    Verify that resolve_missing_mbids correctly updates the DataFrame
    using the results from the API client.
    """
    
    # Mock the API Client response
    # We want to simulate finding a match for "Target - Hit"
    mock_details = {
        "mbid": "resolved-new-id",
        "album": "Resolved Album Name",
        "title": "Hit"
    }
    
    # We patch the module-level 'mb_client' in enrichment.py
    with patch("enrichment.mb_client") as mock_client, \
         patch("enrichment._load_json_dict", return_value={}), \
         patch("enrichment._save_json_dict"):
        
        # Configure mock to return success
        mock_client.search_recording_details.return_value = mock_details
        
        # Run Resolver
        df_out, count_res, count_fail = enrichment.resolve_missing_mbids(messy_df)
        
        # Assertions
        assert count_res == 2  # Row 1 and Row 2 should be resolved (same artist/track key)
        assert count_fail == 0
        
        # Row 0: Should be untouched
        assert df_out.iloc[0]["recording_mbid"] == "existing-id"
        assert df_out.iloc[0]["album"] == "Alb"
        
        # Row 1: Should be fully updated (MBID + Album) because album was "Unknown"
        assert df_out.iloc[1]["recording_mbid"] == "resolved-new-id"
        assert df_out.iloc[1]["album"] == "Resolved Album Name" 
        
        # Row 2: MBID updated, Album preserved (because it wasn't Unknown)
        # The Resolver prefers user data over API data if user data exists.
        assert df_out.iloc[2]["recording_mbid"] == "resolved-new-id"
        assert df_out.iloc[2]["album"] == "Real Album"
        
        
        
        
"""
tests/test_resolver.py
Tests the Metadata Resolver logic in enrichment.py.
"""

import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
import enrichment

@pytest.fixture
def messy_df():
    return pd.DataFrame([
        # Row 0: Valid
        {"artist": "Known", "track_name": "Song", "album": "Alb", "recording_mbid": "existing-id"},
        # Row 1: Needs Resolution
        {"artist": "Target", "track_name": "Hit", "album": "Unknown", "recording_mbid": None},
    ])

def test_resolve_missing_mbids_logic(messy_df):
    """
    Verify that resolve_missing_mbids correctly updates the DataFrame.
    """
    mock_details = {
        "mbid": "resolved-new-id",
        "album": "Resolved Album Name",
        "title": "Hit"
    }
    
    with patch("enrichment.mb_client") as mock_client, \
         patch("enrichment._load_json_dict", return_value={}), \
         patch("enrichment._save_json_dict"):
        
        mock_client.search_recording_details.return_value = mock_details
        
        df_out, count_res, count_fail = enrichment.resolve_missing_mbids(messy_df)
        
        # Assertions
        assert count_res == 1
        
        # Row 1 updated
        updated_row = df_out.iloc[1]
        assert updated_row["recording_mbid"] == "resolved-new-id"
        assert updated_row["album"] == "Resolved Album Name"        