"""
gui_main.py (v7.2)
Main entry point for BrainzMRI.
Assemble UI components (Header, Filters, Table, Actions).
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import logging
import sys
import traceback
import time
import os
import subprocess
import gc # Memory management for crash prevention

from idlelib.tooltip import Hovertip

# Core Logic
from config import config
from user import User, get_cached_usernames
from report_engine import ReportEngine
from sync_engine import SyncManager, ProgressWindow
from api_client import ListenBrainzClient

# UI Components
from gui_header import HeaderComponent
from gui_filters import FilterComponent
from gui_actions import ActionComponent
from gui_tableview import ReportTableView
from gui_charts import show_artist_trend_chart, show_new_music_stacked_bar, show_genre_flavor_treemap
import reporting

# ======================================================================
# Logging
# ======================================================================
def setup_logging(root=None):
    """
    Configure logging to file and console.
    Hooks into Tkinter's exception handler if root is provided.
    """
    # 1. Determine Log Level
    # Normalize to Upper Case to match user's map keys
    level_str = config.log_level.upper()
    
    # 0. Level "NONE" -> Disable Logging
    if level_str == "NONE":
        logging.getLogger().handlers = []
        return


    level_map = {
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
    }
    target_level = level_map.get(level_str, logging.INFO)

    # 2. Configure Logging
    # Wrap in try/except to handle "File in Use" crashes
    try:
        logging.basicConfig(
            level=target_level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                 logging.FileHandler(config.log_file, mode='w', encoding='utf-8'),
                 logging.StreamHandler(sys.stdout)
            ],
            force=True
        )
    except PermissionError:
        # Fallback to Console Only if file is locked
        logging.basicConfig(
            level=target_level,
            format="%(asctime)s [%(levelname)s] [FILE LOCKED] %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
            force=True
        )
        logging.warning("Could not write to brainzmri.log (File Locked). Logging to console only.")
    except Exception as e:
        # Total fallback
        print(f"CRITICAL: Logging setup failed: {e}")

    # 3. Capture Python Warnings
    logging.captureWarnings(True)
    
    # 2. Hook standard uncaught exceptions (Main Thread)
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    
    sys.excepthook = handle_exception

    # 3. Hook unraisable exceptions (e.g., in __del__ or threads)
    def unraisable_handler(args):
        # Prevent logging spam during shutdown
        if args.exc_type == RuntimeError and "main thread is not in main loop" in str(args.exc_value):
            return 
        logging.error("Unraisable exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.unraisablehook = unraisable_handler

    # 4. Hook Tkinter callback exceptions
    if root:
        def tk_handler(exc, val, tb):
            logging.error("Exception in Tkinter callback", exc_info=(exc, val, tb))
            traceback.print_exception(exc, val, tb)
            
        root.report_callback_exception = tk_handler

    logging.info("=== BrainzMRI v7.0 Session Started ===")

def open_file_default(path: str) -> None:
    if sys.platform.startswith("win"): os.startfile(path)
    elif sys.platform == "darwin": subprocess.Popen(["open", path])
    else: subprocess.Popen(["xdg-open", path])

# ======================================================================
# Application State
# ======================================================================
class GUIState:
    def __init__(self):
        self.user = None
        self.playlist_df = None
        self.playlist_name = None
        self.last_report_df = None
        self.last_meta = None
        self.last_mode = None
        self.last_report_type_key = None
        self.last_enriched = False
        self.last_params = {}
        self.original_df = None
        self.filtered_df = None

# ======================================================================
# Main Window
# ======================================================================
class BrainzMRIGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BrainzMRI - ListenBrainz Metadata Review Instrument")
        self.root.geometry("1000x900")
        
        self.state = GUIState()
        self.report_engine = ReportEngine()
        self.processing = False # Simple guard



        # Define Report Modes
        self.REPORT_MODES_STANDARD = ["Top Artists", "Top Albums", "Top Tracks", "Genre Flavor", "Genre Flavor Treemap", "Favorite Artist Trend", "New Music by Year", "Raw Listens"]
        self.REPORT_MODES_CSV = ["Imported Playlist"]

        # Initialize Variables for Enrichment (Moved from Filters)
        self.enrichment_mode_var = tk.StringVar(value="None (Data Only, No Genres)")
        self.force_cache_var = tk.BooleanVar(value=False)
        self.deep_query_var = tk.BooleanVar(value=False)

        # 1. Header (User/Source)
        # Pass callback for "Get New Listens" AND "Import CSV" AND "Import Last.fm"
        self.header = HeaderComponent(
            root, self.state, 
            self.start_sync_engine, 
            on_import_callback=self.on_data_imported,
            on_cleared_callback=self.on_data_cleared,
            on_import_lastfm_callback=self.trigger_import_lastfm,
            lock_cb=self.lock_interface,
            unlock_cb=self.unlock_interface
        )

        # 2. Filters (Stripped of enrichment)
        self.filters = FilterComponent(root, on_enter_key=self.run_report)

        # 3. Report Settings Group (New Layout)
        self._build_report_settings_frame()

        # 4. Table
        self.frm_table = tk.Frame(root)
        self.frm_table.pack(fill="both", expand=True)
        self.table_view = ReportTableView(root, self.frm_table, self.state)

        # 5. Actions (Now always visible)
        self.actions = ActionComponent(root, self.state, self.table_view, self.on_data_updated)

        # 6. Status Bar
        self.status_var = tk.StringVar(value="Ready.")
        self.status_bar = tk.Label(root, textvariable=self.status_var, bd=1, relief="sunken", anchor="center")
        self.status_bar.pack(fill="x", side="bottom")

        # Auto-load last user
        if config.last_user:
            self.header.user_var.set(config.last_user)
            self.header.load_user(config.last_user)

    # ------------------------------------------------------------------
    # Dynamic Mode Logic
    # ------------------------------------------------------------------
    def _update_report_modes(self):
        """Update report dropdown based on available data."""
        modes = self.REPORT_MODES_STANDARD.copy()
        
        if self.state.playlist_df is not None:
             modes = self.REPORT_MODES_CSV + modes
             
        self.cmb_report["values"] = modes
        
        # Auto-select if current is invalid
        current = self.cmb_report.get()
        if current not in modes:
             self.cmb_report['values'] = self.REPORT_MODES_CSV
             self.cmb_report.set("Imported Playlist")
        else:
            self.cmb_report['values'] = self.REPORT_MODES_STANDARD
            self.cmb_report.set(modes[0])

    def on_data_imported(self):
        """Callback when CSV is imported successfully."""
        self._update_report_modes()
        self.cmb_report.set("Imported Playlist")
        self.state.last_mode = "Imported Playlist"
        self.status_var.set(f"Imported Data: {self.state.playlist_name}")
        logging.info(f"TRACE: Main.on_data_imported: {self.state.playlist_name}")
        self.btn_generate.config(state="normal")
        
        # Validate UI state immediately (Force Cache needs enabling)
        self._update_ui_state()
        logging.info(f"TRACE: Main.on_data_imported: _update_ui_state")
        
        # Auto-run: Clear the processing flag so run_report passes its guard.
        # import_csv already locked the interface; run_report will re-lock (idempotent)
        # and _on_report_done will properly unlock when finished.
        self.processing = False
        logging.info(f"TRACE: Main.on_data_imported: calling run_report")
        self.run_report()
        logging.info(f"TRACE: Main.on_data_imported: run_report returned")

    def on_data_cleared(self):
        """Callback when CSV is closed (called by header via new callback)."""
        self._update_report_modes()
        self.cmb_report.set("Raw Listens")
        self._update_ui_state()

    def _build_report_settings_frame(self):
        """Redesigned 'Report Settings' Group."""
        frm_settings = tk.LabelFrame(self.root, text="Report Settings", padx=10, pady=5)
        frm_settings.pack(pady=5, fill="x", padx=10)

        # FIX: Container to center the content
        container = tk.Frame(frm_settings)
        container.pack(expand=True, anchor="center")

        # --- Column 1: Report Type ---
        frm_type = tk.Frame(container)
        frm_type.pack(side="left", padx=15, anchor="n")
        
        tk.Label(frm_type, text="Report Type").pack(anchor="w")
        self.cmb_report = ttk.Combobox(frm_type, values=self.REPORT_MODES_STANDARD, state="readonly", width=18)
        self.cmb_report.current(0)
        self.cmb_report.pack(anchor="w")
        self.cmb_report.bind("<<ComboboxSelected>>", lambda e: self._update_ui_state())

        # --- Column 2: Genre Lookup ---
        frm_enrich = tk.Frame(container)
        frm_enrich.pack(side="left", padx=15, anchor="n")

        tk.Label(frm_enrich, text="Genre Lookup (Enrichment)").pack(anchor="w")
        self.cmb_enrich = ttk.Combobox(frm_enrich, textvariable=self.enrichment_mode_var, values=[
            "None (Data Only, No Genres)", "Cache Only", "Query MusicBrainz", "Query Last.fm", "Query All Sources (Slow)"
        ], state="readonly", width=28)
        self.cmb_enrich.pack(anchor="w")
        Hovertip(self.cmb_enrich, "Select source for Genre metadata.\\nAPI lookups can be slow.")
        self.cmb_enrich.bind("<<ComboboxSelected>>", lambda e: self._update_ui_state())

        # --- Column 3: Checkboxes (Stacked) ---
        frm_checks = tk.Frame(container)
        frm_checks.pack(side="left", padx=15, anchor="n")

        self.chk_force = tk.Checkbutton(frm_checks, text="Force Cache Update", variable=self.force_cache_var)
        self.chk_force.pack(anchor="w")
        Hovertip(self.chk_force, "Force query API even if data exists in cache.")

        self.chk_deep = tk.Checkbutton(frm_checks, text="Deep Query (Slow)", variable=self.deep_query_var)
        self.chk_deep.pack(anchor="w")
        Hovertip(self.chk_deep, "Fetch metadata for Albums/Tracks (Default is Artists only).")
        
        self._update_ui_state() # Init state

        # --- Column 4: Buttons (Side-by-side) ---
        frm_btns = tk.Frame(container)
        frm_btns.pack(side="left", padx=20, fill="y")
        # Center vertically in the frame
        frm_btns_inner = tk.Frame(frm_btns)
        frm_btns_inner.pack(anchor="center", pady=10)

        self.btn_generate = tk.Button(frm_btns_inner, text="Generate Report", bg="#4CAF50", fg="white", command=self.run_report, height=2)
        self.btn_generate.pack(side="left", padx=5)

        self.btn_graph = tk.Button(frm_btns_inner, text="Show Graph", state="disabled", command=self.show_graph, height=2)
        self.btn_graph.pack(side="left", padx=5)

        tk.Button(frm_btns_inner, text="Save Report", bg="#2196F3", fg="white", command=self.save_report, height=2).pack(side="left", padx=5)

    def on_report_type_changed(self, event):
        # Auto-set Enrichment to Cache Only for Genre Flavor
        if self.cmb_report.get() == "Genre Flavor":
            if self.filters.enrichment_mode_var.get().startswith("None"):
                self.filters.enrichment_mode_var.set("Cache Only")

    # ------------------------------------------------------------------
    # Core Actions
    # ------------------------------------------------------------------
    def trigger_import_lastfm(self):
        """Proxy to trigger Last.fm import from Header."""
        if hasattr(self, 'actions') and self.actions:
            self.actions.action_import_likes()

    def start_sync_engine(self):
        logging.info("User Action: Clicked 'Get New Listens'")
        if not self.state.user: return
        
        self.header.btn_get_listens.config(state="disabled")
        
        # Determine start time (Resume vs Fresh)
        local_ts = self.state.user.get_latest_listen_timestamp()
        inter_df = self.state.user.load_intermediate_listens()
        
        start_ts = int(time.time())
        if not inter_df.empty:
            try: start_ts = int(inter_df["listened_at"].min().timestamp())
            except: pass

        win = ProgressWindow(self.root, "Fetching New Listens...")
        
        # Define callbacks
        def on_update_primary(c, m): win.update_progress(0, 0, f"{m} (Total: {c})")
        def on_update_secondary(m): win.update_secondary(m)
        def on_error(m): messagebox.showerror("Sync Error", m)
        def on_confirm(m, cb): 
            res = messagebox.askyesno("Confirm", m)
            cb(res)
        
        def on_complete(barrier):
            if win.winfo_exists(): win.destroy()
            self.header.btn_get_listens.config(state="normal")
            
            if barrier["gap_closed"]:
                self.state.user.merge_intermediate_cache()
                msg = f"Imported {barrier['listens_count']} new listens."
                if barrier.get("likes_failed"): msg += "\\nWARNING: Likes Sync Failed."
                else: msg += f"\\nSynced {barrier['likes_count']} likes."
                messagebox.showinfo("Success", msg)
                if self.cmb_report.get() == "Raw Listens": self.run_report()
            else:
                messagebox.showwarning("Partial", f"Stopped. Gap not closed. ({barrier['listens_count']} fetched)")

        # Create manager
        client = ListenBrainzClient(self.state.user.listenbrainz_token)
        callbacks = {
            "update_primary": on_update_primary,
            "update_secondary": on_update_secondary,
            "on_error": on_error,
            "request_confirmation": on_confirm,
            "on_complete": on_complete
        }
        
        manager = SyncManager(self.state.user, client, self.root.after, callbacks)
        win.btn_cancel.config(command=lambda: [win.cancel(), manager.cancel()])
        
        manager.start(start_ts, local_ts)

    def run_report(self):
        logging.info("User Action: Clicked 'Generate Report' or Auto-run of 'Generate Report'")
        if self.processing:
            logging.info("TRACE: Main.run_report: returning early due to processing")
            return
        if not self.state.user and not self.state.playlist_df: 
            logging.info("TRACE: Main.run_report: returning early due to no user/playlist")
            # Note that this may also be the reason for the perceived "crash". Can this kill the main GUI?
            return
        logging.info("TRACE: Main.run_report: starting, locking interface and getting params")
        # 0. Strict Locking
        self.lock_interface()

        try:
            # 1. Get Params from Component
            params = self.filters.get_values()
            
            # 2. Add Context
            selected_mode = self.cmb_report.get()
            
            # Alias "Imported Playlist" to "Raw Listens" logic
            if selected_mode == "Imported Playlist":
                params["mode"] = "Raw Listens"
            else:
                params["mode"] = selected_mode

            # Handle Likes context (User might be None if just reviewing CSV)
            if self.state.user:
                params["liked_mbids"] = self.state.user.get_liked_mbids()
            else:
                params["liked_mbids"] = set()
            
            # Determine Enrichment
            enrich_str = self.enrichment_mode_var.get()
            force_update = self.force_cache_var.get()
            
            # Logic: If Force Update is requested, we MUST query API
            if force_update and (enrich_str.startswith("None") or enrich_str == "Cache Only (Fast)"):
                enrich_str = "Query MusicBrainz"
                logging.info(f"Auto-switching enrichment to '{enrich_str}' because Force Update is enabled.")

            params["do_enrich"] = not enrich_str.startswith("None")
            params["enrichment_mode"] = enrich_str
            params["force_cache_update"] = force_update
            params["deep_query"] = self.deep_query_var.get()
            
            self.state.last_params = params.copy()

            # 3. Select Data (Decoupled: Standard Reports ALWAYS use User History)
            if selected_mode == "Imported Playlist":
                 if self.state.playlist_df is None:
                     raise ValueError("No Playlist loaded.")
                 base_df = self.state.playlist_df.copy()
            else:
                 if not self.state.user:
                     raise ValueError("No User loaded. Please load a user to view history reports.")
                 base_df = self.state.user.get_listens().copy()
            
            if self.state.user and "_username" not in base_df.columns:
                base_df["_username"] = self.state.user.username

            # 4. Launch Thread
            logging.info(f"TRACE: Main.run_report: launching thread with params: {params['mode']}")
            win = ProgressWindow(self.root, f"Generating {params['mode']}...")
            logging.info(f"TRACE: Main.run_report: created progress window")

            def worker():
                try:
                    # FIX: Use self.root.after (permanent) instead of win.after (transient)
                    # This prevents TclError if 'win' is destroyed before callback runs.
                    def cb(c, t, m): 
                        self.root.after(0, lambda: win.update_progress(c, t, m))
                    
                    res, meta, key, enriched, status = self.report_engine.generate_report(
                        base_df,
                        **params,
                        progress_callback=cb,
                        is_cancelled=lambda: win.cancelled
                    )
                    
                    self.root.after(0, lambda: self._on_report_done(res, meta, key, enriched, status, params['mode'], win))
                
                except Exception as e:
                    # Capture exception string immediately
                    err_msg = str(e)
                    logging.error(f"Report generation failed: {e}", exc_info=True)
                    self.root.after(0, lambda: [
                        messagebox.showerror("Error", err_msg),
                        self._on_report_done(pd.DataFrame(), {}, "", False, "Failed.", params['mode'], win) # Unified Exit
                    ])

            threading.Thread(target=worker, daemon=True).start()

        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            self.unlock_interface() # Early unlock on error

    def _on_report_done(self, result, meta, key, enriched, status, mode, win=None):
        try:
            logging.info("TRACE: _on_report_done started")
            if win and win.winfo_exists(): win.destroy()
            logging.info("TRACE: win destroyed")
            
            # self._reset_ui() -> MOVED TO END
            logging.info("TRACE: UI reset skipped (Deferring unlock)")

            # Update State
            self.state.last_report_df = result
            self.state.last_meta = meta
            self.state.last_mode = mode
            self.state.last_report_type_key = key
            self.state.last_enriched = enriched
            self.state.original_df = result.copy()
            self.state.filtered_df = result.copy()
            logging.info(f"TRACE: State updated. Result Rows: {len(result)}")

            # CLEANUP: Manually clear previous state and run GC to prevent Tcl access violations
            # Force Tcl to process pending destruction events before we allocate new massive objects
            # CLEANUP: Manually clear previous state and run GC
            # logging.info("TRACE: Pre-update_idletasks")
            # self.root.update_idletasks() -> REMOVED: Cause of crashes during rapid updates
            # logging.info("TRACE: Post-update_idletasks / Pre-gc.collect")
            
            # Log Data Types to check for anomalies (Requested to keep debug logs)
            # logging.info(f"TRACE: Result Data Types:\n{result.dtypes}")
            
            gc.collect()
            # logging.info("TRACE: Post-gc.collect")

            # This is the suspected crash definition
            logging.info("TRACE: Calling standard show_table...")
            try:
                self.table_view.show_table(result)
                logging.info("TRACE: show_table returned successfully")
            except Exception as e:
                logging.error(f"CRASH during show_table execution: {e}", exc_info=True)
                # Re-raise to ensure visibility if needed, or let faulthandler catch it
                raise
            
            self.status_var.set(status)
            logging.info("TRACE: status_var set")

            # Toggle Graph
            if mode in ["Favorite Artist Trend", "New Music By Year", "Genre Flavor"]:
                self.btn_graph.config(state="normal", bg="#EF5350", fg="white")
            else:
                self.btn_graph.config(state="disabled", bg="SystemButtonFace", fg="black")
            logging.info("TRACE: Graph btn toggled")

            # Toggle Actions Panel
            has_tracks = "track_name" in result.columns
            has_mbids = False
            if "recording_mbid" in result.columns:
                has_mbids = result["recording_mbid"].notna().any()
            
            has_missing = False
            if has_tracks:
                if "recording_mbid" not in result.columns: has_missing = True
                else: has_missing = result["recording_mbid"].isna().any()

            logging.info(f"TRACE: Calling actions.update_state with mbids={has_mbids}, missing={has_missing}")
            self.actions.update_state(
                has_mbids=has_mbids,
                has_missing=has_missing
            )
            
            logging.info("TRACE: _on_report_done completed successfully")
            
        except Exception as e:
            logging.error(f"UI Update failed: {e}", exc_info=True)
            messagebox.showerror("UI Error", f"Failed to update display: {e}")
        
        finally:
            self.unlock_interface()


    def _update_ui_state(self):
        """Enable/Disable checkboxes based on selection."""
        # Check if cmb_report exists first (guards against early init calls)
        if not hasattr(self, 'cmb_report') or not hasattr(self, 'chk_force'): return

        mode = self.cmb_report.get()
        enrich = self.enrichment_mode_var.get()
        
        # Force Cache: Enabled if ANY Enrichment is selected (to allow upgrading Cache Only -> Query)
        # OR if using Imported Playlist
        can_enrich = not enrich.startswith("None")
        is_playlist = (mode == "Imported Playlist")
        
        if can_enrich or is_playlist:
            self.chk_force.config(state="normal")
        else:
            self.chk_force.config(state="disabled")
            self.force_cache_var.set(False)

        # Deep Query: Only meaningful if enriching and NOT None
        if enrich.startswith("None") or enrich == "Cache Only (Fast)":
             self.chk_deep.config(state="disabled")
             self.deep_query_var.set(False)
        else:
             self.chk_deep.config(state="normal")

    def _reset_ui(self):
        self.processing = False
        self.btn_generate.config(state="normal")

    def on_data_updated(self, new_df, resolved_count, failed_count):
        """Callback from ActionComponent when data is resolved."""
        self.table_view.show_table(new_df)
        self.status_var.set(f"Resolved {resolved_count} items ({failed_count} failed).")
        # Refresh visibility of buttons (win=None, no progress window to close)
        self._on_report_done(new_df, self.state.last_meta, self.state.last_report_type_key, 
                             True, self.status_var.get(), self.state.last_mode)

    def save_report(self):
        logging.info("User Action: Clicked 'Save Report'")
        if self.state.last_report_df is None: return
        try:
            path = reporting.save_report(self.state.last_report_df, self.state.user, self.state.last_meta)
            open_file_default(path)
            self.status_var.set(f"Saved to {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def show_graph(self):
        logging.info("User Action: Clicked 'Show Graph'")
        mode = self.state.last_mode
        if mode == "Favorite Artist Trend":
            # Recalculate trend data
            df_src = self.state.playlist_df if self.state.playlist_df is not None else self.state.user.get_listens()
            # Apply time filter again using correct keys
            p = self.state.last_params
            if p.get("time_start_days", 0) > 0 or p.get("time_end_days", 0) > 0:
                df_src = reporting.filter_by_days(df_src, "listened_at", p["time_start_days"], p["time_end_days"])
            
            data = reporting.prepare_artist_trend_chart_data(df_src, topn=p.get("topn", 20))
            if not data.empty: show_artist_trend_chart(data)
            
        elif mode == "New Music By Year":
            show_new_music_stacked_bar(self.state.last_report_df)
            
        elif mode == "Genre Flavor":
            show_genre_flavor_treemap(self.state.last_report_df)

    def lock_interface(self):
        """Disable all interactive elements to prevent race conditions."""
        self.processing = True
        self.status_var.set("Busy...")
        self.root.config(cursor="watch")
        
        # Header
        self.header.lock()
        
        # Filters (Inputs) & Settings
        for child in self.root.winfo_children():
             if isinstance(child, (tk.Button, ttk.Combobox, tk.Checkbutton, tk.Entry)):
                 try: child.config(state="disabled")
                 except: pass
        
        self.btn_generate.config(state="disabled")
        self.btn_graph.config(state="disabled")
        self.chk_force.config(state="disabled")
        self.chk_deep.config(state="disabled")
        self.cmb_report.config(state="disabled")
        self.cmb_enrich.config(state="disabled")
        
        # Actions
        if self.actions: self.actions.frame.pack_forget() # Hide or Disable? Disable is better but hiding is safer for now.
        # Actually action frame has internal buttons. Let's disable them.
        if self.actions:
            for widget in self.actions.frame.winfo_children():
                try: widget.config(state="disabled")
                except: pass

    def unlock_interface(self):
        """Re-enable interactive elements based on current state."""
        self.processing = False
        self.root.config(cursor="")
        
        # Header
        self.header.unlock()

        # Settings
        self.cmb_report.config(state="readonly")
        self.cmb_enrich.config(state="readonly")
        self.btn_generate.config(state="normal")
        
        # Restore Logic
        self._update_ui_state() # Will parse logic to enable/disable specific checks
        
        # Graph Button
        if self.btn_graph["text"] == "Show Graph" and self.state.last_report_df is not None:
             # Logic from on_report_done to decide if enabled
             mode = self.state.last_mode
             if mode in ["Favorite Artist Trend", "New Music By Year", "Genre Flavor"]:
                self.btn_graph.config(state="normal")
        
        # Actions
        if self.actions:
             # Restore frame and buttons
             self.actions.frame.pack(fill="x", side="bottom", padx=5, pady=5)
             for widget in self.actions.frame.winfo_children():
                 try: widget.config(state="normal")
                 except: pass
            
             # Re-eval action logic
             self.actions.update_state(
                 has_mbids=(self.state.last_report_df is not None and "recording_mbid" in self.state.last_report_df.columns),
                 has_missing=(self.state.last_report_df is not None and "recording_mbid" in self.state.last_report_df.columns and self.state.last_report_df["recording_mbid"].isna().any())
             )
            
        logging.info("TRACE: Interface Unlocked")

if __name__ == "__main__":
    root = tk.Tk()
    setup_logging(root)
    app = BrainzMRIGUI(root)
    root.mainloop()