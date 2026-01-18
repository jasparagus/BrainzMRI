"""
gui_main.py
Tkinter GUI for BrainzMRI, using reporting, enrichment, and user modules.
"""

import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, simpledialog
from datetime import datetime, timedelta, timezone
from idlelib.tooltip import Hovertip
import os
import subprocess
import sys
import re
import threading
import time
import pandas as pd # Explicit import for write-back logic

import reporting
import enrichment
import gui_charts
import parsing
from user import (
    User,
    get_cache_root,
    get_cached_usernames,
    get_user_cache_dir,
)
from report_engine import ReportEngine
from gui_user_editor import UserEditorWindow
from gui_tableview import ReportTableView
from api_client import ListenBrainzClient


def open_file_default(path: str) -> None:
    """Open a file using the OS default application."""
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class GUIState:
    """Centralized state for the BrainzMRI GUI."""

    def __init__(self) -> None:
        # Current user
        self.user: User | None = None

        # Ephemeral Playlist State
        self.original_df: pd.DataFrame | None = None
        self.filtered_df: pd.DataFrame | None = None
        
        # Last run meta (for saving)
        self.last_meta: dict | None = None
        self.last_mode: str = ""


class ProgressWindow(tk.Toplevel):
    """
    A modal window showing a progress bar and status text.
    Used for long-running blocking operations.
    """
    def __init__(self, parent, title, label_text):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x150")
        self.resizable(False, False)
        
        # Center on parent
        self.transient(parent)
        self.grab_set()
        
        tk.Label(self, text=label_text, pady=10).pack()
        
        self.progress = ttk.Progressbar(self, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=10)
        
        self.status_label = tk.Label(self, text="", fg="grey")
        self.status_label.pack(pady=5)
        
        # Cancellation support
        self.cancelled = False
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        
    def update_progress(self, current, total, status=""):
        if total > 0:
            pct = (current / total) * 100
            self.progress["value"] = pct
        self.status_label.config(text=status)
        self.update_idletasks()

    def on_cancel(self):
        if messagebox.askyesno("Cancel", "Stop this operation?"):
            self.cancelled = True
            self.destroy()


class MainWindow:
    """
    Main Application Window.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BrainzMRI: ListenBrainz Metadata Review Instrument")
        self.root.geometry("1400x900")

        self.state = GUIState()
        self.report_engine = ReportEngine()
        
        # Background Workers
        self.stop_event = threading.Event()

        # Layout
        self._build_menu()
        self._build_top_bar()
        self._build_main_area()
        self._build_status_bar()

        # Startup
        self._check_for_users()

    # ==================================================================
    # UI Construction
    # ==================================================================

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New User", command=self.action_new_user)
        file_menu.add_command(label="Edit User", command=self.action_edit_user)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo("About", "BrainzMRI v2026.01.17"))
        menubar.add_cascade(label="Help", menu=help_menu)

    def _build_top_bar(self) -> None:
        top_frame = tk.Frame(self.root, relief=tk.RAISED, bd=2)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # 1. User Selection
        tk.Label(top_frame, text="User:").pack(side=tk.LEFT, padx=5)
        self.user_combo = ttk.Combobox(top_frame, state="readonly", width=15)
        self.user_combo.pack(side=tk.LEFT, padx=5)
        self.user_combo.bind("<<ComboboxSelected>>", self.on_user_selected)
        Hovertip(self.user_combo, "Select active user profile")

        # 2. Data Actions
        btn_update = tk.Button(top_frame, text="Get New Listens", command=self.action_get_new_listens)
        btn_update.pack(side=tk.LEFT, padx=5)
        Hovertip(btn_update, "Fetch recent listens from ListenBrainz (Resumable)")

        btn_import_csv = tk.Button(top_frame, text="Import CSV", command=self.action_import_csv)
        btn_import_csv.pack(side=tk.LEFT, padx=5)
        Hovertip(btn_import_csv, "Analyze external CSV playlist")

        tk.Frame(top_frame, width=20).pack(side=tk.LEFT)  # Spacer

        # 3. Report Configuration
        tk.Label(top_frame, text="Report:").pack(side=tk.LEFT, padx=5)
        self.report_type_var = tk.StringVar(value="By Artist")
        report_types = list(self.report_engine._handlers.keys())
        self.report_combo = ttk.Combobox(top_frame, textvariable=self.report_type_var, values=report_types, state="readonly", width=18)
        self.report_combo.pack(side=tk.LEFT, padx=5)

        # Days Filter
        tk.Label(top_frame, text="Days Ago (Start, End):").pack(side=tk.LEFT, padx=5)
        self.days_entry = tk.Entry(top_frame, width=10)
        self.days_entry.insert(0, "0, 365")
        self.days_entry.pack(side=tk.LEFT, padx=5)
        Hovertip(self.days_entry, "Range (e.g. '0, 365' for last year)\nor single number (e.g. '30' for last 30 days)")

        # Generate Button
        btn_generate = tk.Button(top_frame, text="Generate Report", command=self.action_generate_report, bg="#dddddd")
        btn_generate.pack(side=tk.LEFT, padx=5)
        
        # 4. Enrichment Options (Collapsible or just inline)
        # For now, let's put them in a LabelFrame nearby
        enrich_frame = tk.LabelFrame(top_frame, text="Enrichment & Thresholds", padx=5, pady=2)
        enrich_frame.pack(side=tk.LEFT, padx=10, fill=tk.Y)

        self.enrich_mode_var = tk.StringVar(value=enrichment.ENRICHMENT_MODE_CACHE_ONLY)
        modes = [
            enrichment.ENRICHMENT_MODE_CACHE_ONLY,
            enrichment.ENRICHMENT_MODE_MB,
            enrichment.ENRICHMENT_MODE_LASTFM,
            enrichment.ENRICHMENT_MODE_ALL
        ]
        opt_enrich = ttk.OptionMenu(enrich_frame, self.enrich_mode_var, modes[0], *modes)
        opt_enrich.pack(side=tk.LEFT, padx=5)
        
        # Deep Query Checkbox
        self.deep_query_var = tk.BooleanVar(value=False)
        chk_deep = tk.Checkbutton(enrich_frame, text="Deep Query", variable=self.deep_query_var)
        chk_deep.pack(side=tk.LEFT, padx=5)
        Hovertip(chk_deep, "Fetch metadata for Album/Track entities (Slower)")

        # Force Cache Checkbox
        self.force_cache_update_var = tk.BooleanVar(value=False)
        chk_force_cache = tk.Checkbutton(
            enrich_frame,
            text="Force Cache Update",
            variable=self.force_cache_update_var,
        )
        chk_force_cache.pack(side="left", padx=5)
        Hovertip(
            chk_force_cache,
            "Forces querying the API for new genre data.\n"
            "Normal behavior will only query for missing genres.\n"
            "Any new metadata will update cached genre data.",
            hover_delay=500
        )
        
        # Thresholds
        tk.Label(enrich_frame, text="Min Listens:").pack(side=tk.LEFT, padx=2)
        self.min_listens_var = tk.StringVar(value="0")
        tk.Entry(enrich_frame, textvariable=self.min_listens_var, width=4).pack(side=tk.LEFT)
        
        tk.Label(enrich_frame, text="Min Likes:").pack(side=tk.LEFT, padx=2)
        self.min_likes_var = tk.StringVar(value="0")
        tk.Entry(enrich_frame, textvariable=self.min_likes_var, width=4).pack(side=tk.LEFT)

    def _build_main_area(self) -> None:
        # Main area is just the table view
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Toolbar for Table Actions
        self.table_toolbar = tk.Frame(self.main_frame)
        self.table_toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        
        btn_graph = tk.Button(self.table_toolbar, text="Show Graph", command=self.action_show_graph)
        btn_graph.pack(side=tk.LEFT, padx=5)
        Hovertip(btn_graph, "Visualize current report (if supported)")
        
        tk.Label(self.table_toolbar, text="|").pack(side=tk.LEFT, padx=5)
        
        btn_resolve = tk.Button(self.table_toolbar, text="Resolve Metadata", command=self.action_resolve_metadata)
        btn_resolve.pack(side=tk.LEFT, padx=5)
        Hovertip(btn_resolve, "Query MusicBrainz for missing IDs (Requires 'artist' & 'track_name')")
        
        tk.Label(self.table_toolbar, text="|").pack(side=tk.LEFT, padx=5)

        btn_like = tk.Button(self.table_toolbar, text="Like Selected Tracks", command=self.action_batch_like)
        btn_like.pack(side=tk.LEFT, padx=5)
        Hovertip(btn_like, "Mark selected tracks as 'Loved' on ListenBrainz")

        btn_playlist = tk.Button(self.table_toolbar, text="Export as Playlist", command=self.action_export_playlist)
        btn_playlist.pack(side=tk.LEFT, padx=5)
        Hovertip(btn_playlist, "Create a JSPF playlist from current view")

        btn_save = tk.Button(self.table_toolbar, text="Save to CSV", command=self.action_save_report)
        btn_save.pack(side=tk.LEFT, padx=5)
        
        # Dry Run Toggle
        self.dry_run_var = tk.BooleanVar(value=True)
        chk_dry = tk.Checkbutton(self.table_toolbar, text="Dry Run API Actions", variable=self.dry_run_var)
        chk_dry.pack(side=tk.RIGHT, padx=5)
        Hovertip(chk_dry, "Simulate API writes (Likes/Playlists) without sending data")

        # Table Component
        self.table_view = ReportTableView(self.root, self.main_frame, self.state)

    def _build_status_bar(self) -> None:
        self.status_var = tk.StringVar()
        self.status_var.set("Ready.")
        self.status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ==================================================================
    # Logic: User Management
    # ==================================================================

    def _check_for_users(self) -> None:
        usernames = get_cached_usernames()
        if not usernames:
            self.user_combo["values"] = []
            self.status_var.set("No users found. Please create a New User.")
        else:
            self.user_combo["values"] = usernames
            self.user_combo.current(0)
            self.on_user_selected(None)

    def on_user_selected(self, event) -> None:
        username = self.user_combo.get()
        if not username:
            return

        # Load user
        # We need to know where the config is or just assume standard path
        # Simplification: We re-instantiate User which loads cache
        # Ideally we'd store tokens in a central config, but for now we look at config.json
        config = self.load_config()
        users_cfg = config.get("users", {})
        
        if username in users_cfg:
            u_data = users_cfg[username]
            self.state.user = User(
                username=username,
                token=u_data.get("token", ""),
                lastfm_username=u_data.get("lastfm_username", "")
            )
            self.set_status(f"Loaded user: {username} ({len(self.state.user.listens_df)} listens)")
        else:
            # Fallback if config missing but folder exists (unlikely in normal flow)
            self.set_status(f"Error: Config missing for {username}")

    def action_new_user(self) -> None:
        def on_save(username):
            self._check_for_users()
            self.user_combo.set(username)
            self.on_user_selected(None)
            
        UserEditorWindow(self.root, None, on_save)

    def action_edit_user(self) -> None:
        if not self.state.user:
            return
        
        def on_save(username):
            self._check_for_users()
            self.user_combo.set(username)
            self.on_user_selected(None)
            
        UserEditorWindow(self.root, self.state.user, on_save)

    # ==================================================================
    # Logic: Data Ingestion (Transactional + Auto-Likes)
    # ==================================================================

    def action_get_new_listens(self) -> None:
        """
        Transactional update:
        1. Fetch new listens (Backwards Crawl) -> Merge if gap closed.
        2. Sync Likes (Parallel) -> Update local cache.
        """
        if not self.state.user:
            messagebox.showwarning("Warning", "Select a user first.")
            return
        
        # Confirm
        if not messagebox.askyesno("Update", "Fetch new listens and sync likes from ListenBrainz?"):
            return

        user = self.state.user
        lb_client = ListenBrainzClient(user.token, dry_run=False)

        # Shared State for Progress
        self.stop_event = threading.Event()
        self.progress_win = ProgressWindow(self.root, "Fetching Data", "Initializing...")

        # --------------------------------------------------------
        # WORKER 2: LIKES (The "Background" Task)
        # --------------------------------------------------------
        def likes_worker():
            try:
                # Initial UI update
                self.root.after(0, lambda: self.set_status("Syncing Likes..."))
                fetched_likes = set()
                offset = 0
                page_size = 100
                
                while not self.stop_event.is_set():
                    # Fetch Page
                    try:
                        response = lb_client.get_user_likes(user.username, offset=offset, count=page_size)
                    except Exception as e:
                        print(f"Likes API Error: {e}")
                        break

                    feedback = response.get("feedback", [])
                    if not feedback:
                        break # End of list
                        
                    for item in feedback:
                        # "score": 1 means like, 0 is neutral, -1 is dislike
                        if item.get("score") == 1:
                            mbid = item.get("recording_mbid")
                            if mbid:
                                fetched_likes.add(mbid)
                                
                    # Pagination
                    if len(feedback) < page_size:
                        break # Last page
                    offset += len(feedback)
                    
                # Sync to User (Thread-Safe)
                if not self.stop_event.is_set():
                    user.sync_likes(fetched_likes)
                    
                    # Schedule UI Update (Main Thread)
                    count_msg = f"Likes Synced: {len(fetched_likes)} tracks."
                    self.root.after(0, lambda: self.set_status(count_msg))
                    
            except Exception as e:
                print(f"Likes Sync Error: {e}")
                self.root.after(0, lambda: self.set_status("Likes Sync Failed."))

        # --------------------------------------------------------
        # LAUNCH
        # --------------------------------------------------------
        
        # Start Listens Worker (This manages the Progress Window lifecycle)
        t_listens = threading.Thread(target=self._run_listen_ingest_worker, daemon=True)
        t_listens.start()
        
        # Start Likes Worker (Runs silently in background, updates status bar)
        t_likes = threading.Thread(target=likes_worker, daemon=True)
        t_likes.start()

    def _run_listen_ingest_worker(self):
        """
        The blocking worker for 'Backwards Crawl' listen ingestion.
        """
        user = self.state.user
        lb_client = ListenBrainzClient(user.token, dry_run=False)
        
        try:
            # 1. Determine constraints
            # Check for intermediate file
            intermediate_listens = user.load_intermediate_listens()
            resume_mode = len(intermediate_listens) > 0
            
            # Find newest listen in MAIN cache
            latest_main_ts = 0
            if not user.listens_df.empty and "listened_at" in user.listens_df.columns:
                latest_main_ts = int(user.listens_df["listened_at"].max().timestamp())

            # Find newest listen in INTERMEDIATE (if resuming)
            # When resuming, we continue fetching backwards from the OLDEST point in the island
            # Actually, standard backwards crawl means we fetch from NOW backwards until we hit KNOWN.
            # If resuming, we already have some 'island' data. We need to fetch OLDER than the island's oldest.
            
            # Let's simplify: Standard "Backfill" strategy.
            # Start from NOW (or max_ts provided). Fetch backwards.
            # Stop when we hit a timestamp <= latest_main_ts.
            
            # Handling Resume:
            # If intermediate exists, we find its MIN timestamp. We fetch older than that.
            
            current_max_ts = int(datetime.now(timezone.utc).timestamp())
            
            if resume_mode:
                # Find oldest timestamp in intermediate to resume crawling backwards from
                timestamps = [l["listened_at"] for l in intermediate_listens]
                if timestamps:
                    current_max_ts = min(timestamps)
                self.root.after(0, lambda: self.progress_win.status_label.config(text=f"Resuming from {datetime.fromtimestamp(current_max_ts)}"))
            else:
                self.root.after(0, lambda: self.progress_win.status_label.config(text="Starting new fetch..."))

            total_fetched = 0
            gap_closed = False
            
            while not self.stop_event.is_set():
                if self.progress_win.cancelled:
                    self.stop_event.set()
                    break

                # Update UI
                self.root.after(0, lambda: self.progress_win.update_progress(0, 0, f"Fetching before {datetime.fromtimestamp(current_max_ts)}..."))
                
                # Fetch
                response = lb_client.get_user_listens(user.username, max_ts=current_max_ts, count=100)
                payload = response.get("payload", {})
                listens = payload.get("listens", [])
                
                if not listens:
                    # No more data from API
                    gap_closed = True # Effectively closed if we hit beginning of time
                    break
                    
                # Process batch
                batch_min_ts = listens[-1]["listened_at"]
                
                # Check overlap with Main Cache
                if batch_min_ts <= latest_main_ts:
                    # We hit the continent!
                    # Filter out overlaps from this batch
                    new_listens = [l for l in listens if l["listened_at"] > latest_main_ts]
                    if new_listens:
                        user.append_to_intermediate_cache(new_listens)
                        total_fetched += len(new_listens)
                    
                    gap_closed = True
                    break
                
                # No overlap yet, save whole batch
                user.append_to_intermediate_cache(listens)
                total_fetched += len(listens)
                current_max_ts = batch_min_ts
                
                self.root.after(0, lambda: self.progress_win.status_label.config(text=f"Fetched {total_fetched} new listens..."))
                
            # End of Loop
            if self.stop_event.is_set():
                self.root.after(0, lambda: messagebox.showinfo("Cancelled", f"Update cancelled. {total_fetched} listens staged safely."))
            elif gap_closed:
                # Merge!
                self.root.after(0, lambda: self.progress_win.status_label.config(text="Merging data..."))
                user.merge_intermediate_cache()
                self.root.after(0, lambda: messagebox.showinfo("Success", f"Update complete. {total_fetched} new listens added."))
                
                # Refresh User
                self.root.after(0, lambda: self.on_user_selected(None))
            else:
                # Finished loop but gap not closed? (Maybe hit API limit or beginning of time)
                # If we hit beginning of time (no more listens), we treat as closed.
                user.merge_intermediate_cache()
                self.root.after(0, lambda: messagebox.showinfo("Done", "Fetched all available history."))
                self.root.after(0, lambda: self.on_user_selected(None))

        except Exception as e:
            print(f"Update Error: {e}")
            self.root.after(0, lambda: messagebox.showerror("Error", f"Update failed: {e}"))
        finally:
            self.stop_event.set() # Stop likes worker too if logic finishes
            self.root.after(0, self.progress_win.destroy)

    def action_import_csv(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not path:
            return

        try:
            df = parsing.parse_generic_csv(path)
            self.state.original_df = df
            self.table_view.show_table(df)
            self.set_status(f"Imported CSV ({len(df)} rows).")
            # Clear current user context if importing generic CSV? 
            # Ideally we keep user context for Enrichment, but note this data isn't "theirs".
        except Exception as e:
            messagebox.showerror("Import Error", str(e))

    # ==================================================================
    # Logic: Reports
    # ==================================================================

    def action_generate_report(self) -> None:
        if self.state.user is None:
            messagebox.showwarning("Warning", "Please select a user first.")
            return

        report_type = self.report_type_var.get()
        days_str = self.days_entry.get()
        enrich_mode = self.enrich_mode_var.get()
        deep_query = self.deep_query_var.get()
        force_cache = self.force_cache_update_var.get()

        # Parse days
        days_arg = None
        try:
            if "," in days_str:
                parts = [int(x.strip()) for x in days_str.split(",")]
                days_arg = (parts[0], parts[1])
            else:
                days_arg = int(days_str)
        except ValueError:
            messagebox.showerror("Error", "Invalid Days format. Use '30' or '0, 365'")
            return

        # Parse Thresholds
        try:
            min_listens = int(self.min_listens_var.get())
            min_likes = int(self.min_likes_var.get())
        except ValueError:
            min_listens = 0
            min_likes = 0

        # Run via ReportEngine (Threaded)
        self.set_status("Generating report...")
        self.progress_win = ProgressWindow(self.root, "Generating Report", "Processing...")
        
        # We need to capture the DataFrame result. ReportEngine doesn't return to us directly in thread.
        # We'll use a callback.
        
        def on_complete(df, meta):
            self.state.original_df = df
            self.state.filtered_df = df
            self.state.last_meta = meta
            self.state.last_mode = report_type
            
            # Render Table
            self.root.after(0, lambda: self.table_view.show_table(df))
            self.root.after(0, lambda: self.progress_win.destroy())
            self.root.after(0, lambda: self.set_status(f"Report Ready: {len(df)} rows."))

        def on_progress(curr, total, msg):
            self.root.after(0, lambda: self.progress_win.update_progress(curr, total, msg))

        # Start Thread
        t = threading.Thread(
            target=self.report_engine.generate_report,
            args=(self.state.user, report_type, days_arg),
            kwargs={
                "enrichment_mode": enrich_mode,
                "deep_query": deep_query,
                "force_cache_update": force_cache,
                "min_listens": min_listens,
                "min_likes": min_likes,
                "progress_callback": on_progress,
                "completion_callback": on_complete,
                "is_cancelled": lambda: self.progress_win.cancelled
            },
            daemon=True
        )
        t.start()

    def action_show_graph(self) -> None:
        """Visualize the current dataframe."""
        if self.state.filtered_df is None or self.state.filtered_df.empty:
            messagebox.showinfo("Info", "No data to graph.")
            return

        mode = self.state.last_mode
        df = self.state.filtered_df

        if mode == "Genre Flavor":
            gui_charts.show_genre_flavor_treemap(df)
        elif mode == "Favorite Artist Trend":
            gui_charts.show_artist_trend_chart(df)
        elif mode == "New Music by Year":
            gui_charts.show_new_music_stacked_bar(df)
        else:
            messagebox.showinfo("Info", f"No graph visualization available for '{mode}'.")

    # ==================================================================
    # Logic: Actions (Like, Playlist, Resolve)
    # ==================================================================

    def action_batch_like(self) -> None:
        """Submit 'Love' feedback for selected tracks."""
        if not self.table_view.tree: return
        
        selected_items = self.table_view.tree.selection()
        if not selected_items:
            messagebox.showinfo("Info", "Select tracks to like.")
            return

        # Collect MBIDs
        mbids = []
        for item in selected_items:
            vals = self.table_view.tree.item(item, "values")
            # We need to map table columns to data. 
            # This is brittle if columns change order.
            # Better: Look up in DataFrame by Index if possible, or use hidden column?
            # Current TableView implementation creates parallel list?
            # Let's rely on column name mapping in TableView or simply assume 
            # we need to find the 'recording_mbid' column index.
            
            # Helper:
            cols = self.table_view.tree["columns"]
            if "recording_mbid" in cols:
                idx = cols.index("recording_mbid")
                mbid = vals[idx]
                if mbid and mbid != "None" and mbid != "":
                    mbids.append(mbid)
        
        mbids = list(set(mbids)) # dedupe
        if not mbids:
            messagebox.showwarning("Warning", "No valid Recording MBIDs found in selection.\nTry 'Resolve Metadata' first.")
            return
            
        if not messagebox.askyesno("Confirm", f"Mark {len(mbids)} tracks as 'Loved' on ListenBrainz?"):
            return

        # Execute
        client = ListenBrainzClient(self.state.user.token, dry_run=self.dry_run_var.get())
        
        success_count = 0
        for mbid in mbids:
            if client.submit_feedback(mbid, 1):
                success_count += 1
                
        messagebox.showinfo("Result", f"Successfully liked {success_count}/{len(mbids)} tracks.")
        # Ideally, update local cache too?
        # self.state.user.liked_mbids.update(mbids)
        # self.state.user.save_cache()

    def action_export_playlist(self) -> None:
        if self.state.filtered_df is None or self.state.filtered_df.empty:
            return

        name = simpledialog.askstring("Playlist Name", "Enter name for playlist:")
        if not name: return
        
        df = self.state.filtered_df
        tracks = []
        
        # Convert DF to list of dicts expected by api_client
        # We need: title, artist, album, mbid
        for _, row in df.iterrows():
            t = {
                "title": row.get("track_name", "Unknown"),
                "artist": row.get("artist", "Unknown"),
                "album": row.get("album", ""),
                "mbid": row.get("recording_mbid", "")
            }
            tracks.append(t)
            
        client = ListenBrainzClient(self.state.user.token, dry_run=self.dry_run_var.get())
        resp = client.create_playlist(name, tracks, "Created via BrainzMRI")
        
        if self.dry_run_var.get():
             messagebox.showinfo("Dry Run", "Playlist creation simulated (check console).")
        elif "playlist_mbid" in resp:
             messagebox.showinfo("Success", f"Playlist created! MBID: {resp['playlist_mbid']}")
        else:
             messagebox.showinfo("Result", f"API Response: {resp}")

    def action_resolve_metadata(self) -> None:
        """
        Attempt to resolve missing MBIDs for the current DataFrame.
        Useful for CSV imports.
        """
        if self.state.filtered_df is None: return
        
        if not messagebox.askyesno("Resolve", "Query MusicBrainz for missing MBIDs?\nThis may take some time."):
            return

        self.progress_win = ProgressWindow(self.root, "Resolving Metadata", "Starting...")
        
        def run_resolve():
            df = self.state.filtered_df
            
            # 1. Identify missing
            # We need to ensure columns exist
            if "recording_mbid" not in df.columns:
                df["recording_mbid"] = ""
                
            # Delegate to enrichment module
            # We need a progress callback ideally, but enrichment.resolve is synchronous currently.
            # We'll just run it.
            
            new_df, resolved_count, failed_count = enrichment.resolve_missing_mbids(df)
            
            self.state.filtered_df = new_df
            self.state.original_df = new_df # Persist resolution
            
            self.root.after(0, lambda: self.table_view.show_table(new_df))
            self.root.after(0, lambda: self.progress_win.destroy())
            self.root.after(0, lambda: messagebox.showinfo("Complete", f"Resolved: {resolved_count}\nFailed: {failed_count}"))

        t = threading.Thread(target=run_resolve, daemon=True)
        t.start()
    
    def action_save_report(self) -> None:
        if self.state.filtered_df is None: return
        
        try:
            # If user context exists, save to user dir, else save to generic
            if self.state.user:
                filepath = reporting.save_report(
                    self.state.filtered_df,
                    user=self.state.user,
                    meta=self.state.last_meta,
                    report_name=None,
                )
            else:
                # Fallback for generic CSV logic
                # For now just dump to local dir
                filepath = f"report_{int(time.time())}.csv"
                self.state.filtered_df.to_csv(filepath, index=False)

            open_file_default(filepath)
            self.set_status(f"{self.state.last_mode} report saved and opened.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save report: {type(e).__name__}: {e}")
            self.set_status("Error: Failed to save report.")

    # ==================================================================
    # Utility
    # ==================================================================

    def set_status(self, text: str) -> None:
        self.status_var.set(text)
        self.status_bar.update_idletasks()

    def load_config(self) -> dict:
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_config(self, data: dict) -> None:
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


# ======================================================================
# Main entry point
# ======================================================================

if __name__ == "__main__":
    # Ensure DPI awareness on Windows
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()