"""
gui_main.py
Tkinter GUI for BrainzMRI, using reporting, enrichment, and user modules.
"""

import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, simpledialog
from datetime import datetime, timedelta, timezone
from idlelib.tooltip import Hovertip
import os
import subprocess
import sys
import threading
import time
import logging
import pandas as pd

import reporting
import enrichment
import gui_charts
import parsing
from user import (
    User,
    get_cached_usernames,
)
from report_engine import ReportEngine
from gui_user_editor import UserEditorWindow
from gui_tableview import ReportTableView
from api_client import ListenBrainzClient

from sync_engine import SyncManager, ProgressWindow
from config import config  # REFACTORED: Import global config


# ======================================================================
# Logging & Utility
# ======================================================================

def setup_logging():
    """
    Configure file-based logging and redirect stdout/stderr to capture
    all console output (including api_client prints) to a file.
    """
    # REFACTORED: Use path from config
    log_file = config.log_file
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='w', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception
    logging.info("=== BrainzMRI Session Started ===")


def open_file_default(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ======================================================================
# GUI Core Classes
# ======================================================================

class GUIState:
    def __init__(self) -> None:
        self.user: User | None = None
        self.playlist_df = None
        self.playlist_name: str | None = None
        self.last_report_df = None
        self.last_meta = None
        self.last_mode: str | None = None
        self.last_report_type_key: str | None = None
        self.last_enriched: bool = False
        self.last_params: dict = {}
        self.original_df = None
        self.filtered_df = None


class BrainzMRIGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BrainzMRI - ListenBrainz Metadata Review Instrument")

        self.root.geometry("1000x800")
        self.root.minsize(1000, 700)
        self.root.resizable(True, True)
        self.root.update_idletasks()

        self.state = GUIState()
        self.report_engine = ReportEngine()

        self.processing = False
        self.progress_win = None
        self.sync_manager = None

        self.status_var = tk.StringVar(value="Ready.")
        self.status_bar = tk.Label(
            root,
            textvariable=self.status_var,
            bd=1,
            relief="sunken",
            anchor="center",
            font=("Segoe UI", 11),
        )

        # ------------------------------------------------------------
        # Top Area: User Selection & Source Control
        # ------------------------------------------------------------
        frm_top = tk.Frame(root)
        frm_top.pack(pady=10, fill="x", padx=10)

        # Row 1: User Profile Management
        frm_user = tk.Frame(frm_top)
        frm_user.pack(pady=(0, 5))

        tk.Label(frm_user, text="User:").pack(side="left", padx=(5, 5))

        self.user_var = tk.StringVar()
        self.user_dropdown = ttk.Combobox(
            frm_user,
            textvariable=self.user_var,
            state="readonly",
            width=25,
        )
        self.user_dropdown.pack(side="left", padx=(0, 10))
        self.user_dropdown.bind("<<ComboboxSelected>>", self.on_user_selected)

        tk.Button(frm_user, text="New User", command=self.new_user).pack(side="left", padx=2)
        tk.Button(frm_user, text="Edit User", command=self.edit_user).pack(side="left", padx=2)

        # Row 2: Source Control
        frm_source_controls = tk.Frame(frm_top)
        frm_source_controls.pack(pady=(5, 0))

        tk.Button(frm_source_controls, text="Import CSV...", command=self.import_csv).pack(side="left", padx=(5, 5))

        self.btn_get_listens = tk.Button(
            frm_source_controls,
            text="Get New Listens",
            command=self.action_get_new_listens,
            state="disabled"
        )
        self.btn_get_listens.pack(side="left", padx=(0, 10))
        Hovertip(self.btn_get_listens, "Fetch recent listens from ListenBrainz API.\nRequires username in profile.",
                 hover_delay=500)

        self.lbl_source_status = tk.Label(
            frm_source_controls,
            text="Active Source: User History",
            fg="gray",
            font=("Segoe UI", 9, "italic")
        )
        self.lbl_source_status.pack(side="left", padx=5)

        self.btn_close_csv = tk.Button(
            frm_source_controls,
            text="Close CSV",
            command=self.close_csv,
            bg="#FFCDD2",
            fg="black",
            font=("Segoe UI", 8)
        )

        # ------------------------------------------------------------
        # Input fields container
        # ------------------------------------------------------------
        frm_inputs = tk.Frame(root)
        frm_inputs.pack(pady=5)

        (self.ent_time_start, self.ent_time_end, self.time_frame) = self._create_labeled_double_entry(
            frm_inputs, "Time Range To Analyze (Days Ago)", 0, 0
        )

        (self.ent_last_start, self.ent_last_end, self.last_frame) = self._create_labeled_double_entry(
            frm_inputs, "Last Listened Date (Days Ago)", 0, 0
        )

        for widg in [self.ent_time_start, self.ent_time_end]:
            Hovertip(widg, "Time range filtering. Excludes listens by date.\nDefault: [0, 0] (days ago).", hover_delay=500)

        for widg in [self.ent_last_start, self.ent_last_end]:
            Hovertip(widg, "Recency filtering. Exclude entities by last listened.\nDefault: [0, 0] (days ago).", hover_delay=500)

        self.ent_topn, self.ent_min_listens = self._create_dual_entry_row(
            frm_inputs,
            "Top N (Number Of Results):", 200,
            "Number of Listens Threshold:", 10
        )

        self.ent_min_minutes, self.ent_min_likes = self._create_dual_entry_row(
            frm_inputs,
            "Minutes Listened Threshold:", 15,
            "Minimum Likes Threshold:", 0
        )

        Hovertip(self.ent_topn, "Number of results to return.\nDefault: 200 results", hover_delay=500)
        Hovertip(self.ent_min_listens, "Minimum number of listens.", hover_delay=500)
        Hovertip(self.ent_min_minutes, "Minimum number of minutes listened.", hover_delay=500)
        Hovertip(self.ent_min_likes, "Minimum number of unique liked tracks.", hover_delay=500)

        for entry in [self.ent_time_start, self.ent_time_end, self.ent_last_start, self.ent_last_end,
                      self.ent_topn, self.ent_min_listens, self.ent_min_minutes, self.ent_min_likes]:
            entry.bind("<Return>", lambda event: self.run_report())

        frm_enrich_source = tk.Frame(frm_inputs)
        frm_enrich_source.pack(fill="x", pady=8, anchor="center")

        enrich_inner = tk.Frame(frm_enrich_source)
        enrich_inner.pack(anchor="center")

        tk.Label(enrich_inner, text="Genre Lookup (Enrichment) Source:", width=32, anchor="e").pack(side="left")

        self.enrichment_mode_var = tk.StringVar(value="None (Data Only, No Genres)")
        self.cmb_enrich_source = ttk.Combobox(
            enrich_inner,
            textvariable=self.enrichment_mode_var,
            values=[
                "None (Data Only, No Genres)",
                "Cache Only",
                "Query MusicBrainz",
                "Query Last.fm",
                "Query All Sources (Slow)",
            ],
            state="readonly",
            width=28,
        )
        self.cmb_enrich_source.pack(side="left", padx=(0, 10))

        Hovertip(self.cmb_enrich_source, "Select enrichment source.\nAPI lookups are slow.", hover_delay=500)

        self.force_cache_update_var = tk.BooleanVar(value=False)
        chk_force_cache = tk.Checkbutton(
            enrich_inner,
            text="Force Cache Update",
            variable=self.force_cache_update_var,
        )
        chk_force_cache.pack(side="left", padx=5)
        Hovertip(chk_force_cache, "Forces querying the API for new genre data.", hover_delay=500)

        self.deep_query_var = tk.BooleanVar(value=False)
        chk_deep_query = tk.Checkbutton(
            enrich_inner,
            text="Deep Query (Slow)",
            variable=self.deep_query_var,
        )
        chk_deep_query.pack(side="left", padx=5)
        Hovertip(chk_deep_query, "Fetches metadata for Albums and Tracks individually.", hover_delay=500)

        def _update_enrichment_controls(*_):
            mode = self.enrichment_mode_var.get()
            if mode.startswith("None") or mode == "Cache Only":
                self.force_cache_update_var.set(False)
                chk_force_cache.configure(state="disabled")
                self.deep_query_var.set(False)
                chk_deep_query.configure(state="disabled")
            else:
                chk_force_cache.configure(state="normal")
                chk_deep_query.configure(state="normal")

        self.enrichment_mode_var.trace_add("write", lambda *args: _update_enrichment_controls())
        _update_enrichment_controls()

        # ------------------------------------------------------------
        # Buttons & Report Type Row
        # ------------------------------------------------------------
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)

        tk.Label(btn_frame, text="Report Type:").pack(side="left", padx=(0, 5))

        self.report_type = ttk.Combobox(
            btn_frame,
            values=[
                "By Artist",
                "By Album",
                "By Track",
                "Genre Flavor",
                "Favorite Artist Trend",
                "New Music By Year",
                "Raw Listens"
            ],
            state="readonly",
            width=18
        )
        self.report_type.current(0)
        self.report_type.pack(side="left", padx=(0, 15))
        self.report_type.bind("<<ComboboxSelected>>", self.on_report_type_selected)

        self.btn_generate = tk.Button(
            btn_frame,
            text="Generate Report",
            command=self.run_report,
            bg="#4CAF50",
            fg="white",
            width=16,
        )
        self.btn_generate.pack(side="left", padx=5)

        tk.Button(
            btn_frame,
            text="Save Report",
            command=self.save_report,
            bg="#2196F3",
            fg="white",
            width=16,
        ).pack(side="left", padx=5)

        self.btn_show_graph = tk.Button(
            btn_frame,
            text="Show Graph",
            command=self.show_graph,
            state="disabled",
            width=16,
        )
        self.btn_show_graph.pack(side="left", padx=5)

        # ------------------------------------------------------------
        # Table viewer frame
        # ------------------------------------------------------------
        self.table_frame = tk.Frame(root)
        self.table_frame.pack(fill="both", expand=True)
        self.table_frame.pack_propagate(False)

        self.table_view = ReportTableView(self.root, self.table_frame, self.state)

        # ------------------------------------------------------------
        # Upstream Actions Frame
        # ------------------------------------------------------------
        self.frm_upstream = tk.Frame(root, bg="#ECEFF1", bd=1, relief="groove")

        lbl_upstream = tk.Label(self.frm_upstream, text="Send To ListenBrainz Account:", bg="#ECEFF1",
                                font=("Segoe UI", 9, "bold"))
        lbl_upstream.pack(side="left", padx=(10, 5), pady=5)

        self.dry_run_var = tk.BooleanVar(value=True)
        chk_dry = tk.Checkbutton(
            self.frm_upstream,
            text="Dry Run (Simulate Only)",
            variable=self.dry_run_var,
            bg="#ECEFF1",
            activebackground="#ECEFF1"
        )
        chk_dry.pack(side="left", padx=(0, 15))
        Hovertip(chk_dry, "If checked, actions will NOT send data to ListenBrainz.", hover_delay=100)

        self.btn_like_all = tk.Button(
            self.frm_upstream,
            text="Like All Tracks",
            command=self.action_like_all,
            bg="#FFB74D",
        )
        self.btn_like_all.pack(side="left", padx=5)
        Hovertip(self.btn_like_all, "Mark all tracks in the list as Liked via API.", hover_delay=500)

        self.btn_like_selected = tk.Button(
            self.frm_upstream,
            text="Like Selected Tracks",
            command=self.action_like_selected,
            bg="#FFCC80",
        )
        self.btn_like_selected.pack(side="left", padx=5)
        Hovertip(self.btn_like_selected, "Submit a like for all highlighted tracks.", hover_delay=500)

        self.btn_resolve = tk.Button(
            self.frm_upstream,
            text="Resolve Metadata",
            command=self.action_resolve_metadata,
            bg="#4DD0E1",
        )
        Hovertip(self.btn_resolve, "Search MusicBrainz for missing MBIDs (slow).", hover_delay=500)

        self.btn_export_playlist = tk.Button(
            self.frm_upstream,
            text="Export as Playlist",
            command=self.action_export_playlist,
            bg="#9575CD",
            fg="white"
        )
        self.btn_export_playlist.pack(side="left", padx=5)
        Hovertip(self.btn_export_playlist, "Export all tracks in the list as a playlist via API.", hover_delay=500)

        # ------------------------------------------------------------
        # Status Bar
        # ------------------------------------------------------------
        self.status_bar.pack(fill="x", side="bottom")

        # Initialize
        self.refresh_user_list()
        
        # REFACTORED: Use config.last_user
        last_user = config.last_user
        if last_user and last_user in self.user_dropdown["values"]:
            self.user_var.set(last_user)
            self.load_user_from_cache(last_user)
            self.set_status(f"Auto-loaded user: {last_user}")
        else:
            self.set_status("Ready.")

    # ==================================================================
    # UI Generators
    # ==================================================================

    def _create_dual_entry_row(self, parent, label1, default1, label2, default2):
        row = tk.Frame(parent)
        row.pack(pady=2, anchor="center")
        tk.Label(row, text=label1, width=28, anchor="e").pack(side="left", padx=(0, 5))
        ent1 = tk.Entry(row, width=8)
        ent1.insert(0, str(default1))
        ent1.pack(side="left")
        tk.Frame(row, width=20).pack(side="left")
        tk.Label(row, text=label2, width=28, anchor="e").pack(side="left", padx=(0, 5))
        ent2 = tk.Entry(row, width=8)
        ent2.insert(0, str(default2))
        ent2.pack(side="left")
        return ent1, ent2

    def _create_labeled_double_entry(self, parent, label: str, default1, default2):
        frm = tk.Frame(parent)
        frm.pack(fill="x", pady=5)
        tk.Label(frm, text=label).pack(anchor="center")
        row = tk.Frame(frm)
        row.pack(anchor="center")
        tk.Label(row, text="Start:", width=8, anchor="e").pack(side="left")
        ent1 = tk.Entry(row, width=6)
        ent1.insert(0, str(default1))
        ent1.pack(side="left", padx=5)
        tk.Label(row, text="End:", width=8, anchor="e").pack(side="left")
        ent2 = tk.Entry(row, width=6)
        ent2.insert(0, str(default2))
        ent2.pack(side="left", padx=5)
        return ent1, ent2, frm

    # ==================================================================
    # User Management
    # ==================================================================

    def refresh_user_list(self) -> None:
        users = get_cached_usernames()
        self.user_dropdown["values"] = users
        if not users:
            self.user_var.set("")

    def new_user(self):
        UserEditorWindow(self.root, None, self._on_user_saved)

    def edit_user(self):
        username = self.user_var.get().strip()
        if not username:
            messagebox.showerror("Error", "Select a user to edit.")
            return
        try:
            user = User.from_cache(username)
        except Exception as e:
            messagebox.showerror("Error Loading User", f"Failed to load user: {e}")
            return
        UserEditorWindow(self.root, user, self._on_user_saved)

    def _on_user_saved(self, username: str):
        self.refresh_user_list()
        self.user_var.set(username)
        self.load_user_from_cache(username)
        self.set_status(f"User '{username}' saved.")

    # ==================================================================
    # User Loading & Source Management
    # ==================================================================

    def on_user_selected(self, event=None) -> None:
        username = self.user_var.get().strip()
        if not username:
            return
        self.load_user_from_cache(username)

    def load_user_from_cache(self, username: str) -> None:
        try:
            user = User.from_cache(username)
        except FileNotFoundError as e:
            messagebox.showerror("Error Loading User", str(e))
            self.set_status(f"Error: {str(e)}")
            return
        except Exception as e:
            messagebox.showerror("Error Loading User (Unknown)", f"{type(e).__name__}: {e}")
            self.set_status("Error: Failed to load user.")
            return

        self.state.user = user

        # REFACTORED: Use config
        config.last_user = username
        config.save()

        self.close_csv()
        self.lbl_source_status.config(text="Active Source: User History", fg="gray")
        self.set_status(f"User '{username}' loaded.")
        self._check_api_status()

    def _check_api_status(self):
        if self.state.user and self.state.user.get_listenbrainz_username():
            self.btn_get_listens.config(state="normal")
        else:
            self.btn_get_listens.config(state="disabled")

    def import_csv(self):
        if not self.state.user:
            messagebox.showerror("Error", "Please load a user first (to provide context).")
            return
        path = filedialog.askopenfilename(
            title="Select CSV Playlist",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            df = parsing.parse_generic_csv(path)
            df["_username"] = self.state.user.username
            self.state.playlist_df = df
            self.state.playlist_name = os.path.basename(path)
            self.lbl_source_status.config(text=f"Active Source: Playlist ({self.state.playlist_name})", fg="#E65100")
            self.btn_close_csv.pack(side="left", padx=5)
            self.report_type.set("Raw Listens")
            self.run_report()
            messagebox.showinfo("Import Successful", f"Loaded {len(df)} tracks from '{self.state.playlist_name}'.")
        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not parse CSV: {e}")

    def close_csv(self):
        self.state.playlist_df = None
        self.state.playlist_name = None
        self.lbl_source_status.config(text="Active Source: User History", fg="gray")
        self.btn_close_csv.pack_forget()
        self.frm_upstream.pack_forget()
        for widget in self.table_frame.winfo_children():
            widget.destroy()
        self.set_status("Playlist closed. Ready.")

    def on_report_type_selected(self, event=None):
        mode = self.report_type.get()
        if mode == "Genre Flavor":
            if self.enrichment_mode_var.get().startswith("None"):
                self.enrichment_mode_var.set("Cache Only")

    # ==================================================================
    # Report Generation (Threaded)
    # ==================================================================

    def _parse_int_field(self, entry: tk.Entry, field_name: str) -> int:
        value = entry.get().strip()
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"{field_name} must be numeric.")

    def _parse_float_field(self, entry: tk.Entry, field_name: str) -> float:
        value = entry.get().strip()
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"{field_name} must be numeric.")

    def run_report(self) -> None:
        if self.processing:
            return
        if self.state.user is None:
            messagebox.showerror("Error", "Please load or create a user first.")
            self.set_status("Error: No user loaded.")
            return

        self.processing = True
        mode = self.report_type.get()

        try:
            t_start = self._parse_int_field(self.ent_time_start, "Time range")
            t_end = self._parse_int_field(self.ent_time_end, "Time range")
            time_start = min(t_start, t_end)
            time_end = max(t_start, t_end)

            l_start = self._parse_int_field(self.ent_last_start, "Last listened range")
            l_end = self._parse_int_field(self.ent_last_end, "Last listened range")
            rec_start = min(l_start, l_end)
            rec_end = max(l_start, l_end)

            min_listens = self._parse_int_field(self.ent_min_listens, "Minimum listens")
            min_minutes = self._parse_float_field(self.ent_min_minutes, "Minimum time listened")
            min_likes = self._parse_int_field(self.ent_min_likes, "Minimum likes")
            topn = self._parse_int_field(self.ent_topn, "Top N")
        except ValueError as e:
            self.processing = False
            messagebox.showerror("Error With Filter Input", str(e))
            self.set_status(f"Error With Filter Input: {str(e)}")
            return

        enrich_mode_str = self.enrichment_mode_var.get()
        do_enrich = not enrich_mode_str.startswith("None")

        params = {
            "mode": mode,
            "liked_mbids": self.state.user.get_liked_mbids(),
            "time_start_days": time_start,
            "time_end_days": time_end,
            "rec_start_days": rec_start,
            "rec_end_days": rec_end,
            "min_listens": min_listens,
            "min_minutes": min_minutes,
            "min_likes": min_likes,
            "topn": topn,
            "do_enrich": do_enrich,
            "enrichment_mode": enrich_mode_str,
            "force_cache_update": self.force_cache_update_var.get(),
            "deep_query": self.deep_query_var.get(),
        }

        self.state.last_params = params.copy()

        if self.state.playlist_df is not None:
            base_df = self.state.playlist_df.copy()
        else:
            base_df = self.state.user.get_listens().copy()

        if "_username" not in base_df.columns:
            base_df["_username"] = self.state.user.username

        self.btn_generate.config(state="disabled")

        current_progress_win = ProgressWindow(self.root, title=f"Generating {mode}...")
        self.progress_win = current_progress_win

        def worker():
            try:
                def progress_callback(current, total, msg):
                    def _do_update():
                        try:
                            if current_progress_win.winfo_exists():
                                current_progress_win.update_progress(current, total, msg)
                        except Exception:
                            pass
                    self.root.after(0, _do_update)

                def is_cancelled():
                    try:
                        return current_progress_win.cancelled
                    except Exception:
                        return True

                result, meta, report_type_key, last_enriched, status_text = (
                    self.report_engine.generate_report(
                        base_df,
                        **params,
                        progress_callback=progress_callback,
                        is_cancelled=is_cancelled
                    )
                )

                self.root.after(0, lambda: self._on_report_success(
                    result, meta, report_type_key, last_enriched, status_text, mode
                ))

            except ValueError as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._on_report_error(err_msg, "Error Executing Report"))
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"
                self.root.after(0, lambda: self._on_report_error(err_msg, "Unexpected Error"))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_report_success(self, result, meta, report_type_key, last_enriched, status_text, mode):
        if self.progress_win:
            win = self.progress_win
            try:
                win.grab_release()
                win.withdraw()
                self.root.after(100, win.destroy)
            except Exception:
                pass
            self.progress_win = None

        self.processing = False
        self.btn_generate.config(state="normal")

        self.state.last_report_df = result
        self.state.last_meta = meta
        self.state.last_mode = mode
        self.state.last_report_type_key = report_type_key
        self.state.last_enriched = last_enriched

        self.state.original_df = result.copy()
        self.state.filtered_df = result.copy()

        self.table_view.show_table(result)
        self.set_status(status_text)

        if mode in ["Favorite Artist Trend", "New Music By Year", "Genre Flavor"]:
            self.btn_show_graph.config(state="normal")
        else:
            self.btn_show_graph.config(state="disabled")

        has_tracks = "track_name" in result.columns and "artist" in result.columns
        has_mbids = False
        if "recording_mbid" in result.columns:
            valid = result["recording_mbid"].notna() & (result["recording_mbid"] != "") & (
                        result["recording_mbid"] != "None")
            has_mbids = valid.any()

        has_missing_mbids = False
        if "recording_mbid" in result.columns:
            missing = result["recording_mbid"].isna() | (result["recording_mbid"] == "") | (
                        result["recording_mbid"] == "None")
            has_missing_mbids = missing.any()
        elif has_tracks:
            has_missing_mbids = True

        if has_tracks or has_mbids:
            self.frm_upstream.pack(fill="x", side="bottom", before=self.status_bar, padx=5, pady=5)
            if has_mbids:
                self.btn_like_all.config(state="normal")
                self.btn_like_selected.config(state="normal")
            else:
                self.btn_like_all.config(state="disabled")
                self.btn_like_selected.config(state="disabled")

            if has_missing_mbids:
                self.btn_resolve.pack(side="left", padx=5)
            else:
                self.btn_resolve.pack_forget()
        else:
            self.frm_upstream.pack_forget()

    def _on_report_error(self, error_msg, title):
        if self.progress_win:
            win = self.progress_win
            try:
                win.grab_release()
                win.withdraw()
                self.root.after(100, win.destroy)
            except Exception:
                pass
            self.progress_win = None

        self.processing = False
        self.btn_generate.config(state="normal")

        messagebox.showerror(title, error_msg)
        self.set_status(f"Error: {error_msg}")
        self.frm_upstream.pack_forget()

    # ==================================================================
    # Upstream Actions (Like / Playlist / Resolve)
    # ==================================================================

    def _get_lb_client(self) -> ListenBrainzClient:
        token = self.state.user.listenbrainz_token
        dry_run = self.dry_run_var.get()
        return ListenBrainzClient(token=token, dry_run=dry_run)

    # ------------------------------------------------------------------
    # Incremental Update (New Listens)
    # ------------------------------------------------------------------

    def action_get_new_listens(self):
        if not self.state.user or not self.state.user.get_listenbrainz_username():
            messagebox.showerror("Error", "ListenBrainz Username required.")
            return

        local_head_ts = self.state.user.get_latest_listen_timestamp()
        intermediate_df = self.state.user.load_intermediate_listens()
        resume_mode = False

        if not intermediate_df.empty:
            if pd.api.types.is_datetime64_any_dtype(intermediate_df["listened_at"]):
                try:
                    start_ts = int(intermediate_df["listened_at"].min().timestamp())
                    resume_mode = True
                except Exception:
                    start_ts = int(time.time())
            else:
                start_ts = int(time.time())
        else:
            start_ts = int(time.time())

        self.btn_get_listens.config(state="disabled")
        self.processing = True

        title = "Fetching New Listens..."
        if resume_mode:
            title = "Resuming Fetch (Intermediate Cache Found)..."

        current_progress_win = ProgressWindow(self.root, title=title)
        self.progress_win = current_progress_win

        callbacks = {
            "update_primary": lambda c, m: current_progress_win.update_progress(0, 0, f"{m} (Total: {c})"),
            "update_secondary": current_progress_win.update_secondary,
            "on_complete": self._on_sync_complete,
            "on_error": lambda msg: self._on_report_error(msg, "Sync Error"),
            "request_confirmation": self._request_sync_confirmation
        }

        self.sync_manager = SyncManager(
            self.state.user,
            self._get_lb_client(),
            self.root.after,
            callbacks
        )

        current_progress_win.btn_cancel.config(
            command=lambda: [current_progress_win.cancel(), self.sync_manager.cancel()])

        self.sync_manager.start(start_ts, local_head_ts)

    def _request_sync_confirmation(self, message, callback):
        def _ask():
            result = messagebox.askyesno("Confirm", message)
            callback(result)
        _ask()

    def _on_sync_complete(self, barrier_state):
        if self.progress_win:
            try:
                self.progress_win.grab_release()
                self.progress_win.withdraw()
                self.progress_win.destroy()
            except Exception:
                pass
            self.progress_win = None

        self.btn_get_listens.config(state="normal")
        self.processing = False
        self.sync_manager = None

        if barrier_state["gap_closed"]:
            self.state.user.merge_intermediate_cache()

            msg = f"Update Complete.\nImported {barrier_state['listens_count']} new listens."
            
            if barrier_state.get("likes_failed"):
                msg += "\n\nWARNING: User Likes Sync Failed (Check logs)."
            elif barrier_state['likes_count'] > 0:
                msg += f"\nSynced {barrier_state['likes_count']} User Likes."
            
            msg += "\nHistory is fully continuous."

            messagebox.showinfo("Update Complete", msg)

            if self.report_type.get() == "Raw Listens":
                self.run_report()
        else:
            msg = (
                f"Fetch stopped after {barrier_state['listens_count']} listens.\n"
                "Gap to local history NOT closed yet.\n"
                "Progress has been saved to a temporary file.\n"
                "Run 'Get New Listens' again to resume."
            )
            messagebox.showwarning("Update Incomplete", msg)

    def action_resolve_metadata(self):
        if self.state.last_report_df is None:
            return

        self.btn_resolve.config(state="disabled")

        current_progress_win = ProgressWindow(self.root, title="Resolving Metadata...")
        self.progress_win = current_progress_win

        df_in = self.state.last_report_df.copy()

        def worker():
            try:
                def progress_callback(current, total, msg):
                    def _do_update():
                        try:
                            if current_progress_win.winfo_exists():
                                current_progress_win.update_progress(current, total, msg)
                        except Exception:
                            pass
                    self.root.after(0, _do_update)

                def is_cancelled():
                    try:
                        return current_progress_win.cancelled
                    except Exception:
                        return True

                df_resolved, count_res, count_fail = enrichment.resolve_missing_mbids(
                    df_in,
                    progress_callback=progress_callback,
                    is_cancelled=is_cancelled
                )

                def _finish():
                    if current_progress_win.winfo_exists():
                        current_progress_win.grab_release()
                        current_progress_win.withdraw()
                        self.root.after(100, current_progress_win.destroy)

                    self.btn_resolve.config(state="normal")

                    self.state.last_report_df = df_resolved
                    self.state.original_df = df_resolved.copy()
                    self.state.filtered_df = df_resolved.copy()

                    if self.state.playlist_df is not None:
                        try:
                            resolved_subset = df_resolved[
                                df_resolved["recording_mbid"].notna() &
                                (df_resolved["recording_mbid"] != "") &
                                (df_resolved["recording_mbid"] != "None")
                                ].copy()

                            if not resolved_subset.empty:
                                resolved_subset["_merge_key"] = parsing.make_track_key_series(resolved_subset)
                                update_map = resolved_subset.drop_duplicates(subset=["_merge_key"]).set_index(
                                    "_merge_key")[["recording_mbid", "album"]]

                                self.state.playlist_df["_merge_key"] = parsing.make_track_key_series(
                                    self.state.playlist_df)

                                self.state.playlist_df["recording_mbid"] = self.state.playlist_df["_merge_key"].map(
                                    update_map["recording_mbid"]
                                ).fillna(self.state.playlist_df["recording_mbid"])

                                self.state.playlist_df["album"] = self.state.playlist_df["_merge_key"].map(
                                    update_map["album"]
                                ).fillna(self.state.playlist_df["album"])

                                self.state.playlist_df.drop(columns=["_merge_key"], inplace=True)

                        except Exception as e:
                            logging.error(f"Warning: Could not persist resolved metadata to playlist session: {e}")

                    self.table_view.show_table(df_resolved)

                    self._on_report_success(
                        df_resolved,
                        self.state.last_meta,
                        self.state.last_report_type_key,
                        self.state.last_enriched,
                        f"Resolved {count_res} tracks ({count_fail} failed).",
                        self.state.last_mode
                    )

                    messagebox.showinfo("Resolution Complete",
                                        f"Successfully resolved {count_res} new MusicBrainz IDs.\n{count_fail} items could not be matched with high confidence.")

                self.root.after(0, _finish)

            except Exception as e:
                err_msg = f"Error in resolver: {e}"
                self.root.after(0, lambda: self._on_report_error(err_msg, "Error"))

        threading.Thread(target=worker, daemon=True).start()

    def _execute_like_task(self, mbids_to_process: list[str]):
        count = len(mbids_to_process)
        if count == 0:
            messagebox.showinfo("No Tracks", "No valid MusicBrainz IDs found in selection.")
            return

        dry_run = self.dry_run_var.get()
        mode_str = "SIMULATION" if dry_run else "LIVE ACTION"

        msg = f"Ready to 'Like' (score=1) {count} unique tracks.\nMode: {mode_str}\n\nProceed?"
        if not messagebox.askyesno("Confirm Likes", msg):
            return

        client = self._get_lb_client()

        self.btn_like_all.config(state="disabled")
        self.btn_like_selected.config(state="disabled")

        current_progress_win = ProgressWindow(self.root, title="Submitting Feedback...")
        self.progress_win = current_progress_win

        def worker():
            success_count = 0
            fail_count = 0

            try:
                for i, mbid in enumerate(mbids_to_process):
                    if current_progress_win.cancelled:
                        break

                    def _update():
                        if current_progress_win.winfo_exists():
                            current_progress_win.update_progress(
                                i, count, f"Liking track {i + 1}/{count}..."
                            )
                    self.root.after(0, _update)

                    try:
                        client.submit_feedback(mbid, 1)
                        success_count += 1
                    except Exception as e:
                        logging.error(f"Error liking {mbid}: {e}")
                        fail_count += 1

                        err_str = str(e)
                        if "401" in err_str or "403" in err_str or "429" in err_str:
                            self.root.after(0, lambda: messagebox.showerror(
                                "API Error - Aborting",
                                f"Critical API error encountered (Auth or Rate Limit).\nStopping to protect your account.\n\nError: {e}"
                            ))
                            current_progress_win.cancelled = True
                            break

                    if not dry_run:
                        time.sleep(0.3)

                def _finish():
                    if current_progress_win.winfo_exists():
                        current_progress_win.grab_release()
                        current_progress_win.withdraw()
                        self.root.after(100, current_progress_win.destroy)

                    self.btn_like_all.config(state="normal")
                    self.btn_like_selected.config(state="normal")

                    result_msg = f"Finished.\nSuccessful: {success_count}\nFailed: {fail_count}"
                    if dry_run:
                        result_msg += "\n(Note: This was a Dry Run. No data sent.)"
                    messagebox.showinfo("Feedback Complete", result_msg)

                self.root.after(0, _finish)

            except Exception as e:
                err_msg = f"Error in feedback worker: {e}"
                self.root.after(0, lambda: self._on_report_error(err_msg, "Error"))

        threading.Thread(target=worker, daemon=True).start()

    def action_like_all(self):
        if self.state.filtered_df is None or self.state.filtered_df.empty:
            return

        df = self.state.filtered_df
        if "recording_mbid" not in df.columns:
            return

        valid_rows = df[df["recording_mbid"].notna() & (df["recording_mbid"] != "")].copy()
        unique_mbids = list(valid_rows["recording_mbid"].unique())

        self._execute_like_task(unique_mbids)

    def action_like_selected(self):
        if self.state.filtered_df is None:
            return

        tree = self.table_view.tree
        if not tree:
            return

        selection = tree.selection()
        if not selection:
            messagebox.showinfo("No Selection", "Please select rows in the table first.")
            return

        df = self.state.filtered_df
        if "recording_mbid" not in df.columns:
            messagebox.showerror("Error", "Underlying data is missing MusicBrainz IDs.")
            return

        selected_mbids = set()
        all_children = tree.get_children()

        for item in selection:
            try:
                idx = all_children.index(item)
                if idx < len(df):
                    val = df.iloc[idx]["recording_mbid"]
                    if val and isinstance(val, str) and val.strip() and val != "None":
                        selected_mbids.add(val)
            except ValueError:
                continue

        if not selected_mbids:
            messagebox.showinfo("No Data", "No valid MBIDs found in selected rows.")
            return

        self._execute_like_task(list(selected_mbids))

    def action_export_playlist(self):
        if self.state.filtered_df is None or self.state.filtered_df.empty:
            return

        df = self.state.filtered_df
        if "artist" not in df.columns or "track_name" not in df.columns:
            messagebox.showerror("Error", "Report must contain Artist and Track Name columns.")
            return

        dry_run = self.dry_run_var.get()
        default_name = f"BrainzMRI Export {datetime.now().strftime('%Y-%m-%d')}"

        name = simpledialog.askstring("Create Playlist", "Enter Playlist Name:", initialvalue=default_name)
        if not name:
            return

        client = self._get_lb_client()

        track_list = []
        skipped_count = 0

        for _, row in df.iterrows():
            mbid = row.get("recording_mbid")
            has_mbid = mbid and isinstance(mbid, str) and mbid.strip() and mbid != "None"

            if not has_mbid:
                skipped_count += 1
                continue

            item = {
                "artist": str(row["artist"]),
                "title": str(row["track_name"]),
                "mbid": str(mbid)
            }
            if "album" in row and row["album"] != "Unknown":
                item["album"] = str(row["album"])

            track_list.append(item)

        count = len(track_list)

        if count == 0:
            messagebox.showwarning("No Tracks",
                                   "No tracks with valid MusicBrainz IDs were found.\nPlaylist export aborted.")
            return

        self.btn_export_playlist.config(state="disabled")
        
        current_progress_win = ProgressWindow(self.root, title="Uploading Playlist...")
        self.progress_win = current_progress_win

        def worker():
            try:
                self.root.after(0,
                                lambda: current_progress_win.update_progress(50, 100, "Generating JSPF Payload..."))

                try:
                    resp = client.create_playlist(name, track_list, description="Created via BrainzMRI")
                    success = True
                    msg = f"Playlist '{name}' created with {count} tracks."

                    if skipped_count > 0:
                        msg += f"\n({skipped_count} tracks were scrubbed due to missing metadata.)"

                    if dry_run:
                        msg += "\n(Dry Run: JSON printed to console)"
                except Exception as e:
                    success = False
                    msg = f"Failed to create playlist: {e}"

                def _finish():
                    if current_progress_win.winfo_exists():
                        current_progress_win.grab_release()
                        current_progress_win.withdraw()
                        self.root.after(100, current_progress_win.destroy)

                    self.btn_export_playlist.config(state="normal")

                    if success:
                        messagebox.showinfo("Success", msg)
                    else:
                        messagebox.showerror("Error", msg)

                self.root.after(0, _finish)

            except Exception as e:
                err_msg = f"Error in playlist worker: {e}"
                self.root.after(0, lambda: self._on_report_error(err_msg, "Error"))

        threading.Thread(target=worker, daemon=True).start()

    # ==================================================================
    # Graphing
    # ==================================================================

    def show_graph(self):
        """
        Prepare data and show the chart for the current report.
        """
        mode = self.state.last_mode
        params = self.state.last_params

        if not params:
            return

        # Case 1: Favorite Artist Trend
        if mode == "Favorite Artist Trend":
            # PHASE 2.2: Use Playlist if active
            if self.state.playlist_df is not None:
                df = self.state.playlist_df.copy()
            else:
                df = self.state.user.get_listens().copy()

            # Re-apply filters manually because we need "Top N Overall" logic
            t_start = params.get("time_start_days", 0)
            t_end = params.get("time_end_days", 0)
            if not (t_start == 0 and t_end == 0):
                df = reporting.filter_by_days(df, "listened_at", t_start, t_end)

            try:
                chart_df = reporting.prepare_artist_trend_chart_data(
                    df,
                    bins=15,
                    topn=params.get("topn", 20)
                )
                if chart_df.empty:
                    messagebox.showinfo("No Data", "Not enough data to generate a chart.")
                    return

                # UPDATED: Call standalone function
                gui_charts.show_artist_trend_chart(chart_df)

            except Exception as e:
                messagebox.showerror("Chart Error", f"Failed to generate chart: {e}")

        # Case 2: New Music By Year
        elif mode == "New Music By Year":
            df = self.state.last_report_df
            if df is None or df.empty:
                messagebox.showinfo("No Data", "No data available.")
                return

            try:
                # UPDATED: Call standalone function
                gui_charts.show_new_music_stacked_bar(df)
            except Exception as e:
                messagebox.showerror("Chart Error", f"Failed to generate chart: {e}")

        # Case 3: Genre Flavor (NEW)
        elif mode == "Genre Flavor":
            df = self.state.last_report_df
            if df is None or df.empty:
                messagebox.showinfo("No Data", "No data available.")
                return

            try:
                # UPDATED: Call the new Treemap function
                gui_charts.show_genre_flavor_treemap(df)
            except Exception as e:
                messagebox.showerror("Chart Error", f"Failed to generate chart: {e}")

    # ==================================================================
    # Saving reports
    # ==================================================================

    def save_report(self) -> None:
        if self.state.last_report_df is None:
            messagebox.showerror("Error", "No report to save. Generate a report first.")
            self.set_status("Error: No report to save.")
            return

        if self.state.user is None:
            messagebox.showerror("Error", "No user loaded.")
            self.set_status("Error: No user loaded.")
            return

        try:
            if self.state.last_meta is None:
                report_name = (self.state.last_mode or "Report").replace(" ", "_")
                filepath = reporting.save_report(
                    self.state.last_report_df,
                    user=self.state.user,
                    report_name=report_name,
                    meta=None,
                )
            else:
                filepath = reporting.save_report(
                    self.state.last_report_df,
                    user=self.state.user,
                    meta=self.state.last_meta,
                    report_name=None,
                )

            open_file_default(filepath)
            self.set_status(f"{self.state.last_mode} report saved and opened.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save report: {type(e).__name__}: {e}")
            self.set_status("Error: Failed to save report.")

    # ==================================================================
    # Utility
    # ==================================================================

    def set_status(self, text: str) -> None:
        self.status_var.set(text)
        self.status_bar.update_idletasks()

    def load_config(self) -> dict:
        return {} # Deprecated

    def save_config(self, data: dict) -> None:
        pass # Deprecated


# ======================================================================
# Main entry point
# ======================================================================

if __name__ == "__main__":
    setup_logging()
    root = tk.Tk()
    app = BrainzMRIGUI(root)
    root.mainloop()