# Project Instantiation Document: BrainzMRI
**Version:** 7.3 (Cross-Platform Sync & UI Refactor)
**Date:** 2026-01-30

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
    * Use `logging` module only. `print()` is forbidden.
    * Must hook `sys.excepthook`, `sys.unraisablehook`, and `root.report_callback_exception` to ensure GUI crashes are captured in `brainzmri.log`.
    * Must enable `logging.captureWarnings(True)` to catch Pandas warnings (e.g., `SettingWithCopyWarning`).
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

### 3.3 Observability & User Feedback
* **Dual-Channel Progress UI:** The application uses a **"Primary + Secondary"** observability model. The modal progress window must support a secondary status label to report on background tasks (e.g., "Syncing Likes...") independently of the main progress bar.
* **Detailed Pipeline Stats:** Reporting functions must return granular statistics (Cache Hits, Fetches, Empties, Fallbacks) which are bubbled up to the status bar.
* **Hovertip Ubiquity:** Every interactive UI element (buttons, inputs, checkboxes) must utilize `Hovertip` to provide context-sensitive help.

### 3.4 Data Integrity & Resilience
* **Empty Data Protocol (The Guard Clause):** The `ReportEngine` **MUST** check `if df.empty` at the very start of generation. It must return a valid "No Data" response immediately.
* **Just-In-Time Type Safety:** `reporting.py` must convert columns to numeric types `pd.to_numeric(..., errors='coerce').fillna(0)` *immediately before* calculation.
* **Ingestion Sanitization (The Anti-NaN Rule):** When importing data (CSV or JSON), all text-based identifiers (`artist`, `album`, `track_name`) **MUST** be explicitly cast to string and have `NaN`/None replaced with `""` (empty string). This defaults must happen at the *Ingestion Boundary* (`parsing.py`), not deep in the reporting logic. This prevents "Hidden Float" crashes during merging.
* **Transactional Ingestion:**
    * **Stateful (Listens):** "Backwards Crawl" with Intermediate Caching.
    * **Stateless (Likes):** Atomic Replacement.

### 3.8 Report Mode Decoupling
* **Strict Data Isolation:** Analytical reports ("Top Artists", "Genre Flavor", etc.) **MUST ONLY** operate on the loaded User History. They must never silently fall back to an imported CSV.
* **Dedicated CSV Mode:** Imported CSVs are treated as a transient "Playlist Review" state. They are accessible **ONLY** via the dedicated "Imported CSV" report mode. This prevents cross-contamination of metrics (e.g., your "Top Artists of 2024" should not include tracks from a CSV you just imported to check formatting).
* **UI State Management:** The `gui_main.py` controller must dynamically update the available options in the Report Dropdown based on the current context (e.g., showing/hiding "Imported CSV" option).

### 3.5 Metadata & Enrichment Strategy
* **The "Release Group Hop":** Resolve Album genres via `release-group`, never `release`.
* **Enrichment Hierarchy:** The system MUST adhere to this lookup priority:
    1.  **MBID Lookup:** Precision lookup using MusicBrainz IDs.
    2.  **Name-Based Search (Fallback):** If MBIDs are missing, fallback to Lucene-based search.
    3.  **Negative Caching:** Failed lookups must be cached to prevent repeated expensive API calls.
* **Unified Genre Model:** Genre tags are fetched from multiple sources (MusicBrainz, Last.fm) and consolidated into a single, deduped `Genres` column for reporting.

### 3.6 Network Robustness
* **Centralized Resilience:** All network interactions must occur via `api_client.py`.
* **Connection Resilience:** The client must specifically handle `ConnectionResetError` (and Windows Error 10054) by catching the exception, logging a warning, and triggering a thread sleep (`5.0s`) before retrying.
* **Strict Encoding:** All user-supplied parameters must be strictly URL encoded (`urllib.parse.quote`) to prevent malformed requests.

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
* **`gui_charts.py`:** Native Matplotlib window generation.

### 4.2 The Controller (Logic Engines)
* **`report_engine.py`:** Bridges GUI inputs to Data outputs. Handles "No Data" states, orchestration of aggregation + enrichment pipelines.
* **`sync_engine.py`:** Manages the "Get New Listens" background threads, `ProgressWindow` updates, and the Synchronization Barrier.

### 4.3 The Model (Data & Config)
* **`user.py`:** User entity management, file I/O lock (`_io_lock`), cache directory management.
* **`config.py`:** Singleton configuration (`AppConfig`). Centralizes paths and constants.
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
| **`gui_charts.py`** | **View** | Matplotlib Visualizations. |
| **`gui_user_editor.py`** | **View** | User Creation Dialog. |
| **`report_engine.py`** | **Controller** | Pipeline Orchestration. |
| **`sync_engine.py`** | **Controller** | Sync Threading & Barrier. |
| **`api_client.py`** | **Service** | `requests`-based client for MusicBrainz, ListenBrainz, and Last.fm. |
| **`user.py`** | **Model** | Persistence, File I/O. |
| **`reporting.py`** | **Model** | Pandas Aggregation Logic. |
| **`enrichment.py`** | **Model/Service** | Fetches Genre tags and resolves missing MBIDs using persistent caching. |
| **`parsing.py`** | **Utility** | Data Normalization. |
| **`config.py`** | **Utility** | Singleton Settings. |
| **`sync_engine.py`** | **Controller** | Orchestrates background synchronization (Filter-First logic) and Progress UI. |
| **`likes_sync.py`** | **Controller** | Manages cross-platform logic: Fetch Last.fm Likes  Resolve MBIDs  Diff  User Confirm  Push LB. |


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

### 6.3 Technical Constraints
* **Thread Safety:** UI updates from background threads must use `root.after` (via callbacks).
* **Copy-on-Write:** When passing DataFrame slices (e.g., filtered by time) to `enrichment.py`, you MUST call `.copy()` to avoid `SettingWithCopyWarning`.
* **Logging Hooks:** The `setup_logging` function in `gui_main.py` is the only authorized place to configure `sys` exception hooks.
* **UI Layout:** Report configuration (Type, Enrichment Source, Settings) is grouped into a central `LabelFrame` in `gui_main.py`. The `gui_filters.py` module is restricted solely to data filtering (Time/Count).
* **Duplicate Prevention (Sync):** The `SyncManager` must strictly apply "Filter-First" logic. Incoming batches must be filtered against local data **before** being written to disk or counted for the UI.

### 6.4 Global Caches (`cache/global/`)
* **`artist_enrichment.json`**: Caches genre tags for artists.
* **`mbid_resolver_cache.json`**: **[NEW]** Caches `(Artist, Track, Album)` $\to$ `MBID` resolutions. Critical for "Import Likes" performance.
* **`genres_excluded.json`**: User-defined list of tags to ignore.

---

## 7. Instantiation Trigger

**System:** You have processed the instantiation document.
**Instruction:** Acknowledge receipt of this design context. State that you are ready to proceed as the Lead Developer. **Request the python source files listed in Section 5** to begin the session.