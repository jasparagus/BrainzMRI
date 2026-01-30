"""
gui_filters.py
Input component for filtering and thresholds.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from idlelib.tooltip import Hovertip

class FilterComponent:
    def __init__(self, parent: tk.Frame, on_enter_key):
        self.parent = parent
        self.on_enter_key = on_enter_key

        self.frm_inputs = tk.Frame(parent)
        self.frm_inputs.pack(pady=5, fill="x")

        # --- Row 1: Time, Last Listened, First Listened (Side-by-Side) ---
        self.frm_row1 = tk.Frame(self.frm_inputs)
        # FIX: Center the row instead of filling width, so the 3 items sit in the middle
        self.frm_row1.pack(pady=2, anchor="center")

        # 1. Time Range (Listen Date)
        (self.ent_time_start, self.ent_time_end, frm_time) = self._create_labeled_double_entry(
            self.frm_row1, "Time Range To Analyze (Days Ago)", 0, 0
        )
        frm_time.pack(side="left", padx=5, fill="y")

        # 2. Last Listened
        (self.ent_last_start, self.ent_last_end, frm_last) = self._create_labeled_double_entry(
            self.frm_row1, "Last Listened Date (Days Ago)", 0, 0
        )
        frm_last.pack(side="left", padx=5, fill="y")

        # 3. First Listened
        (self.ent_first_start, self.ent_first_end, frm_first) = self._create_labeled_double_entry(
            self.frm_row1, "First Listened Date (Days Ago)", 0, 0
        )
        frm_first.pack(side="left", padx=5, fill="y")

        # Tooltips
        self._add_tooltip(self.ent_time_start, "Time range filtering. Excludes listens by date.\nExample: [365, 730] will display listens from 1–2 years ago.\nDefault: [0, 0] (days ago).")
        self._add_tooltip(self.ent_last_start, "Recency filtering. Exclude entities by last listened date.\nExample: [365, 9999] = Last heard over a year ago.")
        self._add_tooltip(self.ent_first_start, "Discovery filtering. Exclude entities by first listened date.\nExample: [0, 30] = First heard in the last month (New discoveries).")

        # 4. Thresholds (Grouped in LabelFrame)
        self._build_threshold_frame()

        # Bind Enter Key to all inputs
        all_entries = [
            self.ent_time_start, self.ent_time_end, 
            self.ent_last_start, self.ent_last_end,
            self.ent_first_start, self.ent_first_end,
            self.ent_topn, self.ent_min_listens, self.ent_min_minutes, self.ent_min_likes
        ]
        for ent in all_entries:
            ent.bind("<Return>", lambda e: self.on_enter_key())

    def _build_threshold_frame(self):
        # Create Bordered LabelFrame
        frm_thresh = tk.LabelFrame(self.frm_inputs, text="Thresholds For Filtering Data", padx=10, pady=5)
        frm_thresh.pack(pady=5, anchor="center")

        # Row 1: All inputs side-by-side
        # Top N
        tk.Label(frm_thresh, text="Top N (Results):").pack(side="left", padx=(0, 2))
        self.ent_topn = tk.Entry(frm_thresh, width=6)
        self.ent_topn.insert(0, "200")
        self.ent_topn.pack(side="left", padx=(0, 10))
        self._add_tooltip(self.ent_topn, "Number of results to return.\nDefault: 200 results")

        # Min Listens
        tk.Label(frm_thresh, text="Minimum Listen Count:").pack(side="left", padx=(0, 2))
        self.ent_min_listens = tk.Entry(frm_thresh, width=6)
        self.ent_min_listens.insert(0, "10")
        self.ent_min_listens.pack(side="left", padx=(0, 10))
        self._add_tooltip(self.ent_min_listens, "Minimum number of listens.\nWorks as an OR with minimum minutes.")

        # Min Minutes
        tk.Label(frm_thresh, text="Minimum Minutes Listened:").pack(side="left", padx=(0, 2))
        self.ent_min_minutes = tk.Entry(frm_thresh, width=6)
        self.ent_min_minutes.insert(0, "15")
        self.ent_min_minutes.pack(side="left", padx=(0, 10))
        self._add_tooltip(self.ent_min_minutes, "Minimum number of minutes listened.\nWorks as an OR with minimum listens.")

        # Min Likes
        tk.Label(frm_thresh, text="Minimum Number of Likes:").pack(side="left", padx=(0, 2))
        self.ent_min_likes = tk.Entry(frm_thresh, width=6)
        self.ent_min_likes.insert(0, "0")
        self.ent_min_likes.pack(side="left", padx=(0, 5))
        self._add_tooltip(self.ent_min_likes, "Minimum number of unique liked tracks.\nDefault: 0 (disabled).")

    def _create_labeled_double_entry(self, parent, label, default1, default2):
        # REFACTORED: Use LabelFrame for clarity and grouping
        frm = tk.LabelFrame(parent, text=label, padx=5, pady=5)
        
        # Inner row to hold the entries centered
        row = tk.Frame(frm)
        row.pack(anchor="center", ipadx=10, pady=2)
        
        tk.Label(row, text="Start:", width=5, anchor="e").pack(side="left")
        ent1 = tk.Entry(row, width=6)
        ent1.insert(0, str(default1))
        ent1.pack(side="left", padx=5)
        
        tk.Label(row, text="End:", width=5, anchor="e").pack(side="left")
        ent2 = tk.Entry(row, width=6)
        ent2.insert(0, str(default2))
        ent2.pack(side="left", padx=5)
        
        return ent1, ent2, frm

    def _add_tooltip(self, widget, text):
        Hovertip(widget, text, hover_delay=500)

    # ------------------------------------------------------------------
    # Public Accessor
    # ------------------------------------------------------------------
    def get_values(self):
        """Reads all inputs, validates them, and returns a dictionary."""
        def _get_int(ent, name):
            try: return int(ent.get().strip())
            except: raise ValueError(f"{name} must be an integer.")
        
        def _get_float(ent, name):
            try: return float(ent.get().strip())
            except: raise ValueError(f"{name} must be a number.")

        t_start = _get_int(self.ent_time_start, "Time Start")
        t_end = _get_int(self.ent_time_end, "Time End")
        
        l_start = _get_int(self.ent_last_start, "Recency Start")
        l_end = _get_int(self.ent_last_end, "Recency End")

        f_start = _get_int(self.ent_first_start, "First Start")
        f_end = _get_int(self.ent_first_end, "First End")

        return {
            "time_start_days": min(t_start, t_end),
            "time_end_days": max(t_start, t_end),
            "rec_start_days": min(l_start, l_end),
            "rec_end_days": max(l_start, l_end),
            "first_start_days": min(f_start, f_end),
            "first_end_days": max(f_start, f_end),
            "topn": _get_int(self.ent_topn, "Top N"),
            "min_listens": _get_int(self.ent_min_listens, "Min Listens"),
            "min_minutes": _get_float(self.ent_min_minutes, "Min Minutes"),
            "min_likes": _get_int(self.ent_min_likes, "Min Likes")
        }