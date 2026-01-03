"""
BrainzMRI_GUI.py
============================================================
A standalone GUI wrapper for ParseListens.py
A Python GUI module that wraps analysis code from ParseListens.py.
This GUI:
- Lets the user select a ZIP file
- Lets the user enter:
- Time Range (days ago)
- Minimum tracks
- Minimum minutes
- Last-listened range (days ago)
- Top N
- Lets the user choose:
- By Artist
- By Album
- By Track
- All Liked Artists
- Enriched Artist Report
- Runs the appropriate report
- Saves output using your existing save_report() function
- Calls your existing functions without modifying them
============================================================
# TODO (Future Improvements)
# 1. Filter-By-Column Enhancement
#    Add a "Filter By" dropdown next to the filter entry.
#    Options: "All" + list of current table column headers.
#    Behavior:
#       - If "All": apply regex across all columns (current behavior).
#       - Else: apply regex only to the selected column.
#    Requirements:
#       - Populate dropdown after show_table() builds the Treeview.
#       - Update apply_filter() to respect the selected column.
# 2. UI Layout Abstraction
#    Several UI sections repeat the same pattern (Frame + Label + Entry).
#    Create helper functions to reduce boilerplate and improve readability.
# 3. show_table() Decomposition
#    show_table() currently handles:
#       - clearing the frame
#       - building the filter bar
#       - building the table container
#       - creating the Treeview
#       - wiring sorting
#       - inserting rows
#    Break into smaller helpers:
#       build_filter_bar(), build_table_container(), populate_table()
# 4. run_report() Decomposition
#    run_report() still handles multiple responsibilities:
#       - parsing inputs
#       - applying time filters
#       - dispatching report functions
#       - applying recency filters
#       - saving state
#       - rendering the table
#    Consider splitting into:
#       parse_time_range(), parse_thresholds(),
#       generate_report(), finalize_report()
============================================================
"""
import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from datetime import datetime, timedelta, timezone
from idlelib.tooltip import Hovertip
import os
import subprocess
import sys

import ParseListens as core

def open_file_default(path):
    """Open a file using the OS default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

# GUI Application
class BrainzMRIGUI:
    """
    Tkinter GUI wrapper for ParseListens.py.
    Handles ZIP selection, report generation, filtering, and table display.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("BrainzMRI - ListenBrainz Metadata Review Instrument")
        
        # Build Main Window
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
        
        # Define a lookup dictionary for reporting
        self.report_handlers = {
            "By Artist": {
                "func": core.report_top,
                "kwargs": {"group_col": "artist", "by": "total_tracks"},
                "status": "Artist report generated."
            },
            "By Album": {
                "func": core.report_top,
                "kwargs": {"group_col": "album", "by": "total_tracks"},
                "status": "Album report generated."
            },
            "By Track": {
                "func": core.report_top,
                "kwargs": {"group_col": "track", "by": "total_tracks"},
                "status": "Track report generated."
            },
            "All Liked Artists": {
                "func": core.report_artists_with_likes,
                "kwargs": {},  # special case handled below
                "status": "Liked artists report generated."
            },
            "Enriched Artist Report": {
                "func": "enriched",  # special case
                "kwargs": {},
                "status": "Enriched artist report (with genres) generated."
            }
        }
        
        # Status Bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready.")

        self.status_bar = tk.Label(
            root,
            textvariable=self.status_var,
            bd=1,
            relief="sunken",
            anchor="center",          # center the text
            font=("Segoe UI", 11)     # larger, cleaner font
        )
        
        # ZIP File Selection
        frm_zip = tk.Frame(root)
        frm_zip.pack(pady=10)

        tk.Button(frm_zip, text="Select ListenBrainz ZIP", command=self.select_zip).pack()

        self.lbl_zip = tk.Label(frm_zip, text="No file selected", fg="gray")
        self.lbl_zip.pack(pady=5)

        last = self.load_config().get("last_zip")
        if last and os.path.exists(last):
            self.zip_path = last
            self.lbl_zip.config(text=os.path.basename(last), fg="black")

            user_info, feedback, listens = core.parse_listenbrainz_zip(last)
            self.feedback = feedback
            self.df = core.normalize_listens(listens, last)

            self.set_status(f"Auto-loaded: {os.path.basename(last)}")
        else:
            self.set_status("Ready.")
        
        # Input Fields
        frm_inputs = tk.Frame(root)
        frm_inputs.pack(pady=10)

        def add_labeled_entry(parent, label, default):
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
        lbl_time.pack(anchor="center")   # <-- centers the label

        row_time = tk.Frame(frm_time)
        row_time.pack(anchor="center")   # <-- centers the Start/End row

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
        
        self.ent_topn         = add_labeled_entry(frm_inputs, "Top N (Number Of Results, e.g. 100):", 200)
        self.ent_min_tracks   = add_labeled_entry(frm_inputs, "Min. Tracks Listened Threshold:", 15)
        self.ent_min_minutes  = add_labeled_entry(frm_inputs, "Min. Minutes Listened Threshold:", 30)

        # Use AP or Cache Only For Enriched Artist Report
        self.use_api_var = tk.BooleanVar(value=True)
        chk_api = tk.Checkbutton(
            frm_inputs,
            text="Do MusicBrainz Genre Lookup (Slow)?",
            variable=self.use_api_var
        )
        Hovertip(chk_api, "If checked: query MusicBrainz.\nIf unchecked: use cache only.")
        chk_api.pack(anchor="w", pady=5)
        
        # Dropdown for report type
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
                "Enriched Artist Report"
            ],
            state="readonly"
        )
        self.report_type.current(0)
        self.report_type.pack(side="left")       
        
        # Analyze / Save Buttons
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)

        tk.Button(
            btn_frame,
            text="Generate Report",
            command=self.run_report,
            bg="#4CAF50",
            fg="white",
            width=16
        ).pack(side="left", padx=5)

        tk.Button(
            btn_frame,
            text="Save Report",
            command=self.save_report,
            bg="#2196F3",
            fg="white",
            width=16
        ).pack(side="left", padx=5)
        
        
        self.status_bar.pack(fill="x", side="bottom")

        # Table Viewer Frame
        self.table_frame = tk.Frame(root)
        self.table_frame.pack(fill="both", expand=True)
        self.table_frame.pack_propagate(False)

        # Filter state
        self.original_df = None
        self.filtered_df = None

    def set_status(self, text):
        self.status_var.set(text)
        self.status_bar.update_idletasks()
    
    def load_config(self):
        """Load config.json if present, else return empty dict."""
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except:
            pass
        return {}

    def save_config(self, data):
        """Write config.json with the provided dictionary."""
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except:
            pass    
    
    def select_zip(self):
        path = filedialog.askopenfilename(
            title="Select ListenBrainz ZIP",
            filetypes=[("ZIP files", "*.zip")]
        )
        if not path:
            return

        # Save to config
        cfg = self.load_config()
        cfg["last_zip"] = path
        self.save_config(cfg)

        # Update label
        self.lbl_zip.config(text=os.path.basename(path), fg="black")

        # Load data
        user_info, feedback, listens = core.parse_listenbrainz_zip(path)
        self.feedback = feedback
        self.df = core.normalize_listens(listens, path)

        self.zip_path = path
        self.set_status("Zip loaded.")

    def apply_recency_filter(self, result):
        try:
            l_start = int(self.ent_last_start.get())
            l_end   = int(self.ent_last_end.get())

            rec_start = min(l_start, l_end)
            rec_end   = max(l_start, l_end)

            # (0,0) => All time, skip recency filter
            if rec_start == 0 and rec_end == 0:
                return result

            now = datetime.now(timezone.utc)
            min_dt = now - timedelta(days=rec_end)
            max_dt = now - timedelta(days=rec_start)

            mask = (result["last_listened"] >= min_dt) & (result["last_listened"] <= max_dt)
            return result[mask].copy()

        except ValueError:
            messagebox.showerror("Error", "Last listened range must be numeric.")
            self.set_status("Error: Last listened range must be numeric.")
            return result
        except Exception as e:
            messagebox.showerror("Unexpected Error in Last Listened", f"{type(e).__name__}: {e}")
            self.set_status("Error: Unexpected Error in Last Listened.")
            return result

    def run_report(self):
        if self.df is None:
            messagebox.showerror("Error", "Please select a ListenBrainz ZIP file first.")
            self.set_status("Error: Please select a ListenBrainz ZIP file first.")
            return

        df = self.df.copy()

        # Apply time range filter (pre-grouping)
        try:
            t_start = int(self.ent_time_start.get())
            t_end   = int(self.ent_time_end.get())

            time_start = min(t_start, t_end)
            time_end   = max(t_start, t_end)
            time_range = (time_start, time_end)

            if not (time_start == 0 and time_end == 0):
                df = core.filter_by_days(df, "listened_at", time_start, time_end)

        except ValueError:
            messagebox.showerror("Error", "Time range must be numeric.")
            self.set_status("Error: Time range must be numeric.")
            return
        except Exception as e:
            messagebox.showerror("Unexpected Error in Time Range", f"{type(e).__name__}: {e}")
            self.set_status("Error: Unexpected Error in Time Range.")
            return

        # Read thresholds
        try:
            min_tracks   = int(self.ent_min_tracks.get())
            min_minutes  = float(self.ent_min_minutes.get())
        except:
            messagebox.showerror("Error", "Invalid numeric filter values.")
            self.set_status("Error: Invalid numeric filter values.")
            return

        mode = self.report_type.get()
        topn = int(self.ent_topn.get())
        
        mode = self.report_type.get()
        handler = self.report_handlers.get(mode)

        if handler is None:
            messagebox.showerror("Error", "Unsupported report type.")
            self.set_status("Error: Unsupported report type.")
            return

        # Special case: enriched report
        if handler["func"] == "enriched":
            artist_report = core.report_artists_threshold(
                df,
                mins=min_minutes,
                tracks=min_tracks
            )
            out_path, enriched = core.enrich_report_with_genres(
                artist_report,
                self.zip_path,
                use_api=self.use_api_var.get()
            )
            result = enriched
            meta = None

        else:
            # Normal reports
            func = handler["func"]
            kwargs = handler["kwargs"].copy()

            # Add shared parameters
            if func is core.report_top:
                kwargs.update({"days": time_range, "topn": topn})

            if func is core.report_artists_with_likes:
                result, meta = func(df, self.feedback)
            else:
                result, meta = func(df, **kwargs)

        # Apply recency filter
        result = self.apply_recency_filter(result)

        # Save state
        self.last_result = result
        self.last_meta = meta
        self.last_mode = mode

        # Initialize filter state
        self.original_df = result.copy()
        self.filtered_df = result.copy()

        # Display
        self.show_table(result)
        self.set_status(handler["status"])
        return
            
    def save_report(self):
        if self.last_result is None:
            messagebox.showerror("Error", "No report to save. Generate a report first.")
            self.set_status("Error: No report to save.")
            return

        try:
            if self.last_mode == "Enriched Artist Report":
                # No meta; use explicit report_name
                filepath = core.save_report(
                    self.last_result,
                    self.zip_path,
                    report_name="Enriched_Artist_Report"
                )
            else:
                filepath = core.save_report(
                    self.last_result,
                    self.zip_path,
                    meta=self.last_meta
                )

            open_file_default(filepath)
            self.set_status(f"{self.last_mode} report saved and opened.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save report: {type(e).__name__}: {e}")
            self.set_status("Error: Failed to save report.")
    
    def show_table(self, df):

        # Clear old table + filter bar
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        # Filter bar
        filter_frame = tk.Frame(self.table_frame)
        filter_frame.pack(fill="x", pady=5)

        tk.Label(
            filter_frame,
            text='Filter Results (Supports Regex; Use ".*" for Wildcards or "|" for OR):'
        ).pack(side="left", padx=5)

        self.filter_entry = tk.Entry(filter_frame, width=40)
        self.filter_entry.pack(side="left", padx=5)

        tk.Button(
            filter_frame,
            text="Filter",
            command=self.apply_filter
        ).pack(side="left", padx=5)

        tk.Button(
            filter_frame,
            text="Clear Filter",
            command=self.clear_filter
        ).pack(side="left", padx=5)

        # Tree + Scrollbar Frame
        container = tk.Frame(self.table_frame)
        container.pack(fill="both", expand=True)

        tree = ttk.Treeview(container, show="headings")
        tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        # Store sort state
        tree._sort_state = {}

        # Keep reference for copy handler
        self.tree = tree
        tree.bind("<Control-c>", self.copy_selection_to_clipboard)
        tree.bind("<Control-C>", self.copy_selection_to_clipboard)

        # Setup columns
        tree["columns"] = list(df.columns)
        
        # Bind column headers to sort to method
        for col in df.columns:
            tree.heading(col, text=col,
                         command=lambda c=col: self.sort_column(tree, df, c))
        
        for col in df.columns:
            tree.column(col, width=150, minwidth=100, stretch=True, anchor="w")

        # Insert rows
        for _, row in df.iterrows():
            tree.insert("", "end", values=list(row))
        
    def sort_column(self, tree, df, col):
        """
        Sort the Treeview by the given column.
        Preserves ascending/descending toggle state.
        """
        descending = tree._sort_state.get(col, False)
        tree._sort_state[col] = not descending

        # Extract values for sorting
        data = [(tree.set(k, col), k) for k in tree.get_children("")]

        # Try numeric sort first
        try:
            data = [(float(v), k) for v, k in data]
        except ValueError:
            pass

        data.sort(reverse=tree._sort_state[col])

        # Reorder rows
        for index, (_, k) in enumerate(data):
            tree.move(k, "", index)

        # Update column headers with sort indicators
        for c in df.columns:
            indicator = ""
            if c == col:
                indicator = " ▲" if not descending else " ▼"
            tree.heading(c, text=c + indicator,
                         command=lambda c=c: self.sort_column(tree, df, c))        

    def apply_filter(self):
        """Apply a regex filter to the current report dataframe."""
        import re
        pattern = self.filter_entry.get().strip()
        if not pattern:
            return

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            messagebox.showerror("Invalid Regex", "Your regex pattern is invalid.")
            return

        df = self.original_df.copy()

        # Match ANY column in the row
        mask = df.apply(
            lambda row: row.astype(str).str.contains(regex).any(),
            axis=1
        )

        self.filtered_df = df[mask]
        self.show_table(self.filtered_df)

    def clear_filter(self):
        self.filtered_df = self.original_df.copy()
        self.show_table(self.original_df)
            
    def copy_selection_to_clipboard(self, event=None):
        tree = self.tree  # stored reference from show_table
        selected = tree.selection()

        if not selected:
            return "break"

        rows = []
        for item in selected:
            values = tree.item(item, "values")
            rows.append("\t".join(str(v) for v in values))

        text = "\n".join(rows)

        # Copy to clipboard
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()  # keeps clipboard after app closes

        return "break"


# Run GUI
if __name__ == "__main__":
    root = tk.Tk()
    app = BrainzMRIGUI(root)
    root.mainloop()