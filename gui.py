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
from user import (
    User,
    get_cache_root,
    get_cached_usernames,
    get_user_cache_dir,
)
from report_engine import ReportEngine


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

        # Table/filtering state
        self.original_df = None
        self.filtered_df = None


# ======================================================================
# User Editor Window (New User / Edit User)
# ======================================================================

class UserEditorWindow(tk.Toplevel):
    """
    A modal dialog for creating or editing a user.

    Supports:
    - App Username (letters/numbers only)
    - Last.fm Username
    - ListenBrainz Username
    - Choose ListenBrainz Zip (multi-ZIP, deferred ingestion)
    """

    def __init__(self, parent, existing_user: User | None, on_save_callback):
        super().__init__(parent)
        self.title("User Editor")
        self.resizable(False, False)
        self.parent = parent
        self.existing_user = existing_user
        self.on_save_callback = on_save_callback

        # Pending ZIPs selected during this session
        self.pending_zips = []

        # Build UI
        self._build_ui()

        # If editing, populate fields
        if existing_user:
            self._populate_from_user(existing_user)

        # Make modal
        self.transient(parent)
        self.grab_set()
        self.wait_window(self)

    # ------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------

    def _build_ui(self):
        frm = tk.Frame(self)
        frm.pack(padx=15, pady=15)

        # App Username
        tk.Label(frm, text="App Username (letters/numbers only):").grid(
            row=0, column=0, sticky="w"
        )
        self.ent_app_username = tk.Entry(frm, width=30)
        self.ent_app_username.grid(row=0, column=1, pady=3)

        # Last.fm Username
        tk.Label(frm, text="Last.fm Username:").grid(row=1, column=0, sticky="w")
        self.ent_lastfm = tk.Entry(frm, width=30)
        self.ent_lastfm.grid(row=1, column=1, pady=3)

        # ListenBrainz Username
        tk.Label(frm, text="ListenBrainz Username:").grid(row=2, column=0, sticky="w")
        self.ent_listenbrainz = tk.Entry(frm, width=30)
        self.ent_listenbrainz.grid(row=2, column=1, pady=3)

        # ZIP selection
        tk.Label(frm, text="Previously Ingested ZIPs:").grid(
            row=3, column=0, sticky="nw", pady=(10, 0)
        )
        self.lst_existing_zips = tk.Listbox(frm, width=50, height=5)
        self.lst_existing_zips.grid(row=3, column=1, pady=(10, 0))

        tk.Label(frm, text="New ZIPs to Ingest:").grid(
            row=4, column=0, sticky="nw", pady=(10, 0)
        )
        self.lst_pending_zips = tk.Listbox(frm, width=50, height=5)
        self.lst_pending_zips.grid(row=4, column=1, pady=(10, 0))

        btn_choose_zip = tk.Button(
            frm,
            text="Choose ListenBrainz Zip",
            command=self._choose_zip,
            width=25,
        )
        btn_choose_zip.grid(row=5, column=1, sticky="w", pady=5)

        # Save / Cancel
        frm_buttons = tk.Frame(frm)
        frm_buttons.grid(row=6, column=0, columnspan=2, pady=15)

        tk.Button(
            frm_buttons,
            text="Save User",
            command=self._save_user,
            width=15,
            bg="#4CAF50",
            fg="white",
        ).pack(side="left", padx=5)

        tk.Button(
            frm_buttons,
            text="Cancel",
            command=self.destroy,
            width=15,
            bg="#F44336",
            fg="white",
        ).pack(side="left", padx=5)

    # ------------------------------------------------------------
    # Populate fields for Edit User
    # ------------------------------------------------------------

    def _populate_from_user(self, user: User):
        self.ent_app_username.insert(0, user.username)
        self.ent_app_username.config(state="readonly")

        self.ent_lastfm.insert(0, user.get_lastfm_username() or "")
        self.ent_listenbrainz.insert(0, user.get_listenbrainz_username() or "")

        # Existing ZIPs (read-only)
        zips = user.sources.get("listenbrainz_zips", [])
        for z in zips:
            self.lst_existing_zips.insert(
                tk.END, f"{z.get('path')} (ingested {z.get('ingested_at')})"
            )

    # ------------------------------------------------------------
    # ZIP selection
    # ------------------------------------------------------------

    def _choose_zip(self):
        path = filedialog.askopenfilename(
            title="Select ListenBrainz ZIP",
            filetypes=[("ZIP files", "*.zip")],
        )
        if not path:
            return

        self.pending_zips.append(path)
        self.lst_pending_zips.insert(tk.END, path)

    # ------------------------------------------------------------
    # Save User
    # ------------------------------------------------------------

    def _save_user(self):
        app_username = self.ent_app_username.get().strip()
        lastfm_username = self.ent_lastfm.get().strip() or None
        listenbrainz_username = self.ent_listenbrainz.get().strip() or None

        # Validate app username
        if not app_username:
            messagebox.showerror("Error", "App Username is required.")
            return
        if not app_username.isalnum():
            messagebox.showerror(
                "Error", "App Username must contain only letters and numbers."
            )
            return

        # If editing, update existing user
        if self.existing_user:
            user = self.existing_user
            user.update_sources(lastfm_username, listenbrainz_username)

            # Ingest new ZIPs
            for zip_path in self.pending_zips:
                try:
                    user.ingest_listenbrainz_zip(zip_path)
                except Exception as e:
                    messagebox.showerror(
                        "Error Ingesting ZIP",
                        f"Failed to ingest ZIP '{zip_path}': {type(e).__name__}: {e}",
                    )
                    return

            self.on_save_callback(user.username)
            self.destroy()
            return

        # Creating a new user
        try:
            user = User.from_sources(
                username=app_username,
                lastfm_username=lastfm_username,
                listenbrainz_username=listenbrainz_username,
                listenbrainz_zips=[],
            )
        except Exception as e:
            messagebox.showerror(
                "Error Creating User",
                f"Failed to create user: {type(e).__name__}: {e}",
            )
            return

        # Ingest ZIPs
        for zip_path in self.pending_zips:
            try:
                user.ingest_listenbrainz_zip(zip_path)
            except Exception as e:
                messagebox.showerror(
                    "Error Ingesting ZIP",
                    f"Failed to ingest ZIP '{zip_path}': {type(e).__name__}: {e}",
                )
                return

        self.on_save_callback(user.username)
        self.destroy()

# ======================================================================
# Report Table View (unchanged from v2026.01.06)
# ======================================================================

class ReportTableView:
    """
    Encapsulates table rendering, filtering, and sorting.
    """

    def __init__(self, root: tk.Tk, container: tk.Frame, state: GUIState) -> None:
        self.root = root
        self.container = container
        self.state = state

        # Filter state
        self.filter_by_var = tk.StringVar(value="All")
        self.filter_entry: tk.Entry | None = None

        # UI containers
        self.filter_frame: tk.Frame | None = None
        self.table_container: tk.Frame | None = None

        # Treeview
        self.tree: ttk.Treeview | None = None

        # Build initial filter bar
        self.build_filter_bar()

    # ------------------------------------------------------------
    # Filter Bar Construction
    # ------------------------------------------------------------

    def build_filter_bar(self):
        """Create the filter bar UI and store widget references."""

        if self.filter_frame and self.filter_frame.winfo_exists():
            self.filter_frame.destroy()

        self.filter_frame = tk.Frame(self.container)
        self.filter_frame.pack(pady=5)

        tk.Label(self.filter_frame, text="Filter By:").pack(side="left", padx=(5, 2))

        self.filter_by_dropdown = ttk.Combobox(
            self.filter_frame,
            textvariable=self.filter_by_var,
            state="readonly",
            width=18,
        )
        self.filter_by_dropdown.pack(side="left", padx=(0, 10))

        tk.Label(
            self.filter_frame,
            text='Filter (Supports Regex; Use ".*" for wildcards or "|" for OR):',
        ).pack(side="left", padx=5)

        self.filter_entry = tk.Entry(self.filter_frame, width=40)
        self.filter_entry.pack(side="left", padx=5)

        tk.Button(self.filter_frame, text="Filter", command=self.apply_filter).pack(
            side="left", padx=5
        )
        tk.Button(self.filter_frame, text="Clear Filter", command=self.clear_filter).pack(
            side="left", padx=5
        )

        self.filter_entry.bind("<Return>", lambda e: self.apply_filter())

    # ------------------------------------------------------------
    # Table Rendering
    # ------------------------------------------------------------

    def show_table(self, df):

        if not self.filter_entry or not self.filter_entry.winfo_exists():
            self.build_filter_bar()

        current_filter = ""
        if self.filter_entry and self.filter_entry.winfo_exists():
            current_filter = self.filter_entry.get()

        cols = list(df.columns)
        self.filter_by_dropdown["values"] = ["All"] + cols
        if self.filter_by_var.get() not in ["All"] + cols:
            self.filter_by_var.set("All")

        self.filter_entry.delete(0, tk.END)
        if current_filter:
            self.filter_entry.insert(0, current_filter)

        if not self.table_container or not self.table_container.winfo_exists():
            self.table_container = tk.Frame(self.container)
            self.table_container.pack(fill="both", expand=True)
        else:
            for widget in self.table_container.winfo_children():
                widget.destroy()

        tree = ttk.Treeview(self.table_container, show="headings")
        tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            self.table_container, orient="vertical", command=tree.yview
        )
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        tree._sort_state = {}
        self.tree = tree

        tree.bind("<Control-c>", self.copy_selection_to_clipboard)
        tree.bind("<Control-C>", self.copy_selection_to_clipboard)

        tree["columns"] = cols
        for col in cols:
            tree.heading(
                col, text=col, command=lambda c=col: self.sort_column(tree, df, c)
            )
            tree.column(col, width=150, minwidth=100, stretch=True, anchor="w")

        for _, row in df.iterrows():
            tree.insert("", "end", values=list(row))

    # ------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------

    def sort_column(self, tree: ttk.Treeview, df, col: str) -> None:
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

    # ------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------

    def apply_filter(self) -> None:
        if self.state.original_df is None or self.filter_entry is None:
            return

        pattern = self.filter_entry.get().strip()
        if not pattern:
            return

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            messagebox.showerror("Error In Regex", "Your regex pattern is invalid.")
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
                messagebox.showerror("Error Applying Filter", f"Column '{col_choice}' not found.")
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

    # ------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------

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
        tk.Button(
            frm_user,
            text="New User",
            command=self.new_user,
        ).pack(side="left", padx=5)

        tk.Button(
            frm_user,
            text="Edit User",
            command=self.edit_user,
        ).pack(side="left", padx=5)

        self.lbl_user_status = tk.Label(frm_user, text="", fg="gray")
        self.lbl_user_status.pack(side="left", padx=10)

        # Input fields container
        frm_inputs = tk.Frame(root)
        frm_inputs.pack(pady=10)

        # ------------------------------------------------------------
        # Helper functions for labeled entries
        # ------------------------------------------------------------
        def add_labeled_entry(parent, label: str, default) -> tk.Entry:
            row = tk.Frame(parent)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, width=27, anchor="w").pack(side="left")
            ent = tk.Entry(row, width=8)
            ent.insert(0, str(default))
            ent.pack(side="left")
            return ent

        def add_labeled_double_entry(parent, label: str, default1, default2):
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

        # ------------------------------------------------------------
        # Time Range Filters
        # ------------------------------------------------------------
        (self.ent_time_start, self.ent_time_end,
            self.time_frame) = add_labeled_double_entry(
                frm_inputs,
                "Time Range To Analyze (Days Ago)",
                0, 0
            )

        (self.ent_last_start, self.ent_last_end,
            self.last_frame) = add_labeled_double_entry(
                frm_inputs,
                "Last Listened Date (Days Ago)",
                0, 0
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
        self.ent_topn = add_labeled_entry(
            frm_inputs, "Top N (Number Of Results):", 200
        )
        self.ent_min_listens = add_labeled_entry(
            frm_inputs, "Number of Listens Threshold:", 10
        )
        self.ent_min_minutes = add_labeled_entry(
            frm_inputs, "Minutes Listened Threshold:", 15
        )
        self.ent_min_likes = add_labeled_entry(
            frm_inputs, "Minimum Likes Threshold:", 0
        )

        Hovertip(
            self.ent_topn,
            "Number of results to return.\nDefault: 200 results",
            hover_delay=500,
        )
        Hovertip(
            self.ent_min_listens,
            "Minimum number of listens.\nWorks as an OR with minimum minutes.\nDefault: 10 listens",
            hover_delay=500,
        )
        Hovertip(
            self.ent_min_minutes,
            "Minimum number of minutes listened.\nWorks as an OR with minimum listens.\nDefault: 15 minutes",
            hover_delay=500,
        )
        Hovertip(
            self.ent_min_likes,
            "Minimum number of unique liked tracks.\nDefault: 0 (disabled).",
            hover_delay=500,
        )
        
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

        def toggle_enrich_source(*_):
            state = "readonly" if self.do_enrich_var.get() else "disabled"
            self.cmb_enrich_source.configure(state=state)

        self.do_enrich_var.trace_add("write", lambda *args: toggle_enrich_source())
        toggle_enrich_source()

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
                "New Music By Year",
                "Raw Listens",
            ],
            state="readonly",
        )
        self.report_type.current(0)
        self.report_type.pack(side="left")

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

        self.status_bar.pack(fill="x", side="bottom")

        # ------------------------------------------------------------
        # Table viewer frame and view manager
        # ------------------------------------------------------------
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
            messagebox.showerror(
                "Error Loading User",
                f"Failed to load user '{username}': {type(e).__name__}: {e}",
            )
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
            messagebox.showerror(
                "Error Loading User (Unknown)", f"{type(e).__name__}: {e}"
            )
            self.set_status("Error: Failed to load user.")
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

        self.set_status(f"User '{username}' loaded.")

    # ==================================================================
    # Report Generation
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
            messagebox.showerror(
                "Error", "Please load or create a user first."
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
            min_likes = self._parse_int_field(self.ent_min_likes, "Minimum likes")
            topn = self._parse_int_field(self.ent_topn, "Top N")
        except ValueError as e:
            messagebox.showerror("Error With Filter Input", str(e))
            self.set_status(f"Error With Filter Input: {str(e)}")
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
                    min_likes=min_likes,
                    topn=topn,
                    do_enrich=do_enrich,
                    enrich_source=enrich_source,
                )
            )
        except ValueError as e:
            messagebox.showerror("Error Executing Report", str(e))
            self.set_status(f"Error Executing Report: {str(e)}")
            return
        except Exception as e:
            messagebox.showerror(
                "Unexpected Error Executing Report", f"{type(e).__name__}: {e}"
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
            messagebox.showerror(
                "Error", f"Failed to save report: {type(e).__name__}: {e}"
            )
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
        