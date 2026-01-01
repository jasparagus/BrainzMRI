"""
test_brainzmri.py
Automated test harness for BrainzMRI parser/reporting.

Runs:
- Top Artists (All Time)
- Top Albums (All Time)
- Top Tracks (All Time)
- Artists once popular but not listened recently
- Artists listened recently
- All Liked Artists
- Enriched Artist Report (Genres)

Outputs go to: ./test_reports/
"""

import os
import time
import ParseListens as core

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
ZIP_PATH = r"C:\Path\To\Your\ListenBrainzExport.zip"

# Output folder
TEST_DIR = "test_reports"
os.makedirs(TEST_DIR, exist_ok=True)

def save_test(df, name):
    """Save a test report into test_reports/ with a timestamp."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(TEST_DIR, f"{timestamp}_{name}.txt")
    df.to_string(open(path, "w", encoding="utf-8"))
    print(f"[OK] {name} → {path}")

# ------------------------------------------------------------
# MAIN TEST LOGIC
# ------------------------------------------------------------
def main():
    print("=== BrainzMRI Automated Test Runner ===")

    # Load data
    user_info, feedback, listens = core.parse_listenbrainz_zip(ZIP_PATH)
    df = core.normalize_listens(listens, ZIP_PATH)

    # --------------------------------------------------------
    # 1. Top Artists / Albums / Tracks (All Time)
    # --------------------------------------------------------
    for mode in ["artist", "album", "track"]:
        result, meta = core.report_top(
            df,
            group_col=mode,
            days=(0,0),        # All Time
            by="total_tracks",
            topn=50
        )
        save_test(result, f"Top_{mode.capitalize()}_AllTime")

    # --------------------------------------------------------
    # 2. Artists once popular but not listened recently
    #    (e.g., listened heavily 365–2000 days ago, but not in last 180 days)
    # --------------------------------------------------------
    old_window = core.filter_by_days(df, "listened_at", 365, 2000)
    result, meta = core.report_top(
        old_window,
        group_col="artist",
        days=(365,2000),
        by="total_tracks",
        topn=50
    )
    save_test(result, "Artists_OncePopular_NotRecent")

    # --------------------------------------------------------
    # 3. Artists listened recently (0–30 days)
    # --------------------------------------------------------
    recent = core.filter_by_days(df, "listened_at", 0, 30)
    result, meta = core.report_top(
        recent,
        group_col="artist",
        days=(0,30),
        by="total_tracks",
        topn=50
    )
    save_test(result, "Artists_Recent_0to30days")

    # --------------------------------------------------------
    # 4. All Liked Artists
    # --------------------------------------------------------
    liked, meta = core.report_artists_with_likes(df, feedback)
    save_test(liked, "All_Liked_Artists")

    # --------------------------------------------------------
    # 5. Enriched Artist Report (Genres)
    # --------------------------------------------------------
    threshold = core.report_artists_threshold(df, mins=30, tracks=15)
    csv_path, enriched = core.enrich_report_with_genres(threshold, ZIP_PATH)
    print(f"[OK] Enriched Artist Report → {csv_path}")

    print("\n=== All tests completed successfully ===")

if __name__ == "__main__":
    main()