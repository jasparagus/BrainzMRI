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
- Minimum hours
- Last-listened range (days ago)
- Top N
- Lets the user choose:
- By Artist
- By Album
- By Track (future expansion)
- Runs the appropriate report
- Saves output using your existing save_report() function
- Calls your existing functions without modifying them
============================================================
"""
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from datetime import datetime, timedelta, timezone
import os

import ParseListens as core

# ------------------------------------------------------------
# GUI Application
# ------------------------------------------------------------
class BrainzMRIGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("BrainzMRI Report Generator")

        self.zip_path = None
        self.df = None
        self.feedback = None

        # -----------------------------
        # ZIP File Selection
        # -----------------------------
        frm_zip = tk.Frame(root)
        frm_zip.pack(pady=10)

        tk.Button(frm_zip, text="Select ListenBrainz ZIP", command=self.select_zip).pack(side="left")
        self.lbl_zip = tk.Label(frm_zip, text="No file selected", fg="gray")
        self.lbl_zip.pack(side="left", padx=10)

        # -----------------------------
        # Input Fields
        # -----------------------------
        frm_inputs = tk.Frame(root)
        frm_inputs.pack(pady=10)

        def add_labeled_entry(parent, label, default):
            row = tk.Frame(parent)
            row.pack(anchor="w")
            tk.Label(row, text=label, width=25, anchor="w").pack(side="left")
            ent = tk.Entry(row, width=10)
            ent.insert(0, str(default))
            ent.pack(side="left")
            return ent

        self.ent_time_start = add_labeled_entry(frm_inputs, "Time Range Start (days ago):", 0)
        self.ent_time_end   = add_labeled_entry(frm_inputs, "Time Range End (days ago):", 365)

        self.ent_min_tracks = add_labeled_entry(frm_inputs, "Minimum Tracks:", 15)
        self.ent_min_hours  = add_labeled_entry(frm_inputs, "Minimum Hours:", 0)

        self.ent_last_start = add_labeled_entry(frm_inputs, "Last Listened Start (days ago):", 0)
        self.ent_last_end   = add_labeled_entry(frm_inputs, "Last Listened End (days ago):", 365)

        self.ent_topn       = add_labeled_entry(frm_inputs, "Top N:", 200)

        # -----------------------------
        # Dropdown for report type
        # -----------------------------
        frm_type = tk.Frame(root)
        frm_type.pack(pady=10)

        tk.Label(frm_type, text="Report Type:").pack(side="left", padx=5)

        self.report_type = ttk.Combobox(frm_type, values=["By Artist", "By Album"], state="readonly")
        self.report_type.current(0)
        self.report_type.pack(side="left")

        # -----------------------------
        # Analyze Button
        # -----------------------------
        tk.Button(root, text="Generate Report", command=self.run_report, bg="#4CAF50", fg="white").pack(pady=20)

    # --------------------------------------------------------
    # Select ZIP file
    # --------------------------------------------------------
    def select_zip(self):
        path = filedialog.askopenfilename(title="Select ListenBrainz ZIP", filetypes=[("ZIP files", "*.zip")])
        if not path:
            return
        self.zip_path = path
        self.lbl_zip.config(text=os.path.basename(path), fg="black")

        # Load data
        user_info, feedback, listens = core.parse_listenbrainz_zip(path)
        self.feedback = feedback
        self.df = core.normalize_listens(listens, path)

    # --------------------------------------------------------
    # Run the selected report
    # --------------------------------------------------------
    def run_report(self):
        if self.df is None:
            messagebox.showerror("Error", "Please select a ListenBrainz ZIP file first.")
            return

        df = self.df.copy()

        # Apply time range filter
        try:
            t_start = int(self.ent_time_start.get())
            t_end   = int(self.ent_time_end.get())
            df = core.filter_by_days(df, "listened_at", t_start, t_end)
        except:
            messagebox.showerror("Error", "Invalid time range values.")
            return

        # Apply last-listened filter
        try:
            l_start = int(self.ent_last_start.get())
            l_end   = int(self.ent_last_end.get())
            df = core.filter_by_days(df, "listened_at", l_start, l_end)
        except:
            messagebox.showerror("Error", "Invalid last-listened values.")
            return

        # Minimum tracks / hours filters
        try:
            min_tracks = int(self.ent_min_tracks.get())
            min_hours  = float(self.ent_min_hours.get())
        except:
            messagebox.showerror("Error", "Invalid numeric filter values.")
            return

        # Determine report type
        mode = self.report_type.get()
        topn = int(self.ent_topn.get())

        if mode == "By Artist":
            result, meta = core.report_top(df, group_col="artist", years=None, by="total_tracks", topn=topn)

        elif mode == "By Album":
            result, meta = core.report_top(df, group_col="album", years=None, by="total_tracks", topn=topn)

        else:
            messagebox.showerror("Error", "Unsupported report type.")
            return

        # Save report
        core.save_report(result, self.zip_path, meta=meta)
        messagebox.showinfo("Success", "Report generated successfully.")


# ------------------------------------------------------------
# Run GUI
# ------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = BrainzMRIGUI(root)
    root.mainloop()