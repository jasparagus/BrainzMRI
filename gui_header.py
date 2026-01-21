"""
gui_header.py
Top-level UI component: User selection, Source management, and Session control.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from idlelib.tooltip import Hovertip
import os

from gui_user_editor import UserEditorWindow
from user import get_cached_usernames, User
from config import config

class HeaderComponent:
    def __init__(self, parent: tk.Frame, app_state, callback_refresh_data):
        self.parent = parent
        self.state = app_state
        self.callback_refresh_data = callback_refresh_data # Function to call when source changes

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
        tk.Button(self.frm_source, text="Import CSV...", command=self.import_csv).pack(side="left", padx=(5, 5))

        self.btn_get_listens = tk.Button(
            self.frm_source,
            text="Get New Listens",
            command=self.callback_refresh_data, # Delegated to main controller
            state="disabled"
        )
        self.btn_get_listens.pack(side="left", padx=(0, 10))
        Hovertip(self.btn_get_listens, "Fetch recent listens from ListenBrainz API.\nRequires username in profile.", hover_delay=500)

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
            self.close_csv() # Reset to history mode
            self.lbl_source_status.config(text="Active Source: User History", fg="gray")
            
            # API Button State
            if user.get_listenbrainz_username():
                self.btn_get_listens.config(state="normal")
            else:
                self.btn_get_listens.config(state="disabled")

        except Exception as e:
            messagebox.showerror("Error Loading User", str(e))

    def new_user(self):
        UserEditorWindow(self.parent, None, self._on_user_saved)

    def edit_user(self):
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
    def import_csv(self):
        if not self.state.user:
            messagebox.showerror("Error", "Please load a user first (to provide context).")
            return

        import parsing # Import locally to avoid circular dep risks
        
        path = filedialog.askopenfilename(
            title="Select CSV Playlist",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            df = parsing.parse_generic_csv(path)
            # Inject username so enrichment works
            df["_username"] = self.state.user.username
            
            self.state.playlist_df = df
            self.state.playlist_name = os.path.basename(path)
            
            self.lbl_source_status.config(text=f"Active Source: Playlist ({self.state.playlist_name})", fg="#E65100")
            self.btn_close_csv.pack(side="left", padx=5)
            
            # Signal main to refresh view (handled by caller observing state, or explicit callback?)
            # For this Phase, we'll rely on the user clicking "Generate" next, 
            # but ideally we'd trigger a refresh.
            messagebox.showinfo("Import Successful", f"Loaded {len(df)} tracks. Click 'Generate Report' to view.")

        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not parse CSV: {e}")

    def close_csv(self):
        self.state.playlist_df = None
        self.state.playlist_name = None
        
        self.lbl_source_status.config(text="Active Source: User History", fg="gray")
        self.btn_close_csv.pack_forget()