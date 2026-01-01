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
"""
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from datetime import datetime, timedelta, timezone
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
        
        tk.Button(frm_zip, text="Select ListenBrainz ZIP", command=self.select_zip).pack()
        
        self.lbl_zip = tk.Label(frm_zip, text="No file selected", fg="gray")
        self.lbl_zip.pack(pady=5)

        # -----------------------------
        # Input Fields
        # -----------------------------
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

        self.ent_time_start = add_labeled_entry(frm_inputs, "Time Range Start (days ago, e.g. 0):", 0)
        self.ent_time_end   = add_labeled_entry(frm_inputs, "Time Range End (days ago, e.g. 365):", 0)

        self.ent_last_start = add_labeled_entry(frm_inputs, "Last Listened Start (days ago, e.g. 180):", 0)
        self.ent_last_end   = add_labeled_entry(frm_inputs, "Last Listened End (days ago, e.g. 365):", 0)
        
        self.ent_topn       = add_labeled_entry(frm_inputs, "Top N (Number Of Results, e.g. 100):", 200)
        
        self.ent_min_tracks   = add_labeled_entry(frm_inputs, "Min. Tracks Listened Threshold:", 15)
        self.ent_min_minutes  = add_labeled_entry(frm_inputs, "Min. Minutes Listened Threshold:", 30)

        # -----------------------------
        # Dropdown for report type
        # -----------------------------
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

        # -----------------------------
        # Analyze Button
        # -----------------------------
        tk.Button(root, text="Generate Report", command=self.run_report, bg="#4CAF50", fg="white").pack(pady=20)
        
        # -----------------------------
        # Status Bar
        # -----------------------------
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

        self.status_bar.pack(fill="x", side="bottom")


    def set_status(self, text):
        self.status_var.set(text)
        self.status_bar.update_idletasks()
    
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
        self.set_status("Zip loaded.")

    def apply_recency_filter(self, result):
        try:
            l_start = int(self.ent_last_start.get())
            l_end   = int(self.ent_last_end.get())

            rec_start = min(l_start, l_end)
            rec_end   = max(l_start, l_end)

            # (0,0) => All time, skip recency filter
            if rec_start == 0 and rec_end == 0:
                return

            now = datetime.now(timezone.utc)
            min_dt = now - timedelta(days=rec_end)
            max_dt = now - timedelta(days=rec_start)

            mask = (result["last_listened_dt"] >= min_dt) & (result["last_listened_dt"] <= max_dt)
            result.drop(result[~mask].index, inplace=True)

        except ValueError:
            messagebox.showerror("Error", "Last listened range must be numeric.")
            self.set_status("Error: Last listened range must be numeric.")
        except Exception as e:
            messagebox.showerror("Unexpected Error in Last Listened", f"{type(e).__name__}: {e}")
            self.set_status("Error: Unexpected Error in Last Listened.")

    # --------------------------------------------------------
    # Run the selected report
    # --------------------------------------------------------
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

        # By Artist
        if mode == "By Artist":
            result, meta = core.report_top(
                df,
                group_col="artist",
                days=time_range,
                by="total_tracks",
                topn=topn
            )
            self.apply_recency_filter(result)
            filepath = core.save_report(result, self.zip_path, meta=meta)
            open_file_default(filepath)
            self.set_status("Artist report generated and opened.")
            return

        # By Album
        elif mode == "By Album":
            result, meta = core.report_top(
                df,
                group_col="album",
                days=time_range,
                by="total_tracks",
                topn=topn
            )
            self.apply_recency_filter(result)
            filepath = core.save_report(result, self.zip_path, meta=meta)
            open_file_default(filepath)
            self.set_status("Album report generated and opened.")
            return
            
        # By Track
        elif mode == "By Track":
            result, meta = core.report_top(
                df,
                group_col="track",
                days=time_range,
                by="total_tracks",
                topn=topn
            )
            self.apply_recency_filter(result)
            filepath = core.save_report(result, self.zip_path, meta=meta)
            open_file_default(filepath)
            self.set_status("Track report generated and opened.")
            return
            
            
        # All liked artists
        elif mode == "All Liked Artists":
            result, meta = core.report_artists_with_likes(df, self.feedback)            
            filepath = core.save_report(result, self.zip_path, meta=meta)
            open_file_default(filepath)
            self.set_status("Liked artists report generated and opened.")
            return

        # Enriched artist report (threshold + genres)
        elif mode == "Enriched Artist Report":
            artist_report = core.report_artists_threshold(
                df,
                mins=min_minutes,
                tracks=min_tracks
            )
            out_path, enriched = core.enrich_report_with_genres(artist_report, self.zip_path)
            open_file_default(out_path)
            self.set_status("Enriched artist report (with genres) generated and opened.")
            return

        else:
            messagebox.showerror("Error", "Unsupported report type.")
            self.set_status("Error: Unsupported report type.")
            return


# ------------------------------------------------------------
# Run GUI
# ------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = BrainzMRIGUI(root)
    root.mainloop()