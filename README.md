# BrainzMRI: ListenBrainz Metadata Review Instrument

A ListenBrainz "Metadata Review Instrument" (MRI) for analyzing listens from the ListenBrainz service.

BrainzMRI is a desktop tool for analyzing your **ListenBrainz** listening history. It provides a **GUI application** for generating rich reports about your listening habits, extending far beyond standard "Year in Review" summaries.

## Key Features

* **Local-First & Private:** Analyzes your local JSON/ZIP exports. No data is sent to the cloud (except for specific, anonymized metadata lookups).
* **Deep Enrichment:** Fetches genre and tag data from **MusicBrainz** and **Last.fm**, using robust name-based fallback strategies when MBIDs are missing.
* **Powerful Filtering:** Filter by Time Range, Recency (last listened), and regex patterns on Artists/Tracks.
* **Advanced Reporting:**
    * **Top N:** Artists, Albums, and Tracks.
    * **Genre Flavor:** Weighted analysis of your most-listened genres.
    * **Favorite Artist Trends:** Time-series analysis of your top artists over specific periods.
    * **New Music by Year:** Breakdown of discovery rates vs. recurring favorites.
* **Visualizations:** Interactive **Stacked Area Charts** (Trends) and **Stacked Bar Charts** (New Music) powered by Matplotlib.
* **Observability:** Detailed status bar feedback on enrichment pipeline performance (Cached | Fetched | Empty).
* **Exportable Data:** Save any generated report or filtered view to CSV.

---

## Attribution
This project was developed with assistance from **Microsoft Copilot** and **Google Gemini** as a fun test/experiment with "Vibe Coding".

---

# Installation

BrainzMRI requires **Python 3.10+** and a few common libraries.

### 1. Clone the repository
```bash
git clone [https://github.com/jasparagus/BrainzMRI.git](https://github.com/jasparagus/BrainzMRI.git) "Your/Chosen/Destination/Path"
cd BrainzMRI

```

### 2. Install dependencies

From inside the project directory:

```bash
pip install -r requirements.txt

```

*(Note: `matplotlib`, `pandas`, and `numpy` are required).*

### 3. (Optional) API Keys

Set your Last.fm API Key as an environment variable for better genre data:

```bash
export BRAINZMRI_LASTFM_API_KEY="your_key_here"

```

---

# Running BrainzMRI

## Windows

Double-click:
`BrainzMRI.bat`

## macOS / Linux

Run:

```bash
python3 gui_main.py

```

---

# Using the GUI

### 1. Select your ListenBrainz ZIP

Click **“New User”** or select an existing user to begin. If creating a new user, you can ingest a ListenBrainz export ZIP. The app parses listens, feedback, and metadata.

### 2. Configure filters

You can set:

* **Time Range (days ago):** Restrict listens to a specific window.
* **Last Listened (days ago):** Filter entities based on recency (e.g., "Show artists I haven't heard in 365 days").
* **Top N:** Limit the number of results.
* **Thresholds:** Filter out low-activity entities by Min. Listens, Min. Time Listened, or Min. Likes.

### 3. Configure enrichment (Optional)

* **Perform Genre Lookup:** Enriches the report with genre tags.
* **Source:** Choose between **Cache Only** (Fast), **Query MusicBrainz**, or **Query Last.fm**.
* **Force Cache Update:** Forces a re-fetch of metadata from the API.

### 4. Choose a report type

* **By Artist / Album / Track:** Standard Top-N tables.
* **Genre Flavor:** Aggregated list of genres weighted by your listen counts.
* **Favorite Artist Trend:** Generates a tabular view of artist rankings over time bins.
* **New Music by Year:** Comparison of new discoveries vs. catalog listens per year.
* **Raw Listens:** A view of the raw dataset after filters are applied.

### 5. View Results & Charts

* **Table View:** Results appear in a sortable, filterable table.
* **Show Graph:** For supported reports ("Favorite Artist Trend" and "New Music By Year"), click this button to render an interactive visualization.

### 6. Save reports

Click **“Save Report”** to export CSVs to `.../cache/users/username/reports`.

---

# Project Structure

```text
BrainzMRI/
│
├── BrainzMRI.bat                 # Windows launcher
├── gui_main.py                   # Main GUI orchestrator & Threading
├── gui_charts.py                 # Matplotlib visualization logic
├── gui_tableview.py              # Table rendering & Regex filtering
├── gui_user_editor.py            # User creation dialog
├── report_engine.py              # Report routing & Pipeline logic
├── reporting.py                  # Math, Aggregation, & Data Prep
├── enrichment.py                 # Metadata fetching (MB/Last.fm) & Caching
├── user.py                       # Data Model & File I/O
├── parsing.py                    # JSON normalization
│
├── tests/                        # Unit tests & Fixtures
│   ├── conftest.py
│   └── test_parsing.py
│
├── README.md
├── requirements.txt
├── config.json                   # Auto-created settings
└── cache/                        # Data storage

```

---

# **Major Modules & Classes**

## `gui_main.py`: Main Application Orchestrator

Handles window lifecycle, user selection, input parsing, and threading.

* **Threading:** Offloads `ReportEngine` execution to background threads to keep the UI responsive.
* **ProgressWindow:** Displays real-time progress for long-running enrichment tasks.
* **Graph Integration:** Manages the "Show Graph" button state and launches `gui_charts`.

## `gui_charts.py`: Visualization Engine

Responsible for rendering Matplotlib figures using the native UI backend.

* `show_artist_trend_chart()`: Displays a Stacked Area Chart for artist dominance over time.
* `show_new_music_stacked_bar()`: Displays 3 subplots (Artist/Album/Track) comparing New vs. Recurring listening.

## `report_engine.py`: Controller

The bridge between the GUI and Data layers.

* **Routing:** Dispatches requests to specific `reporting.py` functions.
* **Enrichment Coordination:** Manages the flow of data through `enrichment.py`.
* **Status Generation:** Formats detailed pipeline stats (e.g., `100 Processed (50 Cached | 40 Fetched | 10 Empty)`).

## `reporting.py`: Aggregation & Logic

Contains all Pandas transformations and math.

* `report_genre_flavor()`: Weighted genre calculation.
* `report_artist_trend()`: Time-binning and ranking logic.
* `prepare_artist_trend_chart_data()`: Special pivot logic for "Top N Overall" visualization.
* `filter_by_recency()`: Reusable logic for "Last Listened" filtering.

## `enrichment.py`: Metadata Layer

Handles external API interaction and local caching.

* **Unified Providers:** Generic wrappers for MusicBrainz and Last.fm lookups.
* **Internal Force Update:** Handles cache invalidation logic internally to ensure consistency.
* **Pipeline Stats:** Tracks distinct states (Newly Fetched vs. Empty vs. Cached).

## `user.py`: Data Model

Manages the `User` entity, ZIP ingestion, and gzipped JSONL storage.

---

# Master Roadmap / To-Do List

### Phase 0: Stability & Testing (Current Priority)

* [ ] **0.1. Test Infrastructure:** Set up `pytest` suite and create fixture data (sample `listens.json` and mock API responses).
* [ ] **0.2. Core Tests:** Write unit tests for `parsing.py` (ensuring JSON normalization works) and `reporting.py` (ensuring math/grouping is correct).
* [ ] **0.3. Regression Safety:** Automate the current "Smoke Test" steps to ensure GUI and Threading logic remain stable during refactors.

### Phase 1: Architecture for "Read-Write"

* [ ] **1.1. API Client Extraction:** Create `api_client.py`. Extract networking logic from `enrichment.py` to separate "Data Logic" from "Wire Protocol".
* [ ] **1.2. Auth Management:** Update `user.py` and `gui_user_editor.py` to securely accept and store ListenBrainz User Tokens and Last.fm API keys within the User profile.

### Phase 2: Ingestion & Playlists

* [ ] **2.1. CSV Parser:** Implement a flexible CSV importer that maps arbitrary headers to our canonical `artist`, `track_name`, `album` schema.
* [ ] **2.2. Ephemeral Sessions:** Modify `User` to handle "Session Playlists"—loaded from CSV, rendered in the Table View, and enriching-capable, without permanently merging them into the historical archive.

### Phase 3: Upstream Actions (The "Write" Features)

* [ ] **3.1. "Like" Button:** Add a button below the table: "Like Visible Tracks on ListenBrainz" (utilizing the authenticated `api_client`).
* [ ] **3.2. "Upload Playlist" Button:** Add a button below the table: "Export Visible as Playlist" to post the current view to ListenBrainz.

### Legacy / Maintenance

* **Configuration UI:** To be integrated directly into the User Editor (Phase 1.2).
* **Documentation:** Maintain `BrainzMRI_Instantiation_v3.txt` for context recovery.