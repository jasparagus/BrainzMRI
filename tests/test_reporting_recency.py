import pandas as pd
from datetime import datetime, timedelta, timezone
import reporting

def test_filter_by_recency():
    """
    Verify that filter_by_recency correctly identifies the LATEST listen.
    """
    now = datetime.now(timezone.utc)
    
    # Setup: 
    # Artist A: Listened 1 day ago (Recent)
    # Artist B: Listened 400 days ago (Old)
    # Artist C: Listened 400 days ago AND 1 day ago (Should be Recent!)
    
    data = [
        {"artist": "A", "listened_at": now - timedelta(days=1)},
        {"artist": "B", "listened_at": now - timedelta(days=400)},
        {"artist": "C", "listened_at": now - timedelta(days=400)}, # Old listen
        {"artist": "C", "listened_at": now - timedelta(days=1)},   # New listen
    ]
    df = pd.DataFrame(data)
    
    # Filter: Last listened between 0 and 30 days ago
    # Expected: A and C (because C's *latest* listen is recent). B excluded.
    result = reporting.filter_by_recency(df, ["artist"], start_days=0, end_days=30)
    
    unique_artists = sorted(result["artist"].unique())
    assert unique_artists == ["A", "C"]
    
    # Check that we get ALL rows for valid artists (including C's old listen)
    # filter_by_recency filters *entities*, but returns all rows for those entities.
    assert len(result) == 3 # A(1) + C(2)