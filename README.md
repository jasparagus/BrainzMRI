# BrainzMRI: ListenBrainz Metadata Review Instrument
A ListenBrainz "Metadata Review Instrument" (MRI) for analyzing listens from the ListenBrainz service.

BrainzMRI is a desktop tool for analyzing your **ListenBrainz** listening history.  
It provides a **GUI application** for generating rich reports about your listening habits, including:

- Top artists, albums, and tracks  
- Time-range-based listening summaries
- Recency-filtered listening patterns (digging up "old favorites")
- Liked-artist reports (list of artists whom you have liked)
- Enriched artist reports with **MusicBrainz genre lookups**  
- Fully sortable, filterable tables in the GUI (regex filtering)
- Exportable text and CSV reports  

---

## **Features**

### GUI Application (BrainzMRI_GUI.py)
- Load a ListenBrainz export ZIP  
- Configure:
  - Time range (days ago)
  - Last-listened range
  - Minimum tracks / minutes thresholds
  - Top-N limits  
- Choose report type:
  - By Artist  
  - By Album  
  - By Track  
  - All Liked Artists  
  - Enriched Artist Report (with genre lookup)  
- View results in a sortable, filterable table  
- Save reports to disk  
- Automatically remembers your last ZIP file  

### CLI Mode (ParseListens.py)
- Parse ListenBrainz ZIPs  
- Generate top-N reports  
- Generate liked-artist reports  
- Generate enriched artist reports  
- Save reports to `/reports`  

### Launcher Script (BrainzMRI.bat)
- Simple menu to launch either:
  - GUI mode  
  - CLI mode  

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

You can run the tool in **GUI mode** or **CLI mode**.

---

## Option A — GUI Mode (Recommended)

### Windows
Double-click:

```
BrainzMRI.bat
```

or run:

```bash
python BrainzMRI_GUI.py
```

### macOS / Linux
Run:

```bash
python3 BrainzMRI_GUI.py
```

---

## Option B — CLI Mode

Run:

```bash
python ParseListens.py
```

You will be prompted to select a ListenBrainz ZIP file.

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
  Restrict listens to a specific window.

- **Last Listened (days ago)**  
  Filter by recency.

- **Top N**  
  Limit the number of results.

- **Minimum Tracks / Minutes**  
  Thresholds for enriched reports.

- **Genre Lookup (API or cache)**  
  Enable/disable MusicBrainz API calls.

### 3. Choose a report type
From the dropdown:

- **By Artist**  
- **By Album**  
- **By Track**  
- **All Liked Artists**  
- **Enriched Artist Report**

### 4. View results
Results appear in a sortable, filterable table:

- Click column headers to sort  
- Use the filter bar to search (regex supported)  
- Clear filter to restore the full dataset  

### 5. Save reports
Click **“Save Report”** to export:

- Text reports (`.txt`) for standard reports  
- CSV reports (`.csv`) for enriched reports  

Reports are saved in a `reports/` folder next to your ZIP file.

---

# Using the CLI

The CLI version provides the same core reporting functions.

Example:

```bash
python ParseListens.py
```

You’ll be prompted to select a ZIP file, and the script will generate:

- Top artists  
- Top albums  
- Liked artists  
- Enriched artist report  

All reports are saved to:

```
<ZIP directory>/reports/
```

---

# Project Structure

```
BrainzMRI/
│
├── BrainzMRI_GUI.py        # GUI application
├── ParseListens.py         # Core parser + CLI reporting
├── BrainzMRI.bat           # Windows launcher
├── reports/                # Auto-created report output folder
└── README.md               # This file
```

# TODO (Future Improvements)
 1. Filter-By-Column Enhancement
    Add a "Filter By" dropdown next to the filter entry.
    Options: "All" + list of current table column headers.
    Behavior:
       - If "All": apply regex across all columns (current behavior).
       - Else: apply regex only to the selected column.
    Requirements:
       - Populate dropdown after show_table() builds the Treeview.
       - Update apply_filter() to respect the selected column.

 2. UI Layout Abstraction
    Several UI sections repeat the same pattern (Frame + Label + Entry).
    Create helper functions to reduce boilerplate and improve readability.

 3. show_table() Decomposition
    show_table() currently handles:
       - clearing the frame
       - building the filter bar
       - building the table container
       - creating the Treeview
       - wiring sorting
       - inserting rows
    Break into smaller helpers:
       build_filter_bar(), build_table_container(), populate_table()

 4. run_report() Decomposition
    run_report() still handles multiple responsibilities:
       - parsing inputs
       - applying time filters
       - dispatching report functions
       - applying recency filters
       - saving state
       - rendering the table
    Consider splitting into:
       parse_time_range(), parse_thresholds(),
       generate_report(), finalize_report()

 5. Hybrid ZIP + API Mode (ListenBrainz + Last.fm)
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