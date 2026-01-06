# BrainzMRI: ListenBrainz Metadata Review Instrument
A ListenBrainz "Metadata Review Instrument" (MRI) for analyzing listens from the ListenBrainz service.

BrainzMRI is a desktop tool for analyzing your **ListenBrainz** listening history.  
It provides a **GUI application** for generating rich reports about your listening habits, including:

- Top artists, albums, and tracks  
- "Time Range" filter for listens enables looking across arbitrary time windows (by "days ago")
- "Last Played" filter enables digging up "old favorites" and more (by "days ago")
- Liked-artist reports (list of artists whose tracks you have liked)
- Optional genre enrichment with **MusicBrainz genre lookups**
- Fully sortable, filterable tables in the GUI (using regex)
- Exportable CSV reports  

## Attribution
This project was developed with assistance from Microsoft Copilot as a fun test of "Vibe Coding".

---

## **Features**
<img src="example.png" alt="GUI Example" width="600">

### GUI Application (BrainzMRI_GUI.py)
- Load a ListenBrainz export ZIP  
- Configure Report filters
- Choose report type (Artist, Album, Likes, and more)
- Optionally enrich any report with MusicBrainz genre data  
- View results in a sortable, fully filterable table  
- Save reports to disk as CSV  
- Automatically remembers your last ZIP file  
- Stores configuration info in a `config.json` file

### Launcher Script (BrainzMRI.bat)
- Simple menu to launch either:
  - GUI mode (starts by default)
  - Debug mode (available for tinkering)

---

# Installation

BrainzMRI requires **Python 3.10+** and a few common libraries.

### 1. Clone the repository
```bash
git clone https://github.com/jasparagus/BrainzMRI.git
cd BrainzMRI
```

### 2. Install dependencies
From inside the project directory:

```bash
pip install -r requirements.txt
```

If you don’t have a `requirements.txt`, install manually:

```bash
pip install pandas tqdm
```

*(Tkinter is included with most Python installations.)*

---

# Running BrainzMRI

## Windows
Double-click:

```
BrainzMRI.bat
```

or run:

```bash
python BrainzMRI_GUI.py
```

## macOS / Linux
Run:

```bash
python3 BrainzMRI_GUI.py
```

---

# Using the GUI

### 1. Select your ListenBrainz ZIP
Click **“Select ListenBrainz ZIP”** and choose the export file downloaded from ListenBrainz.

The app will automatically parse:
- listens  
- feedback (likes/dislikes)  
- metadata  

### 2. Configure filters
You can set:

- **Time Range (days ago)**  
  Restrict listens to a specific window (by listened date). Applied at the listen level.

- **Last Listened (days ago)**  
  Filter by recency (based on when listens occurred). Applied at the entity level (artist/album/track) based on each entity’s true last listen.

- **Top N**  
  Limit the number of results.

- **Thresholds for Minimum Listens / Time Listened**  
  Apply thresholds to filter out low-activity artists, albums, tracks, or liked artists:
  - Min. Listens Threshold (per entity)
  - Minimum Time Listened Threshold (per entity, based on total duration)

### 3. Configure enrichment (optional)
- **Perform Genre Lookup (Enrich Report)**  
  When checked, the report is enriched with genre information after all filtering and sorting.
  - Genre information comes from MusicBrainz (currently artists only).
  - Runs after all filters and sorting.  
  - May be slow if API lookup is enabled (1.2s per entity)

- **Genre Enrichment Source**  
  - **Cache**: uses only the local genre cache, built from past API lookups.
  - **Query API (Slow)**: query MusicBrainz and update the cache (subject to rate limiting)  
  - Enabled only when enrichment is turned on

### 4. Choose a report type
From the dropdown:

- **By Artist**
  - Note: collaborating artists are counted separately
- **By Album**  
- **By Track**  
- **All Liked Artists**  

### 5. View results
Results appear in a sortable, filterable table:

- Click column headers to sort  
- Use the filter bar to search (regex supported)  
- Clear the filter to restore the full dataset  

### 6. Save reports
Click **“Save Report”** to export:

- CSV reports (`.csv`) for all report types (with or without enrichment)  

Reports are saved in a `reports/` folder next to your ZIP file.

---

# Project Structure

```text
BrainzMRI/
│
├── BrainzMRI.bat                 # Windows launcher
├── BrainzMRI_GUI.py              # Main GUI entry point (tkinter)
├── gui.py                        # Core GUI logic and orchestration
├── report_table_view.py          # Table rendering, filtering, sorting UI
├── report_engine.py              # Pure report-generation logic
├── reporting.py                  # Aggregation, grouping, and report helpers
├── enrichment.py                 # Genre/metadata enrichment logic
├── user.py                       # User cache utilities and helpers
├── parsing.py                    # data parsing and canonicalization
│
├── LICENSE.txt
├── README.md
├── requirements.txt			  # required python modules	
├── example.png
├── config.json                   # Auto-created settings file
├── cache.json                    # Auto-created cache folder for enrichment data
└── reports/                      # Auto-created report output folder

```

---

# **Major Modules & Classes**

## gui.py:  Main Application Orchestrator
Handles:
- Window creation, layout, event wiring
- User selection and ZIP loading
- Report parameter parsing (thresholds, time ranges, recency)
- Calling `ReportEngine.generate_report()`
- Displaying results via `ReportTableView`

Important functions:
- `run_report()`
- `load_from_zip()`
- `load_user_cache()`
- `save_user_cache()`
- `refresh_user_list()`


### Class: `ReportTableView`
Responsible for:
- Rendering DataFrames in a Treeview
- Column sorting
- Regex filtering
- Clipboard copy

Key methods:
- `show_table(df)`
- `build_filter_bar()`
- `apply_filter()`
- `clear_filter()`
- `sort_column(tree, df, col)`
- `copy_selection_to_clipboard()`


## report_engine.py: Pure Report Logic
### Class: `ReportEngine`
Encapsulates:
- Time-range filtering
- Recency filtering
- Thresholding (min listens, min minutes)
- Top-N selection
- Calling reporting functions
- Optional enrichment

Key methods:
- `generate_report(base_df, mode, liked_mbids, ...)`
- `get_status(mode)`

Internal handler table maps:
- `"By Artist"` → `reporting.report_top`
- `"By Album"` → `reporting.report_top`
- `"By Track"` → `reporting.report_top`
- `"All Liked Artists"` → `reporting.report_artists_with_likes`
- `"Raw Listens"` → `reporting.report_raw_listens`


## reporting.py: Aggregation & Report Helpers
Important functions:
- `report_top(df, group_col, by, days, topn, min_listens, min_minutes)`
- `report_artists_with_likes(df, liked_mbids, ...)`
- `report_raw_listens(df, topn)`
- `filter_by_days(df, column, start_days, end_days)`


## enrichment.py: Metadata & Genre Enrichment
Important functions:
- `enrich_report(df, report_type_key, source)`
- `load_genre_cache()`
- `save_genre_cache()`
- `lookup_genres(mbid)`
- `fetch_mb_metadata(mbid)`


## user.py: User Cache Utilities
Important functions:
- `get_cache_root()`
- `get_user_cache_dir(username)`
- `load_user_cache(username)`
- `save_user_cache(username, df)`
- `get_cached_usernames()`  ← recently moved here


## parsing.py: ListenBrainz ZIP Parsing & Canonicalization
Important functions:
- `parse_listens_zip(zip_path)`  
  Load a ListenBrainz ZIP export and return a canonicalized DataFrame.
- `parse_jsonl_stream(file_obj)`  
  Stream‑parse JSONL listens safely and yield raw listen dicts.
- `canonicalize_listens(df)`  
  Normalize columns, MBIDs, timestamps, and naming conventions.
- `convert_timestamps(df, column="listened_at")`  
  Convert raw timestamps to timezone‑aware UTC datetimes.
- `normalize_columns(df)`  
  Ensure all expected columns exist with consistent types.
- `dedupe_listens(df)`  
  Remove duplicate listens using MBIDs + precise timestamps.

---


# TODO (Items for Future Improvements)

## New Visualizations
- Stacked bar charts of top N artists/albums/tracks over time  
  - Use filtered data as the population  
  - Cap at ~20 entities for clarity  
  - Each entity receives a distinct color  
- “Top New Artists/Albums/Tracks by Year”
- “Percent New Artists/Albums/Tracks by Year”
- Annual counts of distinct artists, albums, and tracks
- Add “Export Chart” option (PNG/SVG)

## Report Presets
- Dropdown presets for common report types:
  - Forgotten Favorites
  - All-Time Top 10
  - Favorite New Discoveries (requires tracking first-listen dates)
  - Recently Neglected Artists
  - Etc.

## UI Improvements
- Abstract repeated UI patterns (Frame + Label + Entry)
- Break `show_table()` into:
  - `build_filter_bar()`
  - `build_table_container()`
  - `populate_table()`
- Break `run_report()` into:
  - `parse_time_range()`
  - `parse_thresholds()`
  - `generate_report()`
  - `apply_enrichment()`
  - `finalize_report()`
- Add “Refresh Data” button for reloading user cache
- Add “Clear User Cache” utility

## Enrichment Enhancements
- Album-level enrichment using release MBIDs
- Track-level enrichment using recording MBIDs
- Expand genre cache to support multiple entries per entity
- UI viewer for missing-genre log (with MusicBrainz URLs)
- Optional “Rebuild Genre Cache” tool

## Hybrid Mode (ListenBrainz + Last.fm APIs)
- Optional API ingestion for new listens
- Merge ZIP + API data into a persistent local archive
- Deduplicate listens using MBIDs + timestamps
- UI controls for enabling/disabling ingestion
- “Sync New Listens” button

## MusicBrainz Contribution Tools
- Log artists with missing genres + direct MusicBrainz URLs
- Provide link to MusicBrainz metadata best-practices
- Minimal UI pop-out for metadata editing workflow

## Robustness & Edge Cases
- Improve empty-result handling across all report types
- Add user-friendly messages for invalid filters or regex errors
- Validate enrichment source availability (cache vs. API)

## Multi-Source Ingestion & Fuzzy Deduplication
- Support ingestion from heterogeneous sources (ListenBrainz, Last.fm, Spotify, Apple Music, YouTube Music, CSV exports)
- Normalize entity names (artist/album/track) across sources using:
  - Unicode normalization
  - Case folding
  - Punctuation/parenthetical stripping
  - Fuzzy matching (Levenshtein/Jaro-Winkler)
- Introduce a canonical entity resolver:
  - Resolve missing MBIDs via MusicBrainz lookups
  - Cache resolved entities globally
  - Track resolver confidence scores
- Handle timestamp precision differences:
  - Second-precision, minute-precision, day-precision, and date-only sources
  - Convert all timestamps to UTC
  - Store precision metadata per listen
- Implement probabilistic deduplication:
  - Combine similarity scores for artist/album/track names
  - Incorporate timestamp proximity windows based on source precision
  - Use duration (if available) as a secondary signal
  - Produce a final dedupe confidence score
- Add provenance tracking to the canonical DataFrame:
  - `source` (ZIP, API, CSV, etc.)
  - `source_precision`
  - `resolver_confidence`
  - `mbid_confidence`
- Provide UI tools for reviewing and resolving ambiguous matches

## Smarter Way To Address Multi-Artist listens
- Currently, each artist on a listen (collaborations, etc.) is counted as a row
- Ideally, this would be true for per-artist reports, but not for per-album or per-track reports. Need to figure out how to do this.

## Missing-Genre Log Improvements
- Deduplicate entries in `missing_genres.txt`
- Optionally timestamp each entry for auditability
- Provide a lightweight cleanup/rotation mechanism
