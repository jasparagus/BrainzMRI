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
    # 1. Capture Python Warnings (like SettingWithCopyWarning)
    logging.captureWarnings(True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(config.log_file, mode='w', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
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

        # Initialize Variables for Enrichment (Moved from Filters)
        self.enrichment_mode_var = tk.StringVar(value="None (Data Only, No Genres)")
        self.force_cache_var = tk.BooleanVar(value=False)
        self.deep_query_var = tk.BooleanVar(value=False)

        # 1. Header (User/Source)
        # Pass callback for "Get New Listens" AND "Import CSV"
        self.header = HeaderComponent(root, self.state, self.start_sync_engine, self.on_data_imported)

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

    def on_data_imported(self):
        """Callback when CSV is imported successfully."""
        self.cmb_report.set("Raw Listens")
        self.state.last_mode = "Raw Listens"
        self.status_var.set(f"Imported Data: {self.state.playlist_name}")
        self.btn_generate.config(state="normal")
        # Optional: Auto-run or just let user click Generate
        self.run_report() 

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
        self.cmb_report = ttk.Combobox(frm_type, values=[
            "By Artist", "By Album", "By Track", 
            "Genre Flavor", "Favorite Artist Trend", "New Music By Year", "Raw Listens"
        ], state="readonly", width=18)
        self.cmb_report.current(0)
        self.cmb_report.pack(anchor="w")
        self.cmb_report.bind("<<ComboboxSelected>>", self.on_report_type_changed)

        # --- Column 2: Genre Lookup ---
        frm_enrich = tk.Frame(container)
        frm_enrich.pack(side="left", padx=15, anchor="n")

        tk.Label(frm_enrich, text="Genre Lookup (Enrichment)").pack(anchor="w")
        self.cmb_enrich = ttk.Combobox(frm_enrich, textvariable=self.enrichment_mode_var, values=[
            "None (Data Only, No Genres)", "Cache Only", "Query MusicBrainz", "Query Last.fm", "Query All Sources (Slow)"
        ], state="readonly", width=28)
        self.cmb_enrich.pack(anchor="w")
        Hovertip(self.cmb_enrich, "Select source for Genre metadata.\nAPI lookups can be slow.")

        # Logic to disable checkboxes if None/CacheOnly
        def _update_state(*_):
            mode = self.enrichment_mode_var.get()
            state = "disabled" if (mode.startswith("None") or mode == "Cache Only") else "normal"
            self.chk_force.config(state=state)
            self.chk_deep.config(state=state)
            if state == "disabled":
                self.force_cache_var.set(False)
                self.deep_query_var.set(False)
        self.enrichment_mode_var.trace_add("write", _update_state)

        # --- Column 3: Checkboxes (Stacked) ---
        frm_checks = tk.Frame(container)
        frm_checks.pack(side="left", padx=15, anchor="n")

        self.chk_force = tk.Checkbutton(frm_checks, text="Force Cache Update", variable=self.force_cache_var)
        self.chk_force.pack(anchor="w")
        Hovertip(self.chk_force, "Force query API even if data exists in cache.")

        self.chk_deep = tk.Checkbutton(frm_checks, text="Deep Query (Slow)", variable=self.deep_query_var)
        self.chk_deep.pack(anchor="w")
        Hovertip(self.chk_deep, "Fetch metadata for Albums/Tracks (Default is Artists only).")
        
        _update_state() # Init state

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
    def start_sync_engine(self):
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
                if barrier.get("likes_failed"): msg += "\nWARNING: Likes Sync Failed."
                else: msg += f"\nSynced {barrier['likes_count']} likes."
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
        if self.processing or (not self.state.user and not self.state.playlist_df): return
        self.processing = True
        self.btn_generate.config(state="disabled")

        try:
            # 1. Get Params from Component
            params = self.filters.get_values()
            
            # 2. Add Context
            params["mode"] = self.cmb_report.get()
            params["liked_mbids"] = self.state.user.get_liked_mbids()
            
            # Determine Enrichment
            enrich_str = self.enrichment_mode_var.get()
            params["do_enrich"] = not enrich_str.startswith("None")
            params["enrichment_mode"] = enrich_str
            params["force_cache_update"] = self.force_cache_var.get()
            params["deep_query"] = self.deep_query_var.get()
            
            self.state.last_params = params.copy()

            # 3. Select Data
            if self.state.playlist_df is not None:
                base_df = self.state.playlist_df.copy()
            else:
                base_df = self.state.user.get_listens().copy()
            
            if "_username" not in base_df.columns:
                base_df["_username"] = self.state.user.username

            # 4. Launch Thread
            win = ProgressWindow(self.root, f"Generating {params['mode']}...")
            
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
                        win.destroy() if win.winfo_exists() else None,
                        messagebox.showerror("Error", err_msg),
                        self._reset_ui()
                    ])

            threading.Thread(target=worker, daemon=True).start()

        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            self._reset_ui()

    def _on_report_done(self, result, meta, key, enriched, status, mode, win):
        if win.winfo_exists(): win.destroy()
        self._reset_ui()

        # Update State
        self.state.last_report_df = result
        self.state.last_meta = meta
        self.state.last_mode = mode
        self.state.last_report_type_key = key
        self.state.last_enriched = enriched
        self.state.original_df = result.copy()
        self.state.filtered_df = result.copy()

        # Update UI
        self.table_view.show_table(result)
        self.status_var.set(status)

        # Toggle Graph
        if mode in ["Favorite Artist Trend", "New Music By Year", "Genre Flavor"]:
            self.btn_graph.config(state="normal", bg="#EF5350", fg="white")
        else:
            self.btn_graph.config(state="disabled", bg="SystemButtonFace", fg="black")

        # Toggle Actions Panel
        has_tracks = "track_name" in result.columns
        has_mbids = False
        if "recording_mbid" in result.columns:
            has_mbids = result["recording_mbid"].notna().any()
        
        has_missing = False
        if has_tracks:
            if "recording_mbid" not in result.columns: has_missing = True
            else: has_missing = result["recording_mbid"].isna().any()

        self.actions.update_state(
            has_mbids=has_mbids,
            has_missing=has_missing
        )

    def _reset_ui(self):
        self.processing = False
        self.btn_generate.config(state="normal")

    def on_data_updated(self, new_df, resolved_count, failed_count):
        """Callback from ActionComponent when data is resolved."""
        self.table_view.show_table(new_df)
        self.status_var.set(f"Resolved {resolved_count} items ({failed_count} failed).")
        # Refresh visibility of buttons
        self._on_report_done(new_df, self.state.last_meta, self.state.last_report_type_key, 
                             True, self.status_var.get(), self.state.last_mode, 
                             tk.Toplevel()) # Dummy win to satisfy sig

    def save_report(self):
        if self.state.last_report_df is None: return
        try:
            path = reporting.save_report(self.state.last_report_df, self.state.user, self.state.last_meta)
            open_file_default(path)
            self.status_var.set(f"Saved to {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def show_graph(self):
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

if __name__ == "__main__":
    root = tk.Tk()
    setup_logging(root)
    app = BrainzMRIGUI(root)
    root.mainloop()