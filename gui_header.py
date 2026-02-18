"""
gui_header.py
Top-level UI component: User selection, Source management, and Session control.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from idlelib.tooltip import Hovertip
import os
import logging

from gui_user_editor import UserEditorWindow
from user import get_cached_usernames, User
from config import config

class HeaderComponent:
    def __init__(self, parent: tk.Frame, app_state, callback_refresh_data, on_import_callback=None, on_cleared_callback=None, on_import_lastfm_callback=None, **kwargs):
        self.parent = parent
        self.state = app_state
        self.callback_refresh_data = callback_refresh_data # Function to call when source changes
        self.on_import_callback = on_import_callback       # New Callback for CSV import
        self.on_cleared_callback = on_cleared_callback     # Callback for CSV close
        self.on_import_lastfm_callback = on_import_lastfm_callback # Callback: fetch Last.fm loves + show Likes report
        self.lock_cb = kwargs.get("lock_cb", None)
        self.unlock_cb = kwargs.get("unlock_cb", None)

        # Sub-frames
        self.frm_user = tk.Frame(parent)
        self.frm_user.pack(pady=(0, 5))
        
        self.frm_source = tk.Frame(parent)
        self.frm_source.pack(pady=(5, 0))

        # --- User Row ---
        tk.Label(self.frm_user, text="User:").pack(side="left", padx=(5, 5))

        self.user_var = tk.StringVar()
        self.user_dropdown = ttk.Combobox(
            self.frm_user,
            textvariable=self.user_var,
            state="readonly",
            width=25,
        )
        self.user_dropdown.pack(side="left", padx=(0, 10))
        self.user_dropdown.bind("<<ComboboxSelected>>", self.on_user_selected)

        tk.Button(self.frm_user, text="New User", command=self.new_user).pack(side="left", padx=2)
        tk.Button(self.frm_user, text="Edit User", command=self.edit_user).pack(side="left", padx=2)

        # --- Source Row ---
        self.btn_import = tk.Button(self.frm_source, text="Import Playlist File", 
            bg="#FFCC80", command=self.import_playlist)  # use file explorer coloration
        self.btn_import.pack(side="left", padx=(5, 5))

        self.btn_get_listens = tk.Button(
            self.frm_source,
            text="Get New Listenbrainz Data", bg="#353070", fg="white",
            command=self.callback_refresh_data, # Delegated to main controller
            state="disabled"
        )
        self.btn_get_listens.pack(side="left", padx=(0, 10))
        Hovertip(self.btn_get_listens, "Fetch recent listens from ListenBrainz API.\nRequires username in profile.", hover_delay=500)

        # Fetch Last.fm Loves
        self.btn_import_lastfm = tk.Button(
            self.frm_source,
            text="Get Last.fm \u2665",
            command=self.on_import_lastfm_callback,
            bg="#D51007", fg="white",
            state="disabled"
        )
        self.btn_import_lastfm.pack(side="left", padx=(0, 10))
        Hovertip(self.btn_import_lastfm, "Fetch 'Loved Tracks' from Last.fm and show Likes audit.\nRequires Last.fm username.", hover_delay=500)

        self.lbl_source_status = tk.Label(
            self.frm_source,
            text="Active Source: User History",
            fg="gray",
            font=("Segoe UI", 9, "italic")
        )
        self.lbl_source_status.pack(side="left", padx=5)

        self.btn_close_csv = tk.Button(
            self.frm_source,
            text="Close CSV",
            command=self.close_csv,
            bg="#FFCDD2",
            fg="black",
            font=("Segoe UI", 8)
        )
        
        # Initialize
        self.refresh_user_list()

    # ------------------------------------------------------------------
    # User Logic
    # ------------------------------------------------------------------
    def refresh_user_list(self):
        users = get_cached_usernames()
        self.user_dropdown["values"] = users
        if not users:
            self.user_var.set("")

    def on_user_selected(self, event=None):
        username = self.user_var.get().strip()
        if username:
            self.load_user(username)

    def load_user(self, username: str):
        try:
            user = User.from_cache(username)
            self.state.user = user
            
            # Persist
            config.last_user = username
            config.save()

            # UI Updates
            # UI Updates
            self.close_csv(silent=True) # Reset to history mode
            self.lbl_source_status.config(text="Active Source: User History", fg="gray")
            
            # API Button State
            if user.get_listenbrainz_username():
                self.btn_get_listens.config(state="normal")
            else:
                self.btn_get_listens.config(state="disabled")

            if user.get_lastfm_username():
                self.btn_import_lastfm.config(state="normal")
            else:
                self.btn_import_lastfm.config(state="disabled")

        except Exception as e:
            messagebox.showerror("Error Loading User", str(e))

    def new_user(self):
        logging.info("User Action: Clicked 'New User'")
        UserEditorWindow(self.parent, None, self._on_user_saved)

    def edit_user(self):
        logging.info("User Action: Clicked 'Edit User'")
        if not self.state.user:
            messagebox.showerror("Error", "Select a user to edit.")
            return
        # Reload fresh to ensure we have latest state
        try:
            current = User.from_cache(self.state.user.username)
            UserEditorWindow(self.parent, current, self._on_user_saved)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load user for editing: {e}")

    def _on_user_saved(self, username: str):
        self.refresh_user_list()
        self.user_var.set(username)
        self.load_user(username)

    # ------------------------------------------------------------------
    # CSV Logic
    # ------------------------------------------------------------------
    def import_playlist(self):
        logging.info("User Action: Clicked 'Import Playlist'")
        logging.info("TRACE: Header.import_playlist started")
        # We allow import even if no user is loaded, though enrichment might fail.
        # But generally a user context is preferred.
        
        import parsing # Import locally to avoid circular dep risks
        
        if self.lock_cb: self.lock_cb()

        path = filedialog.askopenfilename(
            title="Select Playlist",
            filetypes=[("Playlist Files", "*.jspf *.xspf *.csv *.txt"), ("All files", "*.*")],
        )
        if not path:
            if self.unlock_cb: self.unlock_cb()
            return

        try:
            df = parsing.parse_playlist(path)
            
            # Inject username so enrichment works (if user loaded)
            if self.state.user:
                df["_username"] = self.state.user.username
            
            self.state.playlist_df = df
            self.state.playlist_name = os.path.basename(path)
            
            self.lbl_source_status.config(text=f"Active Source: Playlist ({self.state.playlist_name})", fg="#E65100")
            self.btn_close_csv.pack(side="left", padx=5)
            
            # Modal removed to prevent event loop interference with update_idletasks
            logging.info(f"Import Successful. Loaded {len(df)} tracks.")

            # Signal main GUI to update state
            if self.on_import_callback:
                self.on_import_callback()
                logging.info("TRACE: Header.import_playlist callback sent")
            else:
                logging.info("TRACE: Header.import_playlist callback NOT sent")

        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not parse playlist: {e}")
            if self.unlock_cb: self.unlock_cb()

        # NOTE: Success path does NOT unlock here. The callback chain
        # (on_data_imported → run_report → _on_report_done) manages
        # its own lock lifecycle. Unlocking here would cause a
        # double lock/unlock race that destabilizes Tkinter on Windows.

    def close_csv(self, silent=False):
        if not silent:
            logging.info("User Action: Clicked 'Close CSV'")
        self.state.playlist_df = None
        self.state.playlist_name = None
        
        self.lbl_source_status.config(text="Active Source: User History", fg="gray")
        self.btn_close_csv.pack_forget()

        if self.on_cleared_callback:
            self.on_cleared_callback()

    def lock(self):
        self.user_dropdown.config(state="disabled")
        self.btn_get_listens.config(state="disabled")
        self.btn_import_lastfm.config(state="disabled")
        self.btn_close_csv.config(state="disabled")
        # Disable all buttons in frm_source / frm_user
        for child in self.frm_user.winfo_children():
            try: child.config(state="disabled")
            except: pass
        for child in self.frm_source.winfo_children():
            try: child.config(state="disabled")
            except: pass

    def unlock(self):
        self.user_dropdown.config(state="readonly")
        # Logic to re-enable based on state
        if self.state.user and self.state.user.get_listenbrainz_username():
             self.btn_get_listens.config(state="normal")
        if self.state.user and self.state.user.get_lastfm_username():
             self.btn_import_lastfm.config(state="normal")
        
        if self.state.playlist_df is not None:
             self.btn_close_csv.config(state="normal")
             
        # Re-enable other headers
        for child in self.frm_user.winfo_children():
             if isinstance(child, tk.Button): child.config(state="normal")
        self.user_dropdown.config(state="readonly")
        
        # Primary "Import CSV" button always active
        for child in self.frm_source.winfo_children():
             if isinstance(child, tk.Button) and child != self.btn_get_listens and child != self.btn_import_lastfm and child != self.btn_close_csv:
                 child.config(state="normal")