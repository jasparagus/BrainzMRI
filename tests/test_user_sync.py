"""
tests/test_user_sync.py
Tests for the Data Integrity: Auto-Refresh Likes feature.
"""

import os
import json
import pytest
from user import User

def test_sync_likes_updates_memory(temp_user):
    """Verify sync_likes updates the in-memory set."""
    # Initial state
    temp_user.liked_mbids = {"old-like-1", "old-like-2"}
    
    # New state from API (old-like-2 was unliked, new-like-3 added)
    new_likes_from_api = {"old-like-1", "new-like-3"}
    
    temp_user.sync_likes(new_likes_from_api)
    
    assert "old-like-2" not in temp_user.liked_mbids
    assert "new-like-3" in temp_user.liked_mbids
    assert len(temp_user.liked_mbids) == 2

def test_sync_likes_persists_to_disk(temp_user):
    """Verify sync_likes writes the new set to likes.json."""
    new_likes = {"persistent-like-A", "persistent-like-B"}
    
    # Perform Sync
    temp_user.sync_likes(new_likes)
    
    # Check File
    assert os.path.exists(temp_user.likes_file)
    with open(temp_user.likes_file, "r") as f:
        saved_data = json.load(f)
        
    assert set(saved_data) == new_likes

def test_sync_likes_thread_safety_placeholder(temp_user):
    """
    Sanity check that the lock attribute exists. 
    Actual concurrency testing is hard in unit tests, but we ensure the mechanism is there.
    """
    assert hasattr(temp_user, "lock")
    # Simulate a "locked" operation
    with temp_user.lock:
        temp_user.sync_likes({"locked-like"})
        
    with open(temp_user.likes_file, "r") as f:
        data = json.load(f)
    assert "locked-like" in data