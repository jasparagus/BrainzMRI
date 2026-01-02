# BrainzMRI GUI – Filter Bar Integration (2026-01-01)

## Summary
Added a regex-capable filter bar inside the table frame, above the Treeview.  
Users can now type a regex, click “Filter”, and see only matching rows.  
“Clear Filter” restores the original table.

---

## Changes

### 1. Added filter state variables
- Added at line ~150 in `__init__`
- Purpose: store original and filtered DataFrames

### 2. Modified show_table()
- Replaced entire method
- Added:
  - Filter bar (label, entry, Filter button, Clear Filter button)
  - Storage of original_df and filtered_df
- Ensures filter bar appears above the table inside the table frame

### 3. Added apply_filter() and clear_filter()
- New methods added after copy_selection_to_clipboard()
- apply_filter():
  - Compiles regex
  - Filters rows where ANY column matches
  - Calls show_table() with filtered results
- clear_filter():
  - Restores original_df
  - Calls show_table() to reset table

### 4. Parser file
- No changes required

---

## Why These Changes Were Made
- To allow interactive filtering of table results without regenerating reports
- To support regex-based searching across all text fields
- To keep filtering logic isolated to the GUI layer



1. Add new instance variables
Insert after the line where self.table_frame is created (around line ~150)

        # Filter state
        self.original_df = None
        self.filtered_df = None

2. Replace show_table() to include filter row

    def show_table(self, df):
        # Save original df for clearing filters
        self.original_df = df.copy()
        self.filtered_df = df.copy()

        # Clear old table
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        # === FILTER BAR (inside table frame, above table) ===
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

        # === TABLE CONTAINER ===
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

        # Sorting function
        def sort_column(col):
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
                tree.heading(c, text=c + indicator,
                             command=lambda c=c: sort_column(c))

        # Setup columns
        tree["columns"] = list(df.columns)
        for col in df.columns:
            tree.heading(col, text=col,
                         command=lambda c=col: sort_column(c))
            tree.column(col, width=150, minwidth=100, stretch=True, anchor="w")

        # Insert rows
        for _, row in df.iterrows():
            tree.insert("", "end", values=list(row))


3. Add Filter + Clear Methods
Insert these methods anywhere below copy_selection_to_clipboard

    def apply_filter(self):
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

        mask = df.apply(
            lambda row: row.astype(str).str.contains(regex).any(),
            axis=1
        )

        self.filtered_df = df[mask]
        self.show_table(self.filtered_df)

    def clear_filter(self):
        self.filtered_df = self.original_df.copy()
        self.show_table(self.original_df)