"""
gui_tableview.py
Report Table View logic for BrainzMRI.
Handles rendering, regex filtering, and multi-column sorting.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import re
from typing import Any

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
        """
        Render the DataFrame into the Treeview.
        Applies current sort stack visuals.
        """
        if not self.filter_entry or not self.filter_entry.winfo_exists():
            self.build_filter_bar()

        current_filter = ""
        if self.filter_entry and self.filter_entry.winfo_exists():
            current_filter = self.filter_entry.get()

        # Hide ID columns from display
        df = df.drop(columns=[c for c in df.columns if c.endswith("_mbid")], errors="ignore")
        cols = list(df.columns)
        
        # Update dropdown
        self.filter_by_dropdown["values"] = ["All"] + cols
        if self.filter_by_var.get() not in ["All"] + cols:
            self.filter_by_var.set("All")

        # Restore filter text
        self.filter_entry.delete(0, tk.END)
        if current_filter:
            self.filter_entry.insert(0, current_filter)

        # Re-build container
        if not self.table_container or not self.table_container.winfo_exists():
            self.table_container = tk.Frame(self.container)
            self.table_container.pack(fill="both", expand=True)
        else:
            for widget in self.table_container.winfo_children():
                widget.destroy()

        # --- SCROLLBARS & TABLE SETUP (Updated to Grid for 2D scrolling) ---
        
        # Initialize Scrollbars
        vsb = ttk.Scrollbar(self.table_container, orient="vertical")
        hsb = ttk.Scrollbar(self.table_container, orient="horizontal")

        # Initialize Treeview with scroll commands linked
        tree = ttk.Treeview(
            self.table_container, 
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set
        )
        
        # Link scrollbars back to tree
        vsb.configure(command=tree.yview)
        hsb.configure(command=tree.xview)

        # Layout using Grid
        tree.grid(column=0, row=0, sticky='nsew')
        vsb.grid(column=1, row=0, sticky='ns')
        hsb.grid(column=0, row=1, sticky='ew')

        # Configure weights so tree expands to fill space
        self.table_container.grid_columnconfigure(0, weight=1)
        self.table_container.grid_rowconfigure(0, weight=1)

        self.tree = tree

        # Bindings
        tree.bind("<Control-c>", self.copy_selection_to_clipboard)
        tree.bind("<Control-C>", self.copy_selection_to_clipboard)

        # Clean Sort Stack (remove columns that no longer exist in this report)
        valid_cols = set(cols)
        self.sort_stack = [s for s in self.sort_stack if s[0] in valid_cols]

        # Setup Columns
        tree["columns"] = cols
        for col in cols:
            # Determine header text (Add arrow if Primary sort)
            header_text = col
            if self.sort_stack and self.sort_stack[0][0] == col:
                is_asc = self.sort_stack[0][1]
                header_text += " ▲" if is_asc else " ▼"

            tree.heading(
                col, 
                text=header_text, 
                command=lambda c=col: self.sort_column(c)
            )
            tree.column(col, width=150, minwidth=100, stretch=True, anchor="w")

        # Insert Data
        for _, row in df.iterrows():
            tree.insert("", "end", values=list(row))

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

        # 2. Sort DataFrame
        if self.state.filtered_df is not None:
            cols = [s[0] for s in self.sort_stack]
            ascs = [s[1] for s in self.sort_stack]
            
            try:
                # Use stable sort (mergesort) for multi-level consistency
                self.state.filtered_df = self.state.filtered_df.sort_values(
                    by=cols, 
                    ascending=ascs,
                    kind="mergesort"
                )
            except Exception:
                # Fallback for mixed types that pandas can't natively compare
                # We coerce to string for sorting in worst-case scenarios
                self.state.filtered_df = self.state.filtered_df.sort_values(
                    by=cols, 
                    ascending=ascs, 
                    key=lambda x: x.astype(str)
                )
            
            # 3. Refresh View (Redraws tree and updates header arrows)
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
        
        # FIX 1.2: Re-apply current sort stack to the filtered results
        if self.sort_stack:
            # We call sort_column with the primary key, but we need to cheat slightly
            # because sort_column toggles the direction.
            # Instead, we just manually re-run the sort logic using the existing stack.
            cols = [s[0] for s in self.sort_stack]
            ascs = [s[1] for s in self.sort_stack]
            
            try:
                self.state.filtered_df = self.state.filtered_df.sort_values(
                    by=cols, 
                    ascending=ascs,
                    kind="mergesort"
                )
            except Exception:
                self.state.filtered_df = self.state.filtered_df.sort_values(
                    by=cols, 
                    ascending=ascs, 
                    key=lambda x: x.astype(str)
                )

        self.show_table(self.state.filtered_df)

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