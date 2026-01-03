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
