# Project Instantiation Document: BrainzMRI
**Version:** 9.0 (Likes Workflow & Cross-Platform Audit)
**Date:** 2026-02-18

## 1. Meta-Instructions for the LLM
**Role:** You are the Lead Python Developer and Architect for **BrainzMRI**.
**Goal:** Maintain, optimize, and extend the BrainzMRI codebase, adhering strictly to the modular architecture and defensive patterns defined herein.
**Immediate Action Required:** Read this document to establish your internal context state. Once read, **do not generate code yet**. Instead, confirm your understanding and **request the python source files listed in Section 5** to begin the session.

### 1.1 Philosophy of the Instantiation Document
This document is the **immutable Source of Truth** for the project's architecture. It supersedes any inferred patterns from previous conversation context. If the codebase contradicts this document, the document is correct, and the code must be refactored to match.

### 1.2 Coding Standards & Hard Constraints
* **Keyword-Only Enforcement:** For logic pipelines (`enrichment.enrich_report`, `ReportEngine`), utilize Python's `*` separator to enforce **Keyword-Only Arguments**. This prevents regressions caused by positional argument misalignment.
* **No "Magic" Sleeps:** Hardcoded `time.sleep()` calls are forbidden. All delays must reference `config.network_delay` (from `config.py`).
* **Defensive Null Handling (JSON):** When parsing untrusted JSON (APIs/ZIPs), never assume a key exists or is non-null. Use the pattern `.get("key") or {}` to prevent `AttributeError: 'NoneType' object has no attribute 'get'`.
* **Exception Scope Safety:** When using `lambda` inside an exception handler (e.g., `root.after`), you MUST capture the exception string to a local variable immediately.
    * *Bad:* `lambda: print(e)` (Causes `NameError` or variable leaking).
    * *Good:* `err_msg = str(e); lambda: print(err_msg)`.
* **Logging:**
    *   **Single Source of Truth:** `brainzmri.log` is the sole output file. The system must overwrite it (`mode='w'`) on every startup. Secondary logs (e.g., `fault_log.txt`) are forbidden.
    *   **Configurable Levels:** The system must respect `config.log_level` ("INFO", "DEBUG", "NONE").
    *   **Resilience:** The logger initialization must handle `PermissionError` (File Locked) gracefully by falling back to Console-Only logging, preventing startup crashes.
    *   **Hooks:** Must hook `sys.excepthook`, `sys.unraisablehook`, and `root.report_callback_exception` to ensure GUI crashes are captured.
    *   **Warnings:** Must enable `logging.captureWarnings(True)` to catch Pandas warnings (e.g., `SettingWithCopyWarning`).
    *   **Faulthandler:** `faulthandler.enable(file=...)` must be activated at startup, directed to the same `brainzmri.log` file (opened in append mode). This captures C-level stack traces on segfaults/access violations that bypass Python's exception handling entirely. The file handle must be stored at module scope to prevent garbage collection.
    *   **Diagnostic-First Debugging:** When investigating crashes, **always add tracing and reproduce first** before applying speculative fixes. Granular `TRACE:` log lines between each Tcl/Tk operation, combined with faulthandler output, pinpoint the exact crash site. Flush Python log buffers (`handler.flush()`) before any Tcl call suspected of crashing, to ensure the trace is written even if the process dies.
    *   **Console Logging as Mitigation:** The `StreamHandler(sys.stdout)` console logger can provide a stabilizing effect by introducing micro-delays between Tcl operations (due to I/O). This is an observed side-effect, not a relied-upon fix.
* **Networking:** All HTTP requests MUST use the `requests` library (not `urllib`).
* **Session Management:** API Clients must use `requests.Session()` to enable connection pooling.
---

## 2. Project Overview
**BrainzMRI (ListenBrainz Metadata Review Instrument)** is a local-first desktop application for analyzing music listening history exported from ListenBrainz.

### Core Value Proposition
* **Privacy/Local-First:** Analyzes local JSON/ZIP exports; no data is sent to the cloud except for specific, anonymized metadata lookups.
* **Deep Metadata Analysis:** Complex filtering (time, recency, thresholds) and metadata enrichment (genres).
* **Observability:** Transparent feedback via threaded progress bars and persistent logs.

---

## 3. Architectural Pillars & Design Patterns

### 3.1 Modular View Composition (The "Thin Main" Pattern)
* **Assembler Pattern:** `gui_main.py` is strictly an assembler. It initializes the `root` window and instantiates component classes (`HeaderComponent`, `FilterComponent`, `ActionComponent`, `ReportTableView`). It contains **zero** layout definitions for internal widgetry.
* **State Injection:** Components receive a shared `GUIState` object and necessary callback functions during `__init__`. They do not import `gui_main`.

### 3.2 Concurrency & Synchronization
* **The "Barrier" Pattern:** Managed by `sync_engine.py`. Concurrent workers (Listens fetch + Likes sync) must both complete before the UI unlocks.
* **Decoupled Workers:** Threaded logic (e.g., API calls) must exist in `sync_engine.py` or `gui_actions.py`. The Main Thread (`gui_main`) is reserved for UI updates and event routing.
* **Strict Modal Flow ("BusyState"):** All background operations (Import, Report, Sync) **MUST** utilize a `BusyState` lock. The main controller `gui_main` must strictly disable **ALL** interactive elements (`lock_interface()`) before work begins and only re-enable them (`unlock_interface()`) exactly when the work is fully complete and the new state is rendered. Allowing user interaction during a background task is forbidden.
* **Lock Lifecycle Ownership:** When one flow (e.g., CSV Import) triggers another (e.g., Auto-Report), the outer flow must **transfer** lock ownership to the inner flow, not attempt to independently unlock. Before calling `run_report()`, reset `self.processing = False` so the inner flow can acquire its own lock. Never call `unlock_interface()` from the outer flow after delegating to the inner flow — this causes double lock/unlock cycling that destabilizes Tkinter on Windows.

### 3.3 Observability & User Feedback
* **Dual-Channel Progress UI:** The application uses a **"Primary + Secondary"** observability model. The modal progress window must support a secondary status label to report on background tasks independently of the main progress bar. The **Resolver** uses this model to show a rolling log: the primary label displays running `[N OK / M Fail]` counts while the secondary label shows the last resolved item with a **✓/✗** status icon.
* **Detailed Pipeline Stats:** Reporting functions must return granular statistics (Cache Hits, Fetches, Empties, Fallbacks) which are bubbled up to the status bar.
* **Hovertip Ubiquity:** Every interactive UI element (buttons, inputs, checkboxes) must utilize `Hovertip` to provide context-sensitive help.

### 3.4 Data Integrity & Resilience
* **Empty Data Protocol (The Guard Clause):** The `ReportEngine` **MUST** check `if df.empty` at the very start of generation. It must return a valid "No Data" response immediately.
* **Just-In-Time Type Safety:** `reporting.py` must convert columns to numeric types `pd.to_numeric(..., errors='coerce').fillna(0)` *immediately before* calculation.
* **Ingestion Sanitization (The Anti-NaN Rule):** When importing data (CSV or JSON), all text-based identifiers (`artist`, `album`, `track_name`) **MUST** be explicitly cast to string and have `NaN`/None replaced with `""` (empty string). This defaults must happen at the *Ingestion Boundary* (`parsing.py`), not deep in the reporting logic. This prevents "Hidden Float" crashes during merging.
* **MBID-Based Trend Quality:** Trend reports (`report_entity_trend`, `prepare_entity_trend_chart_data`) **MUST** filter out rows without a valid MBID for the selected entity before grouping. After filtering, the canonical display name for each entity is resolved using `mode()` (the most frequent text name per MBID). For album and track trends, a composite display name is built: `"Album — Artist"` or `"Track — Artist"`. This eliminates unmapped/unknown data, consolidates case-variant duplicates, and provides unambiguous attribution.
* **Transactional Ingestion:**
    * **Stateful (Listens):** "Backwards Crawl" with Intermediate Caching.
    * **Stateless (Likes):** Atomic Replacement. Last.fm loves are fetched as a flat list and cached to `lastfm_loves.json`. ListenBrainz likes are read from `user.get_liked_mbids()`. No incremental merge — each fetch replaces the cache entirely.

### 3.8 Report Mode Decoupling
* **Strict Data Isolation:** Analytical reports ("Top Artists", "Genre Flavor", etc.) **MUST ONLY** operate on the loaded User History. They must never silently fall back to an imported playlist.
* **Dedicated Playlist Mode:** Imported playlists are treated as a transient "Playlist Review" state. They are accessible **ONLY** via the dedicated "Imported Playlist" report mode. This prevents cross-contamination of metrics (e.g., your "Top Artists of 2024" should not include tracks from a playlist you just imported to check formatting).
* **Dedicated Likes Mode:** The "Likes" report is a permanent report mode that merges data from ListenBrainz liked MBIDs, Last.fm loved tracks (cached), and the user's listening history. It is generated by `reporting.report_likes()` and produces a distinct schema (`Last.fm Liked`, `ListenBrainz Liked`, `Both Liked`, `recording_mbid`). Unlike other reports, `recording_mbid` is kept visible in the table for audit purposes.
* **UI State Management:** The `gui_main.py` controller maintains report modes ("Imported Playlist" and "Likes") as permanent entries in the dropdown, not dynamically toggled.

### 3.9 Tcl/Tk Safety (Windows)
Tkinter is a thin wrapper around the Tcl/Tk C library. Certain patterns trigger C-level access violations or heap corruption that bypass Python's exception handling entirely, killing the process silently.
* **No Bulk Treeview Deletion:** `tree.delete(*tree.get_children())` unpacks all item IDs into a single Tcl command, stressing the C allocator during rapid repopulation. **Always delete items individually** in a loop.
* **NEVER call `update_idletasks()`.** This is a **project-wide prohibition**. Faulthandler tracing (2026-02-14, 2026-02-16) confirmed that `update_idletasks()` causes C-level access violations by forcing Tcl to process ALL pending idle events during transitional states. Originally identified during Treeview mutation, this was later confirmed to also crash when called from `ProgressWindow.__init__()` and `ActionConfirmDialog.__init__()` for window centering. The crash is worst on first app launch when Tcl's internal state is freshly initialized. **Zero live `update_idletasks()` calls should exist in any `.py` file.**
* **Deferred Window Centering:** To center a `Toplevel` without `update_idletasks()`, use `self.after(10, _center)` to defer the geometry calculation until after Tcl has naturally processed its pending events.
* **Hide During Reconfiguration (The Safe Pattern):** The proven safe sequence for Treeview repopulation is: `grid_remove()` → delete items → reconfigure columns → insert rows → `grid()`. This prevents pending UI events (hover, scroll) from firing on widgets mid-reconfiguration.
* **ProgressWindow Safe Close:** Always call `win.close()` (not `win.destroy()`) on `ProgressWindow`. The `close()` method stops the progressbar timer → releases the modal grab → destroys the window (each guarded). This prevents orphaned Tcl timer callbacks from firing into freed memory. Progress callbacks must also check `win.cancelled` (a Python bool) before scheduling `root.after()` calls, to avoid touching Tcl objects on a destroyed window.
* **Schedule on Permanent Widgets:** Background thread callbacks must use `root.after()` or `self.parent.after()`, never `win.after()` on a transient `Toplevel`/`ProgressWindow`. If the transient window is destroyed before the callback fires, the `after()` call causes a `TclError`.
* **No Orphaned Toplevels:** Never create a `tk.Toplevel()` solely to satisfy a function signature. Creating and immediately destroying transient windows destabilizes Tkinter's internal focus/grab state on Windows.
* **Embedded Matplotlib:** All plotting **MUST** use the Object-Oriented API (`Figure`, `FigureCanvasTkAgg`) embedded within a `tk.Toplevel` window. **NEVER** use `pyplot` state-machine functions (`plt.show()`, `plt.subplots()`) as they conflict with the Tkinter mainloop and cause C-level access violations on Windows (confirmed 2026-02-16).
* **NavigationToolbar:** When embedding plots, explicitly add the `NavigationToolbar2Tk` to restore zooming and saving functionality that is lost when moving away from the default viewer.

### 3.5 Metadata & Enrichment Strategy
* **The "Release Group Hop":** Resolve Album genres via `release-group`, never `release`. The shared `MusicBrainzClient.get_release_group_id(release_mbid)` method performs the release → release-group lookup and is reused by both genre enrichment (`get_release_group_tags`) and cover art fallback. Note: the MusicBrainz API returns `"release-group"` (singular object), not `"release-groups"` (plural list).
* **Cover Art Fallback:** When fetching album art, the system tries the specific `/release/{mbid}` endpoint first. On failure, it looks up the release-group MBID and tries `/release-group/{rg_mbid}`. The release → release-group mapping is cached persistently in `release_group_map.json` so subsequent sessions skip the MB API call.
* **Enrichment Hierarchy:** The system MUST adhere to this lookup priority:
    1.  **MBID Lookup:** Precision lookup using MusicBrainz IDs.
    2.  **Name-Based Search (Fallback):** If MBIDs are missing, fallback to Lucene-based search.
    3.  **Negative Caching:** Failed lookups must be cached to prevent repeated expensive API calls.
* **Unified Genre Model:** Genre tags are fetched from multiple sources (MusicBrainz, Last.fm) and consolidated into a single, deduped `Genres` column for reporting.
* **Genre Exclusion (Display-Time Only):** The `excluded_genres` list in `config.json` filters junk genres (e.g., "seen live") at display-time only. Raw cached data is preserved unfiltered so exclusion changes take effect without re-fetching.
* **Enrichment Failure Logging:** Failed lookups (empty genres, unrecognized entities, API errors) are logged to `cache/global/enrichment_failures.jsonl` (append-only, capped at 1000 lines). This enables users to identify and improve missing MusicBrainz metadata.

### 3.6 Network Robustness
* **Centralized Resilience:** All network interactions must occur via `api_client.py`.
* **Connection Resilience:** The client must specifically handle `ConnectionResetError` (and Windows Error 10054) by catching the exception, logging a warning, and triggering a thread sleep (`5.0s`) before retrying.
* **Strict Encoding:** All user-supplied parameters must be strictly URL encoded (`urllib.parse.quote`) to prevent malformed requests.
* **Last.fm Desktop Auth:** Session-key-based authentication using Last.fm's Desktop Auth protocol. App-level credentials (API Key + Shared Secret) are stored in `config.json`. Per-user session keys are obtained via a browser-based approval flow (user clicks "Connect" → approves in browser → app calls `auth.getSession`). Session keys are permanent and stored in the user's cache directory. All authenticated requests use MD5 signed parameters per the Last.fm API spec.

### 3.7 Interface Robustness
* **Flexible Contracts (`**kwargs`):** Logic engines (specifically `reporting.py` functions) **MUST** accept `**kwargs`. This acts as a "sink" for unused arguments passed by the `ReportEngine`, preventing `TypeError` when a specific report type (e.g., "Raw Listens") does not utilize a global filter parameter (e.g., `min_listens`).
* **Explicit Error Handling:** Do NOT use `try/except TypeError` to lazily handle signature mismatches. Arguments must be explicitly mapped or safely ignored via `**kwargs`.

---

## 4. Component Architecture (MVC)

### 4.1 The View (Components)
* **`gui_main.py`:** Application entry point, logging setup, component assembly, and event orchestration.
* **`gui_header.py`:** Top bar. User selection, Profile creation, Source selection (API/CSV).
* **`gui_filters.py`:** Middle section. Input validation, Tooltip management, Parameter extraction (`get_values`).
* **`gui_actions.py`:** Bottom bar. Upstream actions (Like, Resolve, Export). Owns the worker threads for these actions.
* **`gui_tableview.py`:** `ttk.Treeview` wrapper. Handles sorting (`mergesort`), regex filtering, and column rendering.
* **`gui_charts.py`:** Native Matplotlib window generation (Entity Trends for Artist/Track/Album, New Music, Genre Treemap, Album Art Matrix).

### 4.2 The Controller (Logic Engines)
* **`report_engine.py`:** Bridges GUI inputs to Data outputs. Handles "No Data" states, orchestration of aggregation + enrichment pipelines.
* **`sync_engine.py`:** Manages the "Get New Listens" background threads, `ProgressWindow` updates, and the Synchronization Barrier.

### 4.3 The Model (Data & Config)
* **`user.py`:** User entity management, file I/O lock (`_io_lock`), cache directory management.
* **`config.py`:** Singleton configuration (`AppConfig`). Centralizes paths, constants, and user-editable settings (e.g., `excluded_genres`).
* **`parsing.py`:** Pure functions for parsing JSON/CSV, normalizing keys (`normalize_sort_key`), and handling messy input data.
* **`enrichment.py`:** Caching layer for metadata. Handles API limits and local JSON caches.

#### Cache Key Hierarchy
When reading or writing to persistent JSON cache files, the system MUST adhere to the following key generation priority to preserve backward compatibility:
1.  **Primary:** Use the UUID (MBID) if it exists and is not null/empty.
2.  **Fallback:** Use the Entity Name (String) *only* if the MBID is strictly unavailable.

---

## 5. File Manifest (v7.0 Modular)

Expect to receive the following files.

| File | Type | Responsibility |
| :--- | :--- | :--- |
| **`gui_main.py`** | **View/Controller** | Main Window, "Report Settings" Logic, and thread orchestration. |
| **`gui_header.py`** | **View** | User/Source Selection UI. |
| **`gui_filters.py`** | **View** | Strictly input widgets for Time, Recency, and Thresholds. (No Enrichment logic). |
| **`gui_actions.py`** | **View/Controller** | Persistent Actions Bar (Like, Resolve, Playlist, Import). Manages button states (`update_state`). |
| **`gui_tableview.py`** | **View** | Treeview & Sort Logic. |
| **`gui_charts.py`** | **View** | Matplotlib Visualization Logic (Embedded implementations). |
| **`gui_user_editor.py`** | **View** | User Creation Dialog. |
| **`report_engine.py`** | **Controller** | Pipeline Orchestration. |
| **`sync_engine.py`** | **Controller** | Sync Threading & Barrier. |
| **`api_client.py`** | **Service** | `requests`-based client for MusicBrainz, ListenBrainz, Last.fm, and Cover Art Archive. |
| **`user.py`** | **Model** | Persistence, File I/O. |
| **`reporting.py`** | **Model** | Pandas Aggregation Logic. |
| **`enrichment.py`** | **Model/Service** | Fetches Genre tags and resolves missing MBIDs using persistent caching. |
| **`parsing.py`** | **Utility** | Data Normalization. |
| **`config.py`** | **Utility** | Singleton Settings. |
| **`likes_sync.py`** | **Controller** | Lightweight Last.fm loves fetcher. Fetches loved tracks via `LastFMClient`, caches to `lastfm_loves.json`. |


---

## 6. Key Data Schemas & Constraints

### 6.1 The Canonical Listens DataFrame
Columns: `listened_at` (datetime64[ns, UTC]), `track_name`, `artist`, `album`, `recording_mbid`, `release_mbid`, `artist_mbid`, `duration_ms` (int64), `_username`.

### 6.2 The Unified "Likes" Schema
* **Column Name:** `Likes`
* **Data Type:** `int64` (Strict)
* **Semantics:**
    * For **Aggregated Reports** (Artist/Album): Represents the count of unique liked tracks associated with that entity.
    * For **Granular Reports** (Track/Raw): Represents a boolean status (1 = Liked, 0 = Not Liked).
* **Constraints:** Must be explicitly cast to `int` before filtering or display to ensure correct sorting.

### 6.2.1 The "Likes Report" Schema
The dedicated "Likes" report uses a distinct schema from the unified `Likes` column:
* **Columns:** `track_name`, `artist`, `album`, `Last.fm Liked` (int), `ListenBrainz Liked` (int), `Both Liked` (int), `recording_mbid` (str).
* **`Last.fm Liked`:** 1 if the track is in the user's Last.fm loved tracks cache, 0 otherwise.
* **`ListenBrainz Liked`:** 1 if the recording MBID is in the user's ListenBrainz feedback (liked) set, 0 otherwise.
* **`Both Liked`:** 1 if both services have the track liked, 0 otherwise. Used as a signature column to detect the Likes report in downstream code (e.g., `gui_tableview.py` uses `"Both Liked" in df.columns` to preserve `recording_mbid` visibility).
* **Name Resolution:** When a liked MBID has no exact match in listening history, the system does a reverse lookup through the resolver cache to find the artist/track name, then falls back to case-insensitive name matching in history.

### 6.3 Technical Constraints
* **Thread Safety:** UI updates from background threads must use `root.after` (via callbacks).
* **Copy-on-Write:** When passing DataFrame slices (e.g., filtered by time) to `enrichment.py`, you MUST call `.copy()` to avoid `SettingWithCopyWarning`.
* **Logging Hooks:** The `setup_logging` function in `gui_main.py` is the only authorized place to configure `sys` exception hooks.
* **UI Layout:** Report configuration (Type, Enrichment Source, Settings) is grouped into a central `LabelFrame` in `gui_main.py`. The `gui_filters.py` module is restricted solely to data filtering (Time/Count).
* **Duplicate Prevention (Sync):** The `SyncManager` must strictly apply "Filter-First" logic. Incoming batches must be filtered against local data **before** being written to disk or counted for the UI.

### 6.4 Global Caches (`cache/global/`)
* **`artist_enrichment.json`**: Caches genre tags for artists.
* **`mbid_resolver_cache.json`**: Caches `(Artist, Track, Album)` → `MBID` resolutions. Critical for "Import Likes" performance.
* **`release_group_map.json`**: Caches `release_mbid` → `release_group_mbid` mappings. Used by both genre enrichment and cover art fallback.
* **`enrichment_failures.jsonl`**: Append-only log of failed lookups (capped at 1000 lines).
* **`cover_art/`**: Cached album cover art thumbnails (JPEG, 250px). Keyed by `release_mbid`.
* **`genres_excluded.json`**: User-defined list of tags to ignore.

---

## 7. Instantiation Trigger

**System:** You have processed the instantiation document.
**Instruction:** Acknowledge receipt of this design context. State that you are ready to proceed as the Lead Developer. **Request the python source files listed in Section 5** to begin the session.