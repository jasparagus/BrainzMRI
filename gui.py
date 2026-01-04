"""
gui.py
Tkinter GUI for BrainzMRI, using parsing/reporting/enrichment modules.
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

import parsing
import reporting
import enrichment


def open_file_default(path: str) -> None:
    """Open a file using the OS default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class BrainzMRIGUI:
    """
    Tkinter GUI wrapper for BrainzMRI.
    Handles ZIP selection, report generation, filtering, and table display.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BrainzMRI - ListenBrainz Metadata Review Instrument")

        # Build main window
        self.root.geometry("1000x700")
        self.root.minsize(1000, 700)
        self.root.resizable(True, True)
        self.root.update_idletasks()

        self.zip_path = None
        self.df = None
        self.feedback = None

        self.last_result = None
        self.last_meta = None
        self.last_mode = None
        self.last_report_type_key = None
        self.last_enriched = False

        # Report handlers
        self.report_handlers = {
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
        }

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

        # ZIP selection
        frm_zip = tk.Frame(root)
        frm_zip.pack(pady=10)

        tk.Button(frm_zip, text="Select ListenBrainz ZIP", command=self.select_zip).pack()

        self.lbl_zip = tk.Label(frm_zip, text="No file selected", fg="gray")
        self.lbl_zip.pack(pady=5)

        last = self.load_config().get("last_zip")
        if last and os.path.exists(last):
            self.zip_path = last
            self.lbl_zip.config(text=os.path.basename(last), fg="black")

            user_info, feedback, listens = parsing.parse_listenbrainz_zip(last)
            self.feedback = feedback
            self.df = parsing.normalize_listens(listens, last)

            self.set_status(f"Auto-loaded: {os.path.basename(last)}")
        else:
            self.set_status("Ready.")

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

        # Table viewer frame
        self.table_frame = tk.Frame(root)
        self.table_frame.pack(fill="both", expand=True)
        self.table_frame.pack_propagate(False)

        # Filter state
        self.original_df = None
        self.filtered_df = None
        self.filter_by_var = tk.StringVar(value="All")

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

    # -----------------------
    # Data loading
    # -----------------------

    def select_zip(self) -> None:
        path = filedialog.askopenfilename(
            title="Select ListenBrainz ZIP",
            filetypes=[("ZIP files", "*.zip")],
        )
        if not path:
            return

        cfg = self.load_config()
        cfg["last_zip"] = path
        self.save_config(cfg)

        self.lbl_zip.config(text=os.path.basename(path), fg="black")

        user_info, feedback, listens = parsing.parse_listenbrainz_zip(path)
        self.feedback = feedback
        self.df = parsing.normalize_listens(listens, path)

        self.zip_path = path
        self.set_status("Zip loaded.")

    # -----------------------
    # Report generation
    # -----------------------

    def run_report(self) -> None:
        if self.df is None:
            messagebox.showerror("Error", "Please select a ListenBrainz ZIP file first.")
            self.set_status("Error: Please select a ListenBrainz ZIP file first.")
            return

        df = self.df.copy()

        # Determine entity column(s) for recency filtering
        mode = self.report_type.get()
        if mode == "By Artist":
            entity_cols = ["artist"]
        elif mode == "By Album":
            entity_cols = ["artist", "album"]
        elif mode == "By Track":
            entity_cols = ["artist", "track_name"]
        else:
            entity_cols = ["artist"]  # Liked Artists uses artist only

        # Time range filter on raw listens
        try:
            t_start = int(self.ent_time_start.get())
            t_end = int(self.ent_time_end.get())
            time_start = min(t_start, t_end)
            time_end = max(t_start, t_end)
            if not (time_start == 0 and time_end == 0):
                df = reporting.filter_by_days(df, "listened_at", time_start, time_end)
        except ValueError:
            messagebox.showerror("Error", "Time range must be numeric.")
            self.set_status("Error: Time range must be numeric.")
            return
        except Exception as e:
            messagebox.showerror(
                "Unexpected Error in Time Range", f"{type(e).__name__}: {e}"
            )
            self.set_status("Error: Unexpected Error in Time Range.")
            return

        # Recency filter (entity-level exclusion)
        try:
            l_start = int(self.ent_last_start.get())
            l_end = int(self.ent_last_end.get())
            rec_start = min(l_start, l_end)
            rec_end = max(l_start, l_end)

            if not (rec_start == 0 and rec_end == 0):
                now = datetime.now(timezone.utc)
                min_dt = now - timedelta(days=rec_end)
                max_dt = now - timedelta(days=rec_start)

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

        except ValueError:
            messagebox.showerror("Error", "Last listened range must be numeric.")
            self.set_status("Error: Last listened range must be numeric.")
            return
        except Exception as e:
            messagebox.showerror(
                "Unexpected Error in Last Listened", f"{type(e).__name__}: {e}"
            )
            self.set_status("Error: Unexpected Error in Last Listened.")
            return

        # Thresholds and Top N
        try:
            min_listens = int(self.ent_min_listens.get())
            min_minutes = float(self.ent_min_minutes.get())
            topn = int(self.ent_topn.get())
        except Exception:
            messagebox.showerror("Error", "Invalid numeric filter values.")
            self.set_status("Error: Invalid numeric filter values.")
            return

        mode = self.report_type.get()
        handler = self.report_handlers.get(mode)
        if handler is None:
            messagebox.showerror("Error", "Unsupported report type.")
            self.set_status("Error: Unsupported report type.")
            return

        func = handler["func"]
        kwargs = handler["kwargs"].copy()

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
            liked_mbids = parsing.load_feedback(self.feedback)
            result, meta = func(
                df,
                liked_mbids,
                min_listens=min_listens,
                min_minutes=min_minutes,
                topn=topn,
            )
        else:
            result, meta = func(df, **kwargs)

        # Optional enrichment
        self.last_enriched = False
        report_type_key = (
            "artist"
            if mode == "By Artist"
            else "album"
            if mode == "By Album"
            else "track"
            if mode == "By Track"
            else "liked_artists"
        )

        if self.do_enrich_var.get():
            if not self.zip_path:
                messagebox.showerror(
                    "Error", "Cannot perform enrichment without a ZIP path."
                )
                self.set_status("Error: No ZIP path for enrichment.")
                return

            source = self.enrich_source_var.get()
            result = enrichment.enrich_report(result, report_type_key, source, self.zip_path)
            self.last_enriched = True

        # Save state
        self.last_result = result
        self.last_meta = meta
        self.last_mode = mode
        self.last_report_type_key = report_type_key

        # Initialize filter state
        self.original_df = result.copy()
        self.filtered_df = result.copy()

        # Display
        self.show_table(result)
        self.set_status(handler["status"])

    # -----------------------
    # Saving reports
    # -----------------------

    def save_report(self) -> None:
        if self.last_result is None:
            messagebox.showerror("Error", "No report to save. Generate a report first.")
            self.set_status("Error: No report to save.")
            return

        try:
            if self.last_meta is None:
                report_name = self.last_mode.replace(" ", "_")
                filepath = reporting.save_report(
                    self.last_result,
                    self.zip_path,
                    report_name=report_name,
                )
            else:
                filepath = reporting.save_report(
                    self.last_result,
                    self.zip_path,
                    meta=self.last_meta,
                )

            open_file_default(filepath)
            self.set_status(f"{self.last_mode} report saved and opened.")
        except Exception as e:
            messagebox.showerror(
                "Error", f"Failed to save report: {type(e).__name__}: {e}"
            )
            self.set_status("Error: Failed to save report.")

    # -----------------------
    # Table and filtering
    # -----------------------

    def show_table(self, df):
        # Preserve existing filter text if any
        try:
            current_filter = self.filter_entry.get()
        except AttributeError:
            current_filter = ""

        # Clear previous contents
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        # Filter bar
        filter_frame = tk.Frame(self.table_frame)
        filter_frame.pack(fill="x", pady=5)

        tk.Label(filter_frame, text="Filter By:").pack(side="left", padx=(5, 2))
        self.filter_by_dropdown = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_by_var,
            state="readonly",
            width=18,
        )
        self.filter_by_dropdown.pack(side="left", padx=(0, 10))

        cols = list(df.columns)
        self.filter_by_dropdown["values"] = ["All"] + cols
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
        container = tk.Frame(self.table_frame)
        container.pack(fill="both", expand=True)

        tree = ttk.Treeview(container, show="headings")
        tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
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
        if self.original_df is None:
            return

        pattern = self.filter_entry.get().strip()
        if not pattern:
            return

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            messagebox.showerror("Invalid Regex", "Your regex pattern is invalid.")
            return

        df = self.original_df.copy()
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

        self.filtered_df = df[mask]
        self.show_table(self.filtered_df)

    def clear_filter(self) -> None:
        if self.original_df is None:
            return
        self.filtered_df = self.original_df.copy()
        self.show_table(self.original_df)
        self.filter_entry.delete(0, tk.END)

    def copy_selection_to_clipboard(self, event=None):
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


if __name__ == "__main__":
    root = tk.Tk()
    app = BrainzMRIGUI(root)
    root.mainloop()