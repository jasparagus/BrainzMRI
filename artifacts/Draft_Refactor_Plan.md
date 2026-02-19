# Refactoring Plan: Modular Package Architecture (v8.0)

**Goal:** Reorganize the current "flat" directory structure into a semantic package hierarchy (`app/`).
**Entry Point:** `BrainzMRI.py` (Root).

## 1. Target Directory Structure

The new structure will group files by their architectural role (MVC: Model, View, Controller, Services).

```text
BrainzMRI/
│
├── BrainzMRI.py                  # [NEW] Application Entry Point
├── BrainzMRI.bat                 # Update to point to BrainzMRI.py
├── README.md
├── Instantiation.md              # Update with new paths
├── requirements.txt
│
└── app/                          # Main Package
    ├── __init__.py
    │
    ├── config.py                 # (Moved from root) Singleton Configuration
    │
    ├── ui/                       # [VIEW]
    │   ├── __init__.py
    │   ├── main.py               # (Was gui_main.py)
    │   ├── header.py             # (Was gui_header.py)
    │   │
    │   ├── components/           # Reusable UI Widgets
    │   │   ├── __init__.py
    │   │   ├── filters.py        # (Was gui_filters.py)
    │   │   ├── actions.py        # (Was gui_actions.py)
    │   │   ├── tableview.py      # (Was gui_tableview.py)
    │   │   └── charts.py         # (Was gui_charts.py)
    │   │
    │   └── dialogs/              # Popups / Modal Windows
    │       ├── __init__.py
    │       └── user_editor.py    # (Was gui_user_editor.py)
    │
    ├── controllers/              # [CONTROLLER] Logic Engines
    │   ├── __init__.py
    │   ├── reports.py            # (Was report_engine.py)
    │   ├── sync.py               # (Was sync_engine.py)
    │   └── likes_sync.py         # (Was likes_sync.py)
    │
    ├── models/                   # [MODEL] Data Entities & Aggregation
    │   ├── __init__.py
    │   ├── user.py               # (Was user.py)
    │   ├── reporting.py          # (Was reporting.py)
    │   └── enrichment.py         # (Was enrichment.py)
    │
    └── services/                 # [SERVICES] Utilities & Network
        ├── __init__.py
        ├── api_client.py         # (Was api_client.py)
        └── parsing.py            # (Was parsing.py)
```

## 2. Migration Steps

### Phase 1: Preparation
1.  **Backup:** Commit all current changes to git.
2.  **Create Folders:** Initialize the directory tree including all `__init__.py` files.

### Phase 2: Relocation & Renaming
Move files to their new locations.

| Current File | New Destination |
| :--- | :--- |
| `gui_main.py` | `app/ui/main.py` |
| `gui_header.py` | `app/ui/header.py` |
| `gui_filters.py` | `app/ui/components/filters.py` |
| `gui_actions.py` | `app/ui/components/actions.py` |
| `gui_tableview.py` | `app/ui/components/tableview.py` |
| `gui_charts.py` | `app/ui/components/charts.py` |
| `gui_user_editor.py` | `app/ui/dialogs/user_editor.py` |
| `report_engine.py` | `app/controllers/reports.py` |
| `sync_engine.py` | `app/controllers/sync.py` |
| `likes_sync.py` | `app/controllers/likes_sync.py` |
| `user.py` | `app/models/user.py` |
| `reporting.py` | `app/models/reporting.py` |
| `enrichment.py` | `app/models/enrichment.py` |
| `api_client.py` | `app/services/api_client.py` |
| `parsing.py` | `app/services/parsing.py` |
| `config.py` | `app/config.py` |

### Phase 3: Import Updates (Crucial)
Every file must be opened and its import statements updated to absolute paths.

**Example Changes:**

*   In `app/ui/main.py`:
    *   `import config` $\to$ `from app.config import config`
    *   `from gui_header import ...` $\to$ `from app.ui.header import ...`
    *   `import report_engine` $\to$ `from app.controllers.reports import ReportEngine`

*   In `app/models/reporting.py`:
    *   `import parsing` $\to$ `from app.services import parsing`

*   In `app/controllers/sync.py`:
    *   `from gui_actions import ...` $\to$ `from app.ui.components.actions import ...` (Wait, SyncEngine shouldnut import UI directly ideally, check for circular deps).

### Phase 4: Entry Point Creation
Create `BrainzMRI.py` in the root:
```python
import sys
import logging
from app.ui.main import BrainzMRIGUI
import tkinter as tk

def main():
    root = tk.Tk()
    app = BrainzMRIGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
```

### Phase 5: Verification
1.  Run `python BrainzMRI.py`.
2.  Test core flows:
    *   Load User.
    *   Generate "Top Artists" Report (Testing `app.controllers` -> `app.models`).
    *   Import CSV (Testing `app.services.parsing`).
    *   Resolve Metadata (Testing `app.services.api_client`).

## 3. Risks & Mitigations
*   **Circular Imports:** The View imports Controller, but Controller sometimes needs to notify View.
    *   *Mitigation:* Use callbacks passed via `__init__` rather than importing View classes into Controllers.
*   **Resource Paths:** if `config.py` uses relative paths (`os.path.dirname(__file__)`), moving it to `app/config.py` might break path resolution for `cache/` or `logs/`.
    *   *Mitigation:* Update `config.py` to `BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (go up one level).
