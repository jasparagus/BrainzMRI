"""
gui.py
Tkinter GUI for BrainzMRI, using reporting, enrichment, and user modules.
"""

import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from datetime import datetime, timedelta, timezone
from idlelib.tooltip import Hovertip
import os
import subprocess
import sys
import re
import threading

import reporting
import enrichment
import gui_charts
from user import (
    User,
    get_cache_root,
    get_cached_usernames,
    get_user_cache_dir,
)
from report_engine import ReportEngine
from gui_user_editor import UserEditorWindow
from gui_tableview import ReportTableView


def open_file_default(path: str) -> None:
    """Open a file using the OS default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class GUIState:
    """Centralized state for the BrainzMRI GUI."""

    def __init__(self) -> None:
        # Current user
        self.user: User | None = None

        # Last generated report
        self.last_report_df = None
        self.last_meta = None
        self.last_mode: str | None = None
        self.last_report_type_key: str | None = None
        self.last_enriched: bool = False
        
        # New: Store params to reproduce charts logic
        self.last_params: dict = {}

        # Table/filtering state
        self.original_df = None
        self.filtered_df = None


class ProgressWindow(tk.Toplevel):
    """
    A modal dialog showing a progress bar and a Cancel button.
    Thread-safe updates must be handled via callbacks scheduling on main loop.
    """
    def __init__(self, parent, title="Processing..."):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x150")
        self.resizable(False, False)
        self.parent = parent
        self.cancelled = False

        # Center window
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (400 // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (150 // 2)
        self.geometry(f"+{x}+{y}")

        # UI
        self.lbl_status = tk.Label(self, text="Initializing...", anchor="w")
        self.lbl_status.pack(fill="x", padx=20, pady=(20, 5))

        self.progress = ttk.Progressbar(self, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", padx=20, pady=5)

        self.btn_cancel = tk.Button(self, text="Cancel", command=self.cancel, width=10)
        self.btn_cancel.pack(pady=20)

        # Make modal
        self.transient(parent)
        self.grab_set()
        
        # Handle "X" button
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def update_progress(self, current, total, message):
        """Update the progress bar and label."""
        self.lbl_status.config(text=message)
        if total > 0:
            pct = (current / total) * 100
            self.progress["value"] = pct
        else:
            self.progress["value"] = 0

    def cancel(self):
        """Set cancellation flag and disable button."""
        self.cancelled = True
        self.lbl_status.config(text="Cancelling... please wait for current step to finish.")
        self.btn_cancel.config(state="disabled")


# ======================================================================
# Main GUI
# ======================================================================

class BrainzMRIGUI:
    """
    Tkinter GUI wrapper for BrainzMRI.
    Handles user selection, report generation, filtering, and table display.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BrainzMRI - ListenBrainz Metadata Review Instrument")

        self.root.geometry("1000x700")
        self.root.minsize(1000, 700)
        self.root.resizable(True, True)
        self.root.update_idletasks()

        # Centralized state and engine
        self.state = GUIState()
        self.report_engine = ReportEngine()

        # Status bar
        self.status_var = tk.StringVar(value="Ready.")
        self.status_bar = tk.Label(
            root,
            textvariable=self.status_var,
            bd=1,
            relief="sunken",
            anchor="center",
            font=("Segoe UI", 11),
        )

        # User selection and ingestion
        frm_user = tk.Frame(root)
        frm_user.pack(pady=10)

        tk.Label(frm_user, text="User:").pack(side="left", padx=(10, 5))

        self.user_var = tk.StringVar()
        self.user_dropdown = ttk.Combobox(
            frm_user,
            textvariable=self.user_var,
            state="readonly",
            width=30,
        )
        self.user_dropdown.pack(side="left", padx=(0, 10))
        self.user_dropdown.bind("<<ComboboxSelected>>", self.on_user_selected)

        # New User / Edit User buttons
        tk.Button(frm_user, text="New User", command=self.new_user).pack(side="left", padx=5)
        tk.Button(frm_user, text="Edit User", command=self.edit_user).pack(side="left", padx=5)

        self.lbl_user_status = tk.Label(frm_user, text="", fg="gray")
        self.lbl_user_status.pack(side="left", padx=10)

        # Input fields container
        frm_inputs = tk.Frame(root)
        frm_inputs.pack(pady=10)

        # ------------------------------------------------------------
        # Time Range Filters
        # ------------------------------------------------------------
        (self.ent_time_start, self.ent_time_end, self.time_frame) = self._create_labeled_double_entry(
            frm_inputs, "Time Range To Analyze (Days Ago)", 0, 0
        )

        (self.ent_last_start, self.ent_last_end, self.last_frame) = self._create_labeled_double_entry(
            frm_inputs, "Last Listened Date (Days Ago)", 0, 0
        )

        for widg in [self.ent_time_start, self.ent_time_end]:
            Hovertip(
                widg,
                "Time range filtering. Excludes listens by date.\n"
                "Example: [365, 730] will display listens from 1–2 years ago.\n"
                "Set to [0, 0] to disable filtering.\n"
                "Default: [0, 0] (days ago).",
                hover_delay=500,
            )

        for widg in [self.ent_last_start, self.ent_last_end]:
            Hovertip(
                widg,
                "Recency filtering. Exclude entities by last listened.\n"
                "Example: [365, 99999] will display entities last listened >1 year ago.\n"
                "Set to [0, 0] to disable filtering.\n"
                "Default: [0, 0] (days ago).",
                hover_delay=500,
            )

        # ------------------------------------------------------------
        # Thresholds and Top N
        # ------------------------------------------------------------
        self.ent_topn = self._create_labeled_entry(frm_inputs, "Top N (Number Of Results):", 200)
        self.ent_min_listens = self._create_labeled_entry(frm_inputs, "Number of Listens Threshold:", 10)
        self.ent_min_minutes = self._create_labeled_entry(frm_inputs, "Minutes Listened Threshold:", 15)
        self.ent_min_likes = self._create_labeled_entry(frm_inputs, "Minimum Likes Threshold:", 0)

        Hovertip(self.ent_topn, "Number of results to return.\nDefault: 200 results", hover_delay=500)
        Hovertip(self.ent_min_listens, "Minimum number of listens.\nWorks as an OR with minimum minutes.", hover_delay=500)
        Hovertip(self.ent_min_minutes, "Minimum number of minutes listened.\nWorks as an OR with minimum listens.", hover_delay=500)
        Hovertip(self.ent_min_likes, "Minimum number of unique liked tracks.\nDefault: 0 (disabled).", hover_delay=500)

        # Bind Enter key
        for entry in [self.ent_time_start, self.ent_time_end, self.ent_last_start, self.ent_last_end,
                      self.ent_topn, self.ent_min_listens, self.ent_min_minutes, self.ent_min_likes]:
            entry.bind("<Return>", lambda event: self.run_report())

        # ------------------------------------------------------------
        # Enrichment controls
        # ------------------------------------------------------------
        self.do_enrich_var = tk.BooleanVar(value=False)
        chk_enrich = tk.Checkbutton(
            frm_inputs,
            text="Perform Genre Lookup (Enrich Report)",
            variable=self.do_enrich_var,
        )
        chk_enrich.pack(anchor="w", pady=5)

        frm_enrich_source = tk.Frame(frm_inputs)
        frm_enrich_source.pack(fill="x", pady=2, anchor="w")

        tk.Label(frm_enrich_source, text="Genre Enrichment Source:", width=32, anchor="w").pack(side="left")

        self.enrichment_mode_var = tk.StringVar(value="Cache Only")
        self.cmb_enrich_source = ttk.Combobox(
            frm_enrich_source,
            textvariable=self.enrichment_mode_var,
            values=[
                "Cache Only",
                "Query MusicBrainz",
                "Query Last.fm",
                "Query All Sources (Slow)",
            ],
            state="readonly",
            width=22,
        )
        self.cmb_enrich_source.pack(side="left")

        self.force_cache_update_var = tk.BooleanVar(value=False)
        chk_force_cache = tk.Checkbutton(
            frm_inputs,
            text="Force Cache Update",
            variable=self.force_cache_update_var,
        )
        chk_force_cache.pack(anchor="w", pady=2)

        def _update_enrichment_controls(*_):
            do_enrich = self.do_enrich_var.get()
            mode = self.enrichment_mode_var.get()

            if not do_enrich:
                self.cmb_enrich_source.configure(state="disabled")
                self.force_cache_update_var.set(False)
                chk_force_cache.configure(state="disabled")
                return

            self.cmb_enrich_source.configure(state="readonly")
            if mode == "Cache Only":
                self.force_cache_update_var.set(False)
                chk_force_cache.configure(state="disabled")
            else:
                chk_force_cache.configure(state="normal")

        self.do_enrich_var.trace_add("write", lambda *args: _update_enrichment_controls())
        self.enrichment_mode_var.trace_add("write", lambda *args: _update_enrichment_controls())
        _update_enrichment_controls()

        # ------------------------------------------------------------
        # Report type selection
        # ------------------------------------------------------------
        frm_type = tk.Frame(root)
        frm_type.pack(pady=10)
        tk.Label(frm_type, text="Report Type:").pack(side="left", padx=5)

        self.report_type = ttk.Combobox(
            frm_type,
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
        )
        self.report_type.current(0)
        self.report_type.pack(side="left")
        self.report_type.bind("<<ComboboxSelected>>", self.on_report_type_selected)

        # ------------------------------------------------------------
        # Buttons
        # ------------------------------------------------------------
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)

        tk.Button(
            btn_frame,
            text="Generate Report",
            command=self.run_report,
            bg="#4CAF50",
            fg="white",
            width=16,
        ).pack(side="left", padx=5)

        tk.Button(
            btn_frame,
            text="Save Report",
            command=self.save_report,
            bg="#2196F3",
            fg="white",
            width=16,
        ).pack(side="left", padx=5)

        # New Show Graph button
        self.btn_show_graph = tk.Button(
            btn_frame,
            text="Show Graph",
            command=self.show_graph,
            state="disabled",
            width=16,
        )
        self.btn_show_graph.pack(side="left", padx=5)

        self.status_bar.pack(fill="x", side="bottom")

        # ------------------------------------------------------------
        # Table viewer frame
        # ------------------------------------------------------------
        self.table_frame = tk.Frame(root)
        self.table_frame.pack(fill="both", expand=True)
        self.table_frame.pack_propagate(False)

        self.table_view = ReportTableView(self.root, self.table_frame, self.state)

        # Initialize
        self.refresh_user_list()
        cfg = self.load_config()
        last_user = cfg.get("last_user")
        if last_user and last_user in self.user_dropdown["values"]:
            self.user_var.set(last_user)
            self.load_user_from_cache(last_user)
            self.set_status(f"Auto-loaded user: {last_user}")
        else:
            self.set_status("Ready.")

    # ==================================================================
    # UI Generators
    # ==================================================================

    def _create_labeled_entry(self, parent, label: str, default) -> tk.Entry:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, width=27, anchor="w").pack(side="left")
        ent = tk.Entry(row, width=8)
        ent.insert(0, str(default))
        ent.pack(side="left")
        return ent

    def _create_labeled_double_entry(self, parent, label: str, default1, default2):
        frm = tk.Frame(parent)
        frm.pack(fill="x", pady=5)
        tk.Label(frm, text=label).pack(anchor="center")
        row = tk.Frame(frm)
        row.pack(anchor="center")
        tk.Label(row, text="Start:", width=8).pack(side="left")
        ent1 = tk.Entry(row, width=6)
        ent1.insert(0, str(default1))
        ent1.pack(side="left", padx=5)
        tk.Label(row, text="End:", width=8).pack(side="left")
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
            self.lbl_user_status.config(text="No cached users found.", fg="gray")

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
    # User Loading
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
        self.lbl_user_status.config(text=f"Loaded user: {username}", fg="black")

        cfg = self.load_config()
        cfg["last_user"] = username
        self.save_config(cfg)

        # Clear previous report state
        self.state.last_report_df = None
        self.state.last_meta = None
        self.state.last_mode = None
        self.state.last_report_type_key = None
        self.state.last_enriched = False
        self.state.original_df = None
        self.state.filtered_df = None
        
        self.btn_show_graph.config(state="disabled") # Reset graph button
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        self.set_status(f"User '{username}' loaded.")

    def on_report_type_selected(self, event=None):
        """Handle changes to the report type dropdown."""
        mode = self.report_type.get()
        if mode == "Genre Flavor":
            # Automatically enable enrichment if it's currently off
            if not self.do_enrich_var.get():
                self.do_enrich_var.set(True)
                # Default to Cache Only if we just auto-enabled it
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
        if self.state.user is None:
            messagebox.showerror("Error", "Please load or create a user first.")
            self.set_status("Error: No user loaded.")
            return

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
            messagebox.showerror("Error With Filter Input", str(e))
            self.set_status(f"Error With Filter Input: {str(e)}")
            return

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
            "do_enrich": self.do_enrich_var.get(),
            "enrichment_mode": self.enrichment_mode_var.get(),
            "force_cache_update": self.force_cache_update_var.get(),
        }

        # Store params for potential graph regeneration
        self.state.last_params = params.copy()

        base_df = self.state.user.get_listens().copy()
        base_df["_username"] = self.state.user.username

        self.progress_win = ProgressWindow(self.root, title=f"Generating {mode}...")

        def worker():
            try:
                def progress_callback(current, total, msg):
                    self.root.after(0, lambda: self.progress_win.update_progress(current, total, msg))
                
                def is_cancelled():
                    return self.progress_win.cancelled

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
                self.root.after(0, lambda: self._on_report_error(str(e), "Error Executing Report"))
            except Exception as e:
                self.root.after(0, lambda: self._on_report_error(f"{type(e).__name__}: {e}", "Unexpected Error"))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_report_success(self, result, meta, report_type_key, last_enriched, status_text, mode):
        """Called on main thread when worker finishes successfully."""
        self.progress_win.destroy()
        
        self.state.last_report_df = result
        self.state.last_meta = meta
        self.state.last_mode = mode
        self.state.last_report_type_key = report_type_key
        self.state.last_enriched = last_enriched

        self.state.original_df = result.copy()
        self.state.filtered_df = result.copy()

        self.table_view.show_table(result)
        self.set_status(status_text)
        
        # Enable Graph button if supported
        if mode == "Favorite Artist Trend" or mode == "New Music By Year":
            self.btn_show_graph.config(state="normal")
        else:
            self.btn_show_graph.config(state="disabled")

    def _on_report_error(self, error_msg, title):
        """Called on main thread when worker fails."""
        self.progress_win.destroy()
        messagebox.showerror(title, error_msg)
        self.set_status(f"Error: {error_msg}")

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
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_config(self, data: dict) -> None:
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


# ======================================================================
# Main entry point
# ======================================================================

if __name__ == "__main__":
    root = tk.Tk()
    app = BrainzMRIGUI(root)
    root.mainloop()