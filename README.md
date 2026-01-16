# BrainzMRI: ListenBrainz Metadata Review Instrument

**BrainzMRI** is a desktop "Metadata Review Instrument" (MRI) for analyzing your **ListenBrainz** listening history. It provides a local, privacy-focused GUI application for generating rich reports, enriching data with external metadata, and pushing actions back to the server.

Unlike standard "Year in Review" summaries, BrainzMRI works with a local cache of your data, allowing for instant filtering, complex queries, offline analysis, and bulk management of your collection.

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
* **Stacked Area Chart:** Visualizes the "Favorite Artist Trend" report, showing how artist dominance shifts over periods .
* **Stacked Bar Chart:** Visualizes the "New Music by Year" report, highlighting your discovery rates over time.

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

* **[ ] Heatmaps:**
* *Goal:* Visualizations for listening density (Hour of Day vs Day of Week).


* **[ ] Streak Detection:**
* *Goal:* Identify "Binge Listening" sessions (consecutive days/hours of specific artists).


* **[ ] "Forgotten Favorites" Engine:**
* *Goal:* Intelligent recommendation report (`High Play Count` + `Last Listened > 1 Year Ago`).


* **[ ] Report Presets:**
* *Goal:* Dropdown menu to pre-fill complex filter configurations.


* **[ ] Advanced Filtering:**
* *Goal:* "Negative" filtering (e.g., "Artist DOES NOT match regex").



```

```