# BrainzMRI: ListenBrainz Metadata Review Instrument

**BrainzMRI** is a desktop "Metadata Review Instrument" (MRI) for analyzing your **ListenBrainz** listening history. It provides a local, privacy-focused GUI application for generating rich reports, enriching data with external metadata, and pushing actions back to the server.

Unlike standard "Year in Review" summaries, BrainzMRI works with a local cache of your data, allowing for instant filtering, complex queries, offline analysis, and bulk management of your collection.


## Gallery

| Main Interface | Artist Trends | New Music Discovery |
| :---: | :---: | :---: |
| <img src="example_main_ui.png" width="250" /> | <img src="example_artist_trend.png" width="250" /> | <img src="example_music_discovery.png" width="250" /> |

---

## Key Features

### Advanced Analysis & Reporting
* **Top N Reports:** Aggregate by **Artist**, **Album**, or **Track**.
    * **Filters:** Time Range (e.g., "Last 365 Days"), Recency (e.g., "Last Listened > 1 year ago"), and Activity Thresholds.
    * **Visual Indicators:** Tracks liked on ListenBrainz are marked with a ❤️.
* **Genre Flavor:** A weighted analysis of your listening habits. Unlike simple tag counts, this report weights genres by the *volume of listens*, giving a more accurate picture of your actual musical "diet."
* **Favorite Artist Trends:** A time-series analysis that bins your history (Daily/Weekly/Monthly) to show the rise and fall of your top artists over time.
* **New Music by Year:** A discovery analysis comparing "New Discoveries" (artists heard for the first time that year) vs. "Catalog" (re-listening to known artists).
* **Raw Listens:** A forensic view of your individual listen events, useful for verifying imports and data integrity.

### Rich Visualizations
* **Genre Treemap:** A rectangular visualization of genre dominance .
* **Stacked Area Chart:** Visualizes the "Favorite Artist Trend" report, showing how artist dominance shifts over periods. Now includes a subplot showing Relative Dominance (normalized percentage) alongside absolute listen counts.
* **Stacked Bar Chart:** Visualizes the "New Music by Year" report, highlighting your discovery rates over time. Now includes a subplot comparing the ratio of New vs. Recurring tracks.

### Metadata Enrichment & Deep Query
* **Smart Enrichment:** Automatically fetches metadata from MusicBrainz and Last.fm.
* **Deep Query Mode:** An optional "Slow" mode that fetches detailed metadata for Albums and Tracks, not just Artists.
* **Resolver Engine:** Can scan generic CSV imports (which lack IDs) and query MusicBrainz to resolve missing **Recording MBIDs**, upgrading "dumb" text lists into fully linkable, "Like"-able data.
* **"Æ" Sorting:** Custom sorting logic that handles special characters (e.g., normalizing "Æ" to "AE") so that artists sort intuitively rather than at the bottom of the list.

### Upstream Actions (Read/Write)
* **Batch Likes:** Highlight rows and mark them as "Loved" on ListenBrainz in bulk.
* **Playlist Creation:** Export any generated report or filtered view directly to a ListenBrainz JSPF playlist.
* **Safety First:** Includes a **"Dry Run"** mode (on by default) to simulate API requests without modifying your account.

### Robust Data Ingestion
* **Transactional Updates:** The "Get New Listens" feature uses a "Backwards Crawl" strategy with intermediate staging. This ensures that even if an update is aborted or crashes, your data remains consistent. It safely bridges the gap between your local history and the server without data corruption.
* **Resume Capability:** Interrupted downloads automatically save their progress to an "Island" cache and resume exactly where they left off.
* **CSV Import:** Load arbitrary CSV playlists (e.g., from Spotify exports) to analyze them using BrainzMRI's matching engine.

[UI EXAMPLES HERE]

---

## Attribution

This project was developed with assistance from **Microsoft Copilot** and **Google Gemini** as a fun test/experiment with "Vibe Coding".

---

# Installation

BrainzMRI requires **Python 3.10+** and a few common libraries.

### 1. Clone the repository
```bash
git clone https://github.com/jasparagus/BrainzMRI.git "your/file/path/here/BrainzMRI"
cd BrainzMRI

```

### 2. Install dependencies

```bash
pip install -r requirements.txt

```

---

# Running BrainzMRI

## Windows

Double-click: `BrainzMRI.bat`

## macOS / Linux

Run:

```bash
python3 gui_main.py

```

---

# Usage Guide

1. **Setup User:**
* Click "New User" (or "Edit User") to enter your ListenBrainz Username and User Token (found on your ListenBrainz settings page).
* If you have a previous ListenBrainz JSON export, you can ingest the ZIP file here to instantly populate your history.


2. **Fetch Data:**
* **Incremental Update:** Click **"Get New Listens"** to fetch recent tracks from the server. This process is safe to interrupt; it will resume from where it left off next time.
* **Import CSV:** Alternatively, click "Import CSV" to load an external playlist for analysis.


3. **Generate Report:**
* Select a **Report Type** (e.g., "Genre Flavor", "By Artist").
* **Time Filters:** Enter "0, 365" to analyze the last year.
* **Enrichment:** Select "Query MusicBrainz" to fetch genres. Check "Deep Query" if you need album-level precision (slower).
* Click **"Generate Report"**.


4. **Visualize:**
* For supported reports (Artist Trend, Genre Flavor, New Music), click **"Show Graph"** to open a Matplotlib visualization window.


5. **Refine & Act:**
* **Filter:** Use the Regex filter bar to drill down (e.g., `Rock|Metal` to find matches for either).
* **Resolve:** If data is missing IDs (common with CSV imports), click **"Resolve Metadata"** to query MusicBrainz.
* **Action:** Highlight tracks and click **"Like Selected Tracks"** or **"Export as Playlist"** to push changes back to ListenBrainz.



---

# Project Structure

```text
BrainzMRI/
│
├── BrainzMRI.bat                 # Windows launcher
├── gui_main.py                   # Main Orchestrator: Threading, Updates, & Workflow
├── gui_charts.py                 # Matplotlib Logic: Treemaps, Stacked Area/Bar Charts
├── gui_tableview.py              # Table Logic: Rendering, Regex Filter, & "Æ" Sorting
├── gui_user_editor.py            # User Profile Management & ZIP Ingestion
├── api_client.py                 # Network Layer: Retries, Rate Limiting (MB/Last.fm/LB)
├── report_engine.py              # Report Routing & Status Management
├── reporting.py                  # Core Logic: Aggregation, Statistics, & Pandas operations
├── enrichment.py                 # Metadata Logic: Caching, Fetching, & MBID Resolution
├── user.py                       # Persistence: Data I/O, Deduplication, & Intermediate Cache
├── parsing.py                    # Utilities: Key Generation, Normalization, & File Parsing
│
├── tests/                        # Unit tests
├── README.md
├── requirements.txt
└── config.json                   # Auto-created settings

```

---

# Master Roadmap


## Playlist Prep: Album Expansion Engine

* **Goal:** Enable the creation of "Full Album" playlists from album-level reports (e.g., turning a "Top Albums of 2024" report into a playable track list).
* **Workflow:**
1. User generates a **"By Album"** report (applying standard filters like time range, play count, etc.).
2. A new button, **"Show All Tracks for Listed Albums"**, appears in the UI.
3. **Expansion Logic:**
* **Fetch:** The system iterates through the `release_mbid`s in the current report and queries the MusicBrainz API to retrieve the full official tracklist for each release.
* **Merge Stats:** It creates a new "Expanded Report" DataFrame containing every track from these albums. It then left-joins the user's local statistics (e.g., `total_listens`, `last_listened`, `Liked` status) onto these tracks.
* **Enrich:** Genre metadata is applied to each track (sourced from Cache or API based on the current "Genre Lookup" setting).
4. **Render:** The UI table refreshes to display this new "Expanded Track List."

* **Benefit:** This transforms abstract album statistics into actionable track lists, allowing users to immediately utilize the existing "Export to Playlist" or "Batch Like" features on full albums.


## Cross-Platform Like Synchronization

* **Goal:** Enable bidirectional synchronization of "Loved Tracks" between Last.fm and ListenBrainz, ensuring your favorites are consistent across both platforms and the local BrainzMRI cache.
* **Workflow:**

1. User opens the "Sync Manager" dialog and selects a **Sync Mode**:
* **"Full Sync (Additive)"**: Merges likes from both services. Any track liked on *either* service will be pushed to the other, resulting in identical libraries.
* **"Last.fm to ListenBrainz"**: Scans Last.fm likes and pushes any missing tracks to ListenBrainz. (One-way).
* **"ListenBrainz to Last.fm"**: Scans ListenBrainz likes and pushes any missing tracks to Last.fm. (One-way).


2. **Fetch & Diff:** The system queries both APIs to build a "State of the World" comparison, identifying exactly which MBIDs are missing from which service.
3. **Execution:** BrainzMRI performs the batch API write operations to apply the necessary "Love" actions to the target service(s).
4. **Local Update:** The local cache is immediately updated to reflect the new superset of liked tracks.

* **Benefit:** Eliminates platform fragmentation, ensuring that a song you hearted on Last.fm years ago is properly recognized and recommended on your modern ListenBrainz profile.


## Heatmaps
* *Goal:* Visualizations for listening density (Hour of Day vs Day of Week).


## Streak Detection
* *Goal:* Identify "Binge Listening" sessions (consecutive days/hours of specific artists).


## Report Presets
* *Goal:* Dropdown menu to pre-fill complex filter configurations.
 * Example: "Forgotten Favorites" (`High Play Count` + `Last Listened > 1 Year Ago`).
 * Example: "All Time Greatest Albums" (`High Play Count` + `High Play Count` + `4+ Likes Per Album`).


## Advanced Filtering
* *Goal:* "Negative" filtering (e.g., "Artist DOES NOT match regex").



## Refactor Opportunities

### High-Value: Separation of Sync Logic (`gui_main.py`)

**Status:** The `action_get_new_listens` method in `gui_main.py` is becoming a "God Method." It contains:

1. UI state management (buttons, progress windows).
2. Threading logic (Daemon threads).
3. Synchronization logic (Barrier pattern, shared state dicts).
4. Business logic (API calls, data parsing).
**Refactoring Opportunity:**

* **Extract `SyncManager`:** Move the `barrier_state`, `likes_worker`, and `listens_worker` logic into a dedicated class (e.g., `sync_manager.py`). The GUI should simply instantiate this manager, pass it a set of callbacks for UI updates (`on_progress`, `on_finish`), and let it run. This makes the synchronization logic testable without spinning up a Tkinter window.

### Maintenance: Enrichment Loop Repetition (`enrichment.py`)

**Status:** `enrich_report` contains three large blocks of code (Tracks, Albums, Artists) that are 90% identical. They all:

1. Check for cancellation.
2. Construct a name info dict.
3. Call `_enrich_single_entity`.
4. Update the map.
5. Handle batch saving.
**Refactoring Opportunity:**

* Abstract the loop into a generic `_process_entities` helper function that accepts the entity type and the list of unique rows. This would reduce `enrichment.py` by approx. 100 lines and ensure bug fixes (like the recent "Deep Query" logic change) are applied consistently to all entity types.

### Inconsistency: "Like" Extraction Logic

**Status:**

* `parsing.py` has a `load_feedback` function that iterates a list and extracts `recording_mbid`.
* `gui_main.py`'s `likes_worker` manually iterates the API response and extracts `recording_mbid` inline.
**Refactoring Opportunity:**
* Update `gui_main.py` to import and use `parsing.load_feedback` (or a slightly generalized version of it) inside the worker. This ensures that the definition of a "valid like" (e.g., checking `score == 1`) is consistent between ZIP imports and API fetches.

### Cleanliness: Modern Type Hinting

**Status:** The codebase mixes `from typing import List, Dict, Set` (old style) with standard types (implied by Python 3.10+ usage elsewhere).
**Refactoring Opportunity:** Standardize on built-in types (`list`, `dict`, `set`, `tuple`) in type hints to clean up imports and modernize the code style.
