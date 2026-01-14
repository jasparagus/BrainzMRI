"""
gui.py
Tkinter GUI for BrainzMRI, using reporting, enrichment, and user modules.
"""

import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from idlelib.tooltip import Hovertip
import re


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

        # Hide MBID columns from display
        df = df.drop(columns=[c for c in df.columns if c.endswith("_mbid")], errors="ignore")
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
        """
        Sort the underlying DataFrame and refresh the view.
        This ensures the visual order matches the data order for index-based lookups.
        """
        # Toggle sort order
        descending = tree._sort_state.get(col, False)
        tree._sort_state[col] = not descending

        # Sort the state dataframe, not just the tree items
        if self.state.filtered_df is not None:
            try:
                # Attempt numeric sort if possible, otherwise string
                self.state.filtered_df = self.state.filtered_df.sort_values(
                    by=col, 
                    ascending=not descending,
                    kind="mergesort" # Stable sort
                )
            except Exception:
                # Fallback for mixed types
                self.state.filtered_df = self.state.filtered_df.sort_values(
                    by=col, 
                    ascending=not descending, 
                    key=lambda x: x.astype(str)
                )
            
            # Re-render the table with the sorted data
            self.show_table(self.state.filtered_df)
            
            # Restore the sort arrow indicator
            # (show_table wipes headings, so we need to re-apply the arrow)
            new_tree = self.tree
            for c in self.state.filtered_df.columns:
                if c not in [col for col in self.state.filtered_df.columns if col.endswith("_mbid")]:
                    indicator = ""
                    if c == col:
                        indicator = " ▼" if descending else " ▲"
                    
                    new_tree.heading(
                        c, 
                        text=c + indicator,
                        command=lambda c=c: self.sort_column(new_tree, self.state.filtered_df, c)
                    )
            
            # Preserve sort state
            new_tree._sort_state = tree._sort_state


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
        
        
