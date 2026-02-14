"""
gui_tableview.py
Report Table View logic for BrainzMRI.
Handles rendering, regex filtering, and multi-column sorting.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import re
import logging  # Added for diagnostic logging
from typing import Any, Optional
import pandas as pd
import parsing # Ensure parsing is imported to access normalize_sort_key

def _clean_text_for_tk(text: Any) -> str:
    """
    Sanitize text for Tkinter/Tcl on Windows to prevent Access Violations.
    1. Convert to string.
    2. Remove non-BMP characters (> U+FFFF).
    3. Remove Tcl/Tk incompatible control characters (keeps tab/newline).
    4. Remove lone surrogates.
    """
    if text is None: return ""
    text = str(text)
    
    # Fast path: if pure ASCII, usually safe (unless control chars)
    if text.isascii() and text.isprintable():
        return text

    # Filter out:
    # - Surrogates (0xD800 - 0xDFFF)
    # - Non-BMP (> 0xFFFF)
    # - Control characters (0x00-0x1F) EXCLUDING \t, \n, \r
    # We use a generator for memory efficiency on long strings
    
    clean_chars = []
    for c in text:
        code = ord(c)
        
        # 1. Reject Non-BMP or Surrogates
        if code > 0xFFFF or (0xD800 <= code <= 0xDFFF):
            continue
            
        # 2. Reject Control Codes (except valid whitespace)
        if code < 32 and c not in ("\t", "\n", "\r"):
            continue
            
        clean_chars.append(c)
        
    return "".join(clean_chars)


class ReportTableView:
    """
    Encapsulates table rendering, filtering, and multi-column sorting.
    """

    def __init__(self, root: tk.Tk, container: tk.Frame, state: Any) -> None:
        self.root = root
        self.container = container
        self.state = state

        # Filter state
        self.filter_by_var = tk.StringVar(value="All")
        self.filter_entry: tk.Entry | None = None

        # Sort state: List of tuples (column_name, ascending_bool)
        # Example: [('artist', True), ('year', False)]
        # Index 0 is the Primary Sort Key.
        self.sort_stack = []

        # UI containers
        self.filter_frame: tk.Frame | None = None
        self.table_container: tk.Frame | None = None

        # Treeview
        self.tree: ttk.Treeview | None = None

        # Build initial filter bar
        self.build_filter_bar()
        
        # Build Table UI once (Reusable)
        self._build_table_ui()

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

    def _build_table_ui(self):
        """Construct the reusable table container and widget."""
        logging.info("TRACE: _build_table_ui started")
        
        self.table_container = tk.Frame(self.container)
        self.table_container.pack(fill="both", expand=True)

        # Initialize Scrollbars
        vsb = ttk.Scrollbar(self.table_container, orient="vertical")
        hsb = ttk.Scrollbar(self.table_container, orient="horizontal")

        # Initialize Treeview
        self.tree = ttk.Treeview(
            self.table_container, 
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set
        )
        
        # Link scrollbars
        vsb.configure(command=self.tree.yview)
        hsb.configure(command=self.tree.xview)

        # Layout (Grid)
        self.tree.grid(column=0, row=0, sticky='nsew')
        vsb.grid(column=1, row=0, sticky='ns')
        hsb.grid(column=0, row=1, sticky='ew')

        # Weights
        self.table_container.grid_columnconfigure(0, weight=1)
        self.table_container.grid_rowconfigure(0, weight=1)

        # Bindings
        self.tree.bind("<Control-c>", self.copy_selection_to_clipboard)
        self.tree.bind("<Control-C>", self.copy_selection_to_clipboard)
        
        logging.info("TRACE: _build_table_ui completed. Widget ID: " + str(self.tree.winfo_id()))

    # ------------------------------------------------------------
    # Table Rendering
    # ------------------------------------------------------------

    def show_table(self, df):
        """
        Render the DataFrame into the Treeview.
        Applies current sort stack visuals.
        """
        logging.info(f"TRACE: show_table called with {len(df)} rows. Columns: {list(df.columns)}")
        
        # Hide ID columns from display
        df = df.drop(columns=[c for c in df.columns if c.endswith("_mbid")], errors="ignore")
        cols = list(df.columns)
        
        # Update dropdown
        self.filter_by_dropdown["values"] = ["All"] + cols
        if self.filter_by_var.get() not in ["All"] + cols:
            self.filter_by_var.set("All")

        # SAFETY: Hide tree during column reconfiguration to prevent Tcl access violations
        # from pending events (like hover) on columns that are about to vanish.
        self.tree.grid_remove() 
        logging.info("TRACE: show_table: grid_remove() done.")
        
        # Clear existing items — delete one-at-a-time to avoid stressing
        # Tcl's C allocator with a single massive deallocation batch.
        logging.info("TRACE: show_table: Clearing existing items...")
        existing = self.tree.get_children()
        logging.info(f"TRACE: show_table: {len(existing)} items to delete.")
        for item in existing:
            self.tree.delete(item)
        logging.info("TRACE: show_table: All items deleted.")
        
        # Update Columns
        logging.info("TRACE: show_table: Updating columns...")
        self.tree["columns"] = cols
        for col in cols:
            # Determine header text (Add arrow if Primary sort)
            header_text = col
            if self.sort_stack and self.sort_stack[0][0] == col:
                is_asc = self.sort_stack[0][1]
                header_text += " ▲" if is_asc else " ▼"

            self.tree.heading(
                col, 
                text=header_text, 
                command=lambda c=col: self.sort_column(c)
            )
            self.tree.column(col, width=150, minwidth=100, stretch=True, anchor="w")
        logging.info("TRACE: show_table: Columns configured.")
        
        # Clean Sort Stack
        valid_cols = set(cols)
        self.sort_stack = [s for s in self.sort_stack if s[0] in valid_cols]

        # Flush pending Tcl events between delete and insert
        # DIAGNOSTIC: Flush Python log buffers BEFORE calling update_idletasks
        # so if a C-level crash occurs, the trace above is guaranteed written.
        logging.info("TRACE: show_table: About to call update_idletasks()...")
        for handler in logging.getLogger().handlers:
            handler.flush()
        self.tree.update_idletasks()
        logging.info("TRACE: show_table: update_idletasks() survived.")

        # Insert Data
        logging.info("show_table: Inserting data rows...")
        try:
             # Fast Bulk Insert (or row-by-row with safety)
             for i, (_, row) in enumerate(df.iterrows()):
                 if i > 20000: break # Safety cap
                 
                 # Convert all values to string to prevent Tcl interpretation issues
                 safe_values = [_clean_text_for_tk(v) for v in row]
                 self.tree.insert("", "end", values=safe_values)
                 if i % 100 == 0: logging.info(f"Inserted row {i}...")
             
             logging.info("show_table: Data insertion complete.")
        except Exception as e:
            messagebox.showerror("Display Error", f"Failed to render table rows: {e}")
            logging.error(f"Treeview Insertion Failed: {e}", exc_info=True)

        # Restore visibility
        self.tree.grid()
        logging.info("TRACE: Treeview visible again.")





    # ------------------------------------------------------------
    # Sorting (Multi-Column Stack)
    # ------------------------------------------------------------

    def sort_column(self, col: str) -> None:
        """
        Update the sort stack and re-sort the DataFrame.
        Logic:
        - If col is already Primary (index 0): Toggle Asc/Desc.
        - If col is not Primary: Move to Index 0 (become Primary), default Asc.
        - Max stack depth: 3.
        """
        # 1. Update Stack
        if self.sort_stack and self.sort_stack[0][0] == col:
            # Toggle current primary
            curr_col, curr_asc = self.sort_stack[0]
            self.sort_stack[0] = (curr_col, not curr_asc)
        else:
            # Move to front (Remove existing instance if any)
            self.sort_stack = [s for s in self.sort_stack if s[0] != col]
            # Insert as new Primary (Ascending default)
            self.sort_stack.insert(0, (col, True))
        
        # Limit depth
        if len(self.sort_stack) > 3:
            self.sort_stack = self.sort_stack[:3]

        # 2. Apply Sort using helper
        self._apply_sort()

    def _apply_sort(self):
        """
        Internal helper to apply the current sort_stack to self.state.filtered_df
        using the regularized sort key logic.
        """
        if self.state.filtered_df is None or not self.sort_stack:
            # If no sort, just refresh (or do nothing)
            if self.state.filtered_df is not None:
                self.show_table(self.state.filtered_df)
            return

        cols = [s[0] for s in self.sort_stack]
        ascs = [s[1] for s in self.sort_stack]

        # Define the Key Wrapper for "Regularized Sorting"
        def sort_key_wrapper(col_series):
            # If numeric or date, let Pandas handle it natively
            if pd.api.types.is_numeric_dtype(col_series) or pd.api.types.is_datetime64_any_dtype(col_series):
                return col_series
            
            # Otherwise, use our smart string normalizer
            return parsing.normalize_sort_key(col_series)

        try:
            # Use stable sort (mergesort)
            self.state.filtered_df = self.state.filtered_df.sort_values(
                by=cols, 
                ascending=ascs,
                kind="mergesort",
                key=sort_key_wrapper  # <--- The Magic Hook
            )
        except Exception as e:
            print(f"Sort failed, falling back to string sort: {e}")
            self.state.filtered_df = self.state.filtered_df.sort_values(
                by=cols, 
                ascending=ascs, 
                key=lambda x: x.astype(str)
            )
        
        self.show_table(self.state.filtered_df)

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
        
        # Re-apply current sort stack to the filtered results using the shared helper
        self._apply_sort()

    def clear_filter(self) -> None:
        if self.state.original_df is None or self.filter_entry is None:
            return
        
        # Reset filtered_df to original
        self.state.filtered_df = self.state.original_df.copy()
        
        # We also reset the sort stack on Clear Filter to return to "Native" order
        # (or comment this out if you prefer sort to persist across clear)
        self.sort_stack = [] 
        
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