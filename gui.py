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

import reporting
import enrichment
from user import User, get_cache_root


def open_file_default(path: str) -> None:
    """Open a file using the OS default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def get_cached_usernames() -> list[str]:
    """
    Return a sorted list of cached usernames based on the user cache directory.
    """
    cache_root = get_cache_root()
    users_root = os.path.join(cache_root, "users")
    if not os.path.exists(users_root):
        return []
    names = []
    for entry in os.listdir(users_root):
        full = os.path.join(users_root, entry)
        if os.path.isdir(full):
            names.append(entry)
    return sorted(names)


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

        # Table/filtering state
        self.original_df = None
        self.filtered_df = None


class ReportEngine:
    """
    Encapsulates report generation logic.

    Responsible for:
    - Time range filtering
    - Recency filtering
    - Thresholding and Top N
    - Calling reporting functions
    - Optional enrichment
    """

    def __init__(self) -> None:
        self._handlers = {
            "By Artist": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "artist", "by": "total_tracks"},
                "status": "Artist report generated.",
            },
            "By Album": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "album", "by": "total_tracks"},
                "status": "Album report generated.",
            },
            "By Track": {
                "func": reporting.report_top,
                "kwargs": {"group_col": "track", "by": "total_tracks"},
                "status": "Track report generated.",
            },
            "All Liked Artists": {
                "func": reporting.report_artists_with_likes,
                "kwargs": {},
                "status": "Liked artists report generated.",
            },
            "Raw Listens": {
                "func": reporting.report_raw_listens,
                "kwargs": {},
                "status": "Raw listens displayed.",
            },
        }

    def get_status(self, mode: str) -> str:
        handler = self._handlers.get(mode)
        if not handler:
            return "Report generated."
        return handler.get("status", "Report generated.")

    def generate_report(
        self,
        base_df,
        mode: str,
        liked_mbids,
        *,
        time_start_days: int,
        time_end_days: int,
        rec_start_days: int,
        rec_end_days: int,
        min_listens: int,
        min_minutes: float,
        topn: int,
        do_enrich: bool,
        enrich_source: str,
    ):
        """
        Generate a report for the given mode and parameters.

        Returns
        -------
        result_df : DataFrame
        meta : dict | None
        report_type_key : str
        last_enriched : bool
        status_text : str
        """
        if base_df is None:
            raise ValueError("No listens data available.")

        df = base_df.copy()

        # Time range filter (on listens)
        if not (time_start_days == 0 and time_end_days == 0):
            df = reporting.filter_by_days(
                df,
                "listened_at",
                time_start_days,
                time_end_days,
            )

        # After time-range filtering, protect against empty results
        if df.empty:
            return (
                df,          # empty result
                None,        # no meta
                report_type_key,
                False,       # not enriched
                "No data available for the selected time range."
            )

        # Recency filter (skip for Raw Listens)
        if mode != "Raw Listens":
            if not (rec_start_days == 0 and rec_end_days == 0):
                now = datetime.now(timezone.utc)
                min_dt = now - timedelta(days=rec_end_days)
                max_dt = now - timedelta(days=rec_start_days)

                if mode == "By Artist":
                    entity_cols = ["artist"]
                elif mode == "By Album":
                    entity_cols = ["artist", "album"]
                elif mode == "By Track":
                    entity_cols = ["artist", "track_name"]
                else:
                    entity_cols = ["artist"]

                true_last = (
                    df.groupby(entity_cols)["listened_at"]
                    .max()
                    .reset_index()
                    .rename(columns={"listened_at": "true_last_listened"})
                )

                allowed = true_last[
                    (true_last["true_last_listened"] >= min_dt)
                    & (true_last["true_last_listened"] <= max_dt)
                ]

                df = df.merge(allowed[entity_cols], on=entity_cols, how="inner")

        handler = self._handlers.get(mode)
        if handler is None:
            raise ValueError(f"Unsupported report type: {mode}")

        func = handler["func"]
        kwargs = handler["kwargs"].copy()

        # Call appropriate reporting function
        if func is reporting.report_top:
            kwargs.update(
                {
                    "days": None,
                    "topn": topn,
                    "min_listens": min_listens,
                    "min_minutes": min_minutes,
                }
            )
            result, meta = func(df, **kwargs)

        elif func is reporting.report_artists_with_likes:
            if liked_mbids is None:
                liked_mbids = set()
            result, meta = func(
                df,
                liked_mbids,
                min_listens=min_listens,
                min_minutes=min_minutes,
                topn=topn,
            )

        elif func is reporting.report_raw_listens:
            result, meta = func(df, topn=topn)

        else:
            result, meta = func(df, **kwargs)

        # Determine report_type_key
        if mode == "By Artist":
            report_type_key = "artist"
        elif mode == "By Album":
            report_type_key = "album"
        elif mode == "By Track":
            report_type_key = "track"
        elif mode == "All Liked Artists":
            report_type_key = "liked_artists"
        else:
            report_type_key = "raw"

        # Optional enrichment (skip for Raw Listens)
        last_enriched = False
        if do_enrich and mode != "Raw Listens":
            # Inject username into the report DataFrame
            result = result.copy()
            result["_username"] = base_df["_username"].iloc[0]

            result = enrichment.enrich_report(
                result,
                report_type_key,
                enrich_source,
            )
            last_enriched = True

        status_text = self.get_status(mode)
        return result, meta, report_type_key, last_enriched, status_text


class ReportTableView:
    """
    Encapsulates table rendering, filtering, and sorting.

    Responsible for:
    - Rendering the DataFrame into a Treeview
    - Managing filter widgets
    - Applying regex filters
    - Sorting columns
    - Copying selection to clipboard
    """

    def __init__(self, root: tk.Tk, container: tk.Frame, state: GUIState) -> None:
        self.root = root
        self.container = container
        self.state = state

        self.filter_by_var = tk.StringVar(value="All")
        self.filter_entry: tk.Entry | None = None
        self.tree: ttk.Treeview | None = None

    def show_table(self, df):
        # Preserve existing filter text if any
        current_filter = ""
        if self.filter_entry is not None:
            current_filter = self.filter_entry.get()

        # Clear previous contents
        for widget in self.container.winfo_children():
            widget.destroy()

        # Filter bar
        filter_frame = tk.Frame(self.container)
        filter_frame.pack(fill="x", pady=5)

        tk.Label(filter_frame, text="Filter By:").pack(side="left", padx=(5, 2))
        filter_by_dropdown = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_by_var,
            state="readonly",
            width=18,
        )
        filter_by_dropdown.pack(side="left", padx=(0, 10))

        cols = list(df.columns)
        filter_by_dropdown["values"] = ["All"] + cols
        if self.filter_by_var.get() not in ["All"] + cols:
            self.filter_by_var.set("All")

        tk.Label(
            filter_frame,
            text='Filter (Supports Regex; Use ".*" for wildcards or "|" for OR):',
        ).pack(side="left", padx=5)

        self.filter_entry = tk.Entry(filter_frame, width=40)
        self.filter_entry.pack(side="left", padx=5)

        if current_filter:
            self.filter_entry.insert(0, current_filter)

        tk.Button(filter_frame, text="Filter", command=self.apply_filter).pack(
            side="left", padx=5
        )
        tk.Button(filter_frame, text="Clear Filter", command=self.clear_filter).pack(
            side="left", padx=5
        )

        self.filter_entry.bind("<Return>", lambda e: self.apply_filter())

        # Table container
        table_container = tk.Frame(self.container)
        table_container.pack(fill="both", expand=True)

        tree = ttk.Treeview(table_container, show="headings")
        tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        tree._sort_state = {}

        self.tree = tree
        tree.bind("<Control-c>", self.copy_selection_to_clipboard)
        tree.bind("<Control-C>", self.copy_selection_to_clipboard)

        tree["columns"] = list(df.columns)
        for col in df.columns:
            tree.heading(
                col, text=col, command=lambda c=col: self.sort_column(tree, df, c)
            )
            tree.column(col, width=150, minwidth=100, stretch=True, anchor="w")

        for _, row in df.iterrows():
            tree.insert("", "end", values=list(row))

    def sort_column(self, tree: ttk.Treeview, df, col: str) -> None:
        """Sort the Treeview by the given column."""
        descending = tree._sort_state.get(col, False)
        tree._sort_state[col] = not descending

        data = [(tree.set(k, col), k) for k in tree.get_children("")]

        try:
            data = [(float(v), k) for v, k in data]
        except ValueError:
            pass

        data.sort(reverse=tree._sort_state[col])

        for index, (_, k) in enumerate(data):
            tree.move(k, "", index)

        for c in df.columns:
            indicator = ""
            if c == col:
                indicator = " ▲" if not descending else " ▼"
            tree.heading(
                c,
                text=c + indicator,
                command=lambda c=c: self.sort_column(tree, df, c),
            )

    def apply_filter(self) -> None:
        """Apply a regex filter to the current report DataFrame."""
        if self.state.original_df is None or self.filter_entry is None:
            return

        pattern = self.filter_entry.get().strip()
        if not pattern:
            return

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            messagebox.showerror("Invalid Regex", "Your regex pattern is invalid.")
            return

        df = self.state.original_df.copy()
        col_choice = self.filter_by_var.get()

        if col_choice == "All":
            mask = df.apply(
                lambda row: row.astype(str).str.contains(regex, regex=True).any(),
                axis=1,
            )
        else:
            if col_choice not in df.columns:
                messagebox.showerror("Error", f"Column '{col_choice}' not found.")
                return
            mask = df[col_choice].astype(str).str.contains(regex, regex=True)

        self.state.filtered_df = df[mask]
        self.show_table(self.state.filtered_df)

    def clear_filter(self) -> None:
        if self.state.original_df is None or self.filter_entry is None:
            return
        self.state.filtered_df = self.state.original_df.copy()
        self.show_table(self.state.original_df)
        self.filter_entry.delete(0, tk.END)

    def copy_selection_to_clipboard(self, event=None):
        if self.tree is None:
            return "break"

        tree = self.tree
        selected = tree.selection()
        if not selected:
            return "break"

        rows = []
        for item in selected:
            values = tree.item(item, "values")
            rows.append("\t".join(str(v) for v in values))

        text = "\n".join(rows)

        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

        return "break"


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
        frm_user.pack(pady=10, fill="x")

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

        tk.Button(
            frm_user,
            text="Load From ZIP",
            command=self.load_from_zip,
        ).pack(side="left")

        self.lbl_user_status = tk.Label(frm_user, text="", fg="gray")
        self.lbl_user_status.pack(side="left", padx=10)

        # Input fields container
        frm_inputs = tk.Frame(root)
        frm_inputs.pack(pady=10)

        def add_labeled_entry(parent, label: str, default) -> tk.Entry:
            row = tk.Frame(parent)
            row.pack(anchor="w")
            tk.Label(row, text=label, width=32, anchor="w").pack(side="left")
            ent = tk.Entry(row, width=10)
            ent.insert(0, str(default))
            ent.pack(side="left")
            return ent

        # Time Range
        frm_time = tk.Frame(frm_inputs)
        frm_time.pack(fill="x", pady=5)

        lbl_time = tk.Label(frm_time, text="Time Range To Analyze (Days)")
        lbl_time.pack(anchor="center")

        row_time = tk.Frame(frm_time)
        row_time.pack(anchor="center")

        tk.Label(row_time, text="Start:", width=8).pack(side="left")
        self.ent_time_start = tk.Entry(row_time, width=10)
        self.ent_time_start.pack(side="left", padx=5)

        tk.Label(row_time, text="End:", width=8).pack(side="left")
        self.ent_time_end = tk.Entry(row_time, width=10)
        self.ent_time_end.pack(side="left", padx=5)

        self.ent_time_start.insert(0, "0")
        self.ent_time_end.insert(0, "9999")

        # Last Listened
        frm_last = tk.Frame(frm_inputs)
        frm_last.pack(fill="x", pady=5)

        lbl_last = tk.Label(frm_last, text="Last Listened Date (Days Ago)")
        lbl_last.pack(anchor="center")

        row_last = tk.Frame(frm_last)
        row_last.pack(anchor="center")

        tk.Label(row_last, text="Start:", width=8).pack(side="left")
        self.ent_last_start = tk.Entry(row_last, width=10)
        self.ent_last_start.pack(side="left", padx=5)

        tk.Label(row_last, text="End:", width=8).pack(side="left")
        self.ent_last_end = tk.Entry(row_last, width=10)
        self.ent_last_end.pack(side="left", padx=5)

        self.ent_last_start.insert(0, "0")
        self.ent_last_end.insert(0, "0")

        # Thresholds and Top N
        self.ent_topn = add_labeled_entry(
            frm_inputs, "Top N (Number Of Results, Default: 200):", 200
        )
        self.ent_min_listens = add_labeled_entry(
            frm_inputs, "Minimum Listens Threshold:", 10
        )
        self.ent_min_minutes = add_labeled_entry(
            frm_inputs, "Minimum Time Listened Threshold (Mins):", 15
        )

        # Enrichment controls
        self.do_enrich_var = tk.BooleanVar(value=False)
        chk_enrich = tk.Checkbutton(
            frm_inputs,
            text="Perform Genre Lookup (Enrich Report)",
            variable=self.do_enrich_var,
        )
        Hovertip(
            chk_enrich,
            "Add genre information to the report using MusicBrainz.\n"
            "Runs after all filters and sorting.\n"
            "May be slow if API lookup is enabled.",
        )
        chk_enrich.pack(anchor="w", pady=5)

        frm_enrich_source = tk.Frame(frm_inputs)
        frm_enrich_source.pack(fill="x", pady=2, anchor="w")

        tk.Label(
            frm_enrich_source,
            text="Genre Enrichment Source:",
            width=32,
            anchor="w",
        ).pack(side="left")

        self.enrich_source_var = tk.StringVar(value="Cache")
        self.cmb_enrich_source = ttk.Combobox(
            frm_enrich_source,
            textvariable=self.enrich_source_var,
            values=["Cache", "Query API (Slow)"],
            state="readonly",
            width=18,
        )
        self.cmb_enrich_source.pack(side="left")

        Hovertip(
            self.cmb_enrich_source,
            "Choose whether to use the local cache only or query the MusicBrainz API.\n"
            "API lookups are slower due to rate limiting.\n"
            "Cache is only available for items pulled previously via API.",
        )

        def toggle_enrich_source(*_):
            state = "readonly" if self.do_enrich_var.get() else "disabled"
            self.cmb_enrich_source.configure(state=state)

        self.do_enrich_var.trace_add("write", lambda *args: toggle_enrich_source())
        toggle_enrich_source()

        # Report type selection
        frm_type = tk.Frame(root)
        frm_type.pack(pady=10)

        tk.Label(frm_type, text="Report Type:").pack(side="left", padx=5)

        self.report_type = ttk.Combobox(
            frm_type,
            values=[
                "By Artist",
                "By Album",
                "By Track",
                "All Liked Artists",
                "Raw Listens",
            ],
            state="readonly",
        )
        self.report_type.current(0)
        self.report_type.pack(side="left")

        # Buttons
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

        self.status_bar.pack(fill="x", side="bottom")

        # Table viewer frame and view manager
        self.table_frame = tk.Frame(root)
        self.table_frame.pack(fill="both", expand=True)
        self.table_frame.pack_propagate(False)

        self.table_view = ReportTableView(self.root, self.table_frame, self.state)

        # Initialize users and auto-load last user if available
        self.refresh_user_list()
        cfg = self.load_config()
        last_user = cfg.get("last_user")
        if last_user and last_user in self.user_dropdown["values"]:
            self.user_var.set(last_user)
            self.load_user_from_cache(last_user)
            self.set_status(f"Auto-loaded user: {last_user}")
        else:
            self.set_status("Ready.")

    # -----------------------
    # Utility methods
    # -----------------------

    def set_status(self, text: str) -> None:
        self.status_var.set(text)
        self.status_bar.update_idletasks()

    def load_config(self) -> dict:
        """Load config.json if present, else return empty dict."""
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_config(self, data: dict) -> None:
        """Write config.json with the provided dictionary."""
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def refresh_user_list(self) -> None:
        """Refresh the list of cached users in the dropdown."""
        users = get_cached_usernames()
        self.user_dropdown["values"] = users
        if not users:
            self.user_var.set("")
            self.lbl_user_status.config(text="No cached users found.", fg="gray")

    # -----------------------
    # User loading
    # -----------------------

    def on_user_selected(self, event=None) -> None:
        username = self.user_var.get().strip()
        if not username:
            return
        self.load_user_from_cache(username)

    def load_user_from_cache(self, username: str) -> None:
        try:
            user = User.from_cache(username)
        except FileNotFoundError as e:
            messagebox.showerror("Error", str(e))
            self.set_status(f"Error: {str(e)}")
            return
        except Exception as e:
            messagebox.showerror("Unexpected Error", f"{type(e).__name__}: {e}")
            self.set_status("Error: Failed to load user from cache.")
            return

        self.state.user = user
        self.lbl_user_status.config(text=f"Loaded user: {username}", fg="black")

        cfg = self.load_config()
        cfg["last_user"] = username
        self.save_config(cfg)

        # Clear previous report
        self.state.last_report_df = None
        self.state.last_meta = None
        self.state.last_mode = None
        self.state.last_report_type_key = None
        self.state.last_enriched = False
        self.state.original_df = None
        self.state.filtered_df = None
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        self.set_status(f"User '{username}' loaded from cache.")

    def load_from_zip(self) -> None:
        """Create or update a user by ingesting a ListenBrainz ZIP."""
        path = filedialog.askopenfilename(
            title="Select ListenBrainz ZIP",
            filetypes=[("ZIP files", "*.zip")],
        )
        if not path:
            return

        try:
            user = User.from_listenbrainz_zip(path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load ZIP: {type(e).__name__}: {e}")
            self.set_status("Error: Failed to load ZIP.")
            return

        self.state.user = user
        username = user.username

        # Refresh dropdown and select this user
        self.refresh_user_list()
        if username not in self.user_dropdown["values"]:
            users = list(self.user_dropdown["values"]) + [username]
            self.user_dropdown["values"] = sorted(users)
        self.user_var.set(username)
        self.lbl_user_status.config(text=f"Loaded from ZIP: {username}", fg="black")

        cfg = self.load_config()
        cfg["last_user"] = username
        self.save_config(cfg)

        # Clear previous report
        self.state.last_report_df = None
        self.state.last_meta = None
        self.state.last_mode = None
        self.state.last_report_type_key = None
        self.state.last_enriched = False
        self.state.original_df = None
        self.state.filtered_df = None
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        self.set_status(f"User '{username}' created/updated from ZIP.")

    # -----------------------
    # Report generation
    # -----------------------

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
            messagebox.showerror(
                "Error", "Please load a user first (via 'Load From ZIP' or selecting an existing user)."
            )
            self.set_status("Error: No user loaded.")
            return

        mode = self.report_type.get()

        # Parse numeric inputs
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
            min_minutes = self._parse_float_field(
                self.ent_min_minutes, "Minimum time listened"
            )
            topn = self._parse_int_field(self.ent_topn, "Top N")
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            self.set_status(f"Error: {str(e)}")
            return

        do_enrich = self.do_enrich_var.get()
        enrich_source = self.enrich_source_var.get()

        base_df = self.state.user.get_listens().copy()
        base_df["_username"] = self.state.user.username
        liked_mbids = self.state.user.get_liked_mbids()

        # Generate report via engine
        try:
            result, meta, report_type_key, last_enriched, status_text = (
                self.report_engine.generate_report(
                    base_df,
                    mode,
                    liked_mbids,
                    time_start_days=time_start,
                    time_end_days=time_end,
                    rec_start_days=rec_start,
                    rec_end_days=rec_end,
                    min_listens=min_listens,
                    min_minutes=min_minutes,
                    topn=topn,
                    do_enrich=do_enrich,
                    enrich_source=enrich_source,
                )
            )
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            self.set_status(f"Error: {str(e)}")
            return
        except Exception as e:
            messagebox.showerror(
                "Unexpected Error", f"{type(e).__name__}: {e}"
            )
            self.set_status("Error: Unexpected error during report generation.")
            return

        # Save state
        self.state.last_report_df = result
        self.state.last_meta = meta
        self.state.last_mode = mode
        self.state.last_report_type_key = report_type_key
        self.state.last_enriched = last_enriched

        self.state.original_df = result.copy()
        self.state.filtered_df = result.copy()

        # Display
        self.table_view.show_table(result)
        self.set_status(status_text)

    # -----------------------
    # Saving reports
    # -----------------------

    def save_report(self) -> None:
        if self.state.last_report_df is None:
            messagebox.showerror("Error", "No report to save. Generate a report first.")
            self.set_status("Error: No report to save.")
            return

        if self.state.user is None:
            messagebox.showerror("Error", "No user loaded to associate with this report.")
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
            messagebox.showerror(
                "Error", f"Failed to save report: {type(e).__name__}: {e}"
            )
            self.set_status("Error: Failed to save report.")


if __name__ == "__main__":
    root = tk.Tk()
    app = BrainzMRIGUI(root)
    root.mainloop()