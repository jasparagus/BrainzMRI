# BrainzMRI: ListenBrainz Metadata Review Instrument
A ListenBrainz "Metadata Review Instrument" (MRI) for analyzing listens from the ListenBrainz service.

BrainzMRI is a desktop tool for analyzing your **ListenBrainz** listening history.  
It provides a **GUI application** for generating rich reports about your listening habits, including:

- Top artists, albums, and tracks  
- "Time Range" filter for listens enables looking across arbitrary time windows (by "days ago")
- "Last Played" filter enables digging up "old favorites" and more (by "days ago")
- Liked-artist reports (list of artists whom you have liked)
- Enriched artist reports with **MusicBrainz genre lookups**  
- Fully sortable, filterable tables in the GUI (using regex)
- Exportable text and CSV reports  

---

## **Features**
<img src="example.png" alt="GUI Example" width="700">

### GUI Application (BrainzMRI_GUI.py)
- Load a ListenBrainz export ZIP  
- Configure:
  - Time Range (as a window; days ago)
  - Last-listened Range (as a window; days ago)
  - Minimum tracks / minutes thresholds (enriched report only for now)
  - Top-N limits  
- Choose report type:
  - By Artist  
  - By Album  
  - By Track  
  - All Liked Artists  
  - Enriched Artist Report (with genre lookup)  
- View results in a sortable, fully filterable table  
- Save reports to disk  
- Automatically remembers your last ZIP file  
- Stores configuration info in a "config.json" file

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
  Restrict listens to a specific window.

- **Last Listened (days ago)**  
  Filter by recency.

- **Top N**  
  Limit the number of results.

- **Minimum Tracks / Minutes**  
  Thresholds for enriched reports only, for now.

- **Genre Lookup (API or cache)**  
  Enable/disable MusicBrainz API calls (currently slow due to rate limit).

### 3. Choose a report type
From the dropdown:

- **By Artist**
	- Note: collaborating artists are counted separately
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

# Project Structure

```
BrainzMRI/
│
├── BrainzMRI.bat           # Windows launcher
├── BrainzMRI_GUI.py        # GUI application
├── LICENSE.txt             # License (GNU GPL)
├── ParseListens.py         # Core parser for GUI
├── README.md               # This file
├── example.png             # Example of GUI
├── requirements.txt        # Required Python modules
├── reports/                # Auto-created report output folder
└── config.json             # Auto-created settigns file
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
       - applying time filters
       - dispatching report functions
       - applying recency filters
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
		 
		 
## Convert "Enriched Artist Report" into a generic enrichment option

Goal:
    Simplify the report type dropdown and make enrichment a post-processing step
    instead of a separate report type. This will also prepare the codebase for
    future enrichment of album and track reports.

Planned Changes:
    1. Remove "Enriched Artist Report" from the report type dropdown.
    2. Add a new checkbox: "Enrich report with genres".
    3. Repurpose the existing "Use MusicBrainz API (slow)" checkbox so that:
           - If enrichment is enabled:
                 - API checkbox determines API vs. cache-only behavior.
           - If enrichment is disabled:
                 - API checkbox is ignored.
    4. Update run_report() so that:
           - It generates the base report (artist/album/track/liked).
           - If enrichment checkbox is enabled:
                 - Apply genre enrichment to the result.
    5. Keep threshold logic (mins/tracks) tied to enrichment unless later separated.
    6. Ensure the GUI layout accommodates the new checkbox cleanly.
    7. Update README to reflect:
           - Fewer report types in the dropdown.
           - Enrichment as an optional enhancement step.
           - Future support for album/track enrichment.

Rationale:
    - Reduces cognitive load in the UI.
    - Makes enrichment behavior explicit and consistent.
    - Sets the foundation for enriching album and track reports later.