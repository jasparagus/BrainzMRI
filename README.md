# BrainzMRI: ListenBrainz Metadata Review Instrument
A ListenBrainz "Metadata Review Instrument" (MRI) for analyzing listens from the ListenBrainz service.

BrainzMRI is a desktop tool for analyzing your **ListenBrainz** listening history.  
It provides a **GUI application** for generating rich reports about your listening habits, including:

- Top artists, albums, and tracks  
- "Time Range" filter for listens enables looking across arbitrary time windows (by "days ago")
- "Last Played" filter enables digging up "old favorites" and more (by "days ago")
- Liked-artist reports (list of artists whom you have liked)
- Optional genre enrichment with **MusicBrainz genre lookups**
- Fully sortable, filterable tables in the GUI (using regex)
- Exportable CSV reports  

---

## **Features**
<img src="example.png" alt="GUI Example" width="700">

### GUI Application (BrainzMRI_GUI.py)
- Load a ListenBrainz export ZIP  
- Configure:
  - Time Range (as a window; days ago)
  - Last-listened Range (as a window; days ago)
  - Minimum listens / minutes thresholds
  - Top-N limits  
- Choose report type:
  - By Artist  
  - By Album  
  - By Track  
  - All Liked Artists  
- Optionally enrich any report with MusicBrainz genre data  
- View results in a sortable, fully filterable table  
- Save reports to disk as CSV  
- Automatically remembers your last ZIP file  
- Stores configuration info in a `config.json` file

### Launcher Script (BrainzMRI.bat)
- Simple menu to launch either:
  - GUI mode
  - Debug mode

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
  Restrict listens to a specific window (by listened date).

- **Last Listened (days ago)**  
  Filter by recency (based on when listens occurred).

- **Top N**  
  Limit the number of results.

- **Minimum Listens / Minutes**  
  Apply thresholds to filter out low-activity artists, albums, tracks, or liked artists:
  - Min. Listens Threshold (per entity)
  - Min. Minutes Listened Threshold (per entity, based on total duration)

### 3. Configure enrichment (optional)
- **Perform Genre Lookup (Enrich Report)**  
  When checked, the report is enriched with genre information after all filtering and sorting.

  Tooltip:
  > Add genre information to the report using MusicBrainz.  
  > Runs after all filters and sorting.  
  > May be slow if API lookup is enabled.

- **Genre Enrichment Source**  
  - **Cache** — use only the local genre cache  
  - **Query API (Slow)** — query MusicBrainz and update the cache (subject to rate limiting)  
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
├── BrainzMRI.bat           # Windows launcher
├── BrainzMRI_GUI.py        # GUI application
├── LICENSE.txt             # License (GNU GPL)
├── ParseListens.py         # Core parser and report logic
├── README.md               # This file
├── example.png             # Example of GUI
├── requirements.txt        # Required Python modules
├── reports/                # Auto-created report output folder
└── config.json             # Auto-created settings file
```

# TODO (Future Improvements)

## UI Layout Abstraction
    Several UI sections repeat the same pattern (Frame + Label + Entry).
    Create helper functions to reduce boilerplate and improve readability.

## show_table() Decomposition
    show_table() currently handles:
       - clearing the frame
       - building the filter bar
       - building the table container
       - creating the Treeview
       - wiring sorting
       - inserting rows
    Break into smaller helpers:
       build_filter_bar(), build_table_container(), populate_table()

## run_report() Decomposition
    run_report() still handles multiple responsibilities:
       - parsing inputs
       - applying time and recency filters
       - dispatching report functions
       - applying thresholds
       - running optional enrichment
       - saving state
       - rendering the table
    Consider splitting into:
       parse_time_range(), parse_thresholds(),
       generate_report(), finalize_report()

## Hybrid ZIP + API Mode (ListenBrainz + Last.fm)
    Add an optional "Hybrid Mode" that:
       - Loads full history from a ListenBrainz ZIP if available.
       - Fetches new listens from ListenBrainz API (timestamp-based).
       - Fetches new listens from Last.fm API (page-based).
       - Merges all sources into a unified local archive.
       - Deduplicates listens using recording_mbid, timestamps, and metadata.
    UI Requirements:
       - Add checkboxes to enable/disable LB API and Last.fm API ingestion.
       - Add a "Sync New Listens" button.
    Long-term Goal:
       - Maintain a persistent local archive that updates incrementally
         without requiring repeated ZIP downloads.

## Unify Enrichment and Threshold Logic Across All Reports

### Goal
Convert enrichment from a special-case “Enriched Artist Report” into a generic, optional post-processing step that can be applied to *any* report (Artist, Album, Track, Liked Artists). Standardize threshold and Top-N behavior across all report types, transition all saved reports to CSV format, and introduce a structured, entity-aware genre cache. This phase implements artist-based enrichment only; album and track enrichment will be added in a later patch.

### Planned Changes

1. **Remove “Enriched Artist Report” from the report type dropdown.**  
   - Report types become: **Artist**, **Album**, **Track**, **Liked Artists Only**.

2. **Add a new checkbox: “Perform Genre Lookup (Enrich Report)”.**
   - When checked, enrichment is applied *after* all filtering and sorting.  
   - When unchecked, no enrichment occurs.
   - Tooltip:
     ```text
     Add genre information to the report using MusicBrainz.
     Runs after all filters and sorting.
     May be slow if API lookup is enabled.
     ```

3. **Add a new dropdown: “Genre Enrichment Source”.**  
   - Options: **Cache** and **Query API (Slow)**.  
   - Only enabled when “Perform Genre Lookup” is checked.

4. **Remove checkbox “Do MusicBrainz Genre Lookup (Slow)?”.**
   - Fully replaced by:
     - “Perform Genre Lookup (Enrich Report)”  
     - “Genre Enrichment Source” (Cache / Query API)

5. **Rename “Min. Tracks Listened Threshold” → “Min. Listens Threshold”.**  
   - Update variable names, labels, and parser arguments.  
   - Threshold meaning:  
     - Artist report → minimum listens per artist  
     - Album report → minimum listens per album  
     - Track report → minimum listens per track  
     - Liked Artists report → **threshold by liked listens only** (do not join back to full listens)

6. **Apply thresholds *before* Top N for all report types.**  
   New processing pipeline:

   ```text
   raw data
     → time range filter
     → recency filter
     → threshold filter (min_listens, min_minutes)
     → sort
     → Top N
     → enrichment (optional)
     → display/save
   ```

7. **Modify all report generators to accept unified filter parameters:**  
   - `min_listens`  
   - `min_minutes`  
   - `top_n`  
   Apply these consistently across Artist, Album, Track, and Liked Artists reports.  
   - For Liked Artists: thresholds apply to **liked listens only**.

8. **Refactor enrichment into a generic function:**  
   ```text
   enrich_report(df, report_type, source, zip_path)
   ```
   Behavior:
   - Artist reports → use MusicBrainz **Artist** API/cache  
   - Album reports → **use artist genres only (incremental scope)**  
   - Track reports → **use artist genres only (incremental scope)**  
   - No internal thresholding; enrichment acts only on the DataFrame it receives.  
   - Album/track MBID-based enrichment will be added in a future patch.

9. **Redesign the genre cache to support multiple entity types.**  
   Replace string-keyed entries with structured objects:

   ```json
   [
     {
       "entity": "artist",
       "artist": "Burial",
       "album": null,
       "track": null,
       "artist_mbid": "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6",
       "genres": ["dubstep", "electronic"]
     },
     {
       "entity": "album",
       "artist": "Burial",
       "album": "Untrue",
       "track": null,
       "release_mbid": "e08c3db9-fc33-4d4e-b8b7-818d34228bef",
       "genres": ["dubstep"]
     },
     {
       "entity": "track",
       "artist": "Burial",
       "album": "Untrue",
       "track": "Etched Headplate",
       "recording_mbid": "1eacb3ca-e8e1-4588-920d-1187dcb8ca79",
       "genres": ["dubstep"]
     }
   ]
   ```

   **Lookup rules:**
   - Prefer MBID matching when available  
   - Fall back to name-based matching  
   - If multiple matches exist, use the most recent or merge genres  

10. **Transition all saved reports to CSV format.**  
    - Standard (non-enriched) reports → CSV  
    - Enriched reports → CSV  
    - Update documentation accordingly  
    - GUI table remains the primary human-readable view

11. **Update README to reflect the new system:**  
    - New enrichment checkbox and source dropdown  
    - Removal of “Enriched Artist Report”  
    - Unified threshold behavior  
    - Liked Artists thresholds apply to liked listens only  
    - Artist-only enrichment for now (album/track enrichment in future patch)  
    - CSV output for all reports  
    - Updated terminology (“Min. Listens Threshold”)

### Rationale

- Eliminates hidden or special-case logic  
- Makes enrichment predictable, consistent, and extensible  
- Provides a clean migration path for album/track enrichment  
- Produces a cleaner, more intuitive UI  
- Simplifies debugging and future maintenance  
- CSV output improves interoperability with spreadsheets and analysis tools
```