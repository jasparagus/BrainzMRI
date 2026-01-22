"""
gui_filters.py
Input component for filtering, thresholds, and enrichment settings.
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
        self.frm_row1.pack(pady=2, fill="x")

        # 1. Time Range (Listen Date)
        (self.ent_time_start, self.ent_time_end, frm_time) = self._create_labeled_double_entry(
            self.frm_row1, "Time Range To Analyze (Days Ago)", 0, 0
        )
        frm_time.pack(side="left", padx=5, expand=True, fill="both")

        # 2. Last Listened
        (self.ent_last_start, self.ent_last_end, frm_last) = self._create_labeled_double_entry(
            self.frm_row1, "Last Listened Date (Days Ago)", 0, 0
        )
        frm_last.pack(side="left", padx=5, expand=True, fill="both")

        # 3. First Listened (New)
        (self.ent_first_start, self.ent_first_end, frm_first) = self._create_labeled_double_entry(
            self.frm_row1, "First Listened Date (Days Ago)", 0, 0
        )
        frm_first.pack(side="left", padx=5, expand=True, fill="both")

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

        # 5. Enrichment Controls
        self._build_enrichment_controls()

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
        row.pack(anchor="center")
        
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

    def _build_enrichment_controls(self):
        frm = tk.Frame(self.parent)
        frm.pack(fill="x", pady=5, anchor="center")
        inner = tk.Frame(frm); inner.pack(anchor="center")

        tk.Label(inner, text="Genre Lookup (Enrichment) Source:", width=30, anchor="e").pack(side="left")

        self.enrichment_mode_var = tk.StringVar(value="None (Data Only, No Genres)")
        self.cmb_enrich = ttk.Combobox(
            inner,
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
        self.cmb_enrich.pack(side="left", padx=(0, 10))
        self._add_tooltip(self.cmb_enrich, "Note: API-based lookups are slow.\nUnless 'Force Cache Update' is checked, API lookups will\nuse previously cached Genres when possible.")

        self.force_cache_var = tk.BooleanVar(value=False)
        self.chk_force = tk.Checkbutton(inner, text="Force Cache Update", variable=self.force_cache_var)
        self.chk_force.pack(side="left", padx=5)
        self._add_tooltip(self.chk_force, "Forces querying the API for new genre data.\nNormal behavior will only query for missing genres.\nAny new metadata will update cached genre data.")

        self.deep_query_var = tk.BooleanVar(value=False)
        self.chk_deep = tk.Checkbutton(inner, text="Deep Query (Slow)", variable=self.deep_query_var)
        self.chk_deep.pack(side="left", padx=5)
        self._add_tooltip(self.chk_deep, "If checked, fetches metadata for Albums and Tracks.\nIf unchecked (Default), fetches Artists only (Fast).")

        # Logic to disable checkboxes if None/CacheOnly
        def _update_state(*_):
            mode = self.enrichment_mode_var.get()
            if mode.startswith("None") or mode == "Cache Only":
                self.chk_force.config(state="disabled"); self.force_cache_var.set(False)
                self.chk_deep.config(state="disabled"); self.deep_query_var.set(False)
            else:
                self.chk_force.config(state="normal")
                self.chk_deep.config(state="normal")
        
        self.enrichment_mode_var.trace_add("write", _update_state)
        _update_state()

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
            "first_start_days": min(f_start, f_end), # NEW
            "first_end_days": max(f_start, f_end),   # NEW
            "topn": _get_int(self.ent_topn, "Top N"),
            "min_listens": _get_int(self.ent_min_listens, "Min Listens"),
            "min_minutes": _get_float(self.ent_min_minutes, "Min Minutes"),
            "min_likes": _get_int(self.ent_min_likes, "Min Likes"),
            "enrichment_mode": self.enrichment_mode_var.get(),
            "force_update": self.force_cache_var.get(),
            "deep_query": self.deep_query_var.get()
        }