"""
gui.py
Tkinter GUI for BrainzMRI, using reporting, enrichment, and user modules.
"""

import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from idlelib.tooltip import Hovertip

from user import (
    User,
    get_cache_root,
    get_cached_usernames,
    get_user_cache_dir,
)


# ======================================================================
# User Editor Window (New User / Edit User)
# ======================================================================

class UserEditorWindow(tk.Toplevel):
    """
    A modal dialog for creating or editing a user.

    Supports:
    - App Username (letters/numbers only)
    - Last.fm Username
    - ListenBrainz Username
    - Choose ListenBrainz Zip (multi-ZIP, deferred ingestion)
    """

    def __init__(self, parent, existing_user: User | None, on_save_callback):
        super().__init__(parent)
        self.title("User Editor")
        self.resizable(False, False)
        self.parent = parent
        self.existing_user = existing_user
        self.on_save_callback = on_save_callback

        # Pending ZIPs selected during this session
        self.pending_zips = []

        # Build UI
        self._build_ui()

        # If editing, populate fields
        if existing_user:
            self._populate_from_user(existing_user)

        # Make modal
        self.transient(parent)
        self.grab_set()
        self.wait_window(self)

    # ------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------

    def _build_ui(self):
        frm = tk.Frame(self)
        frm.pack(padx=15, pady=15)

        # App Username
        tk.Label(frm, text="App Username (letters/numbers only):").grid(
            row=0, column=0, sticky="w"
        )
        self.ent_app_username = tk.Entry(frm, width=30)
        self.ent_app_username.grid(row=0, column=1, pady=3)

        # Last.fm Username
        tk.Label(frm, text="Last.fm Username:").grid(row=1, column=0, sticky="w")
        self.ent_lastfm = tk.Entry(frm, width=30)
        self.ent_lastfm.grid(row=1, column=1, pady=3)

        # ListenBrainz Username
        tk.Label(frm, text="ListenBrainz Username:").grid(row=2, column=0, sticky="w")
        self.ent_listenbrainz = tk.Entry(frm, width=30)
        self.ent_listenbrainz.grid(row=2, column=1, pady=3)

        # ZIP selection
        tk.Label(frm, text="Previously Ingested ZIPs:").grid(
            row=3, column=0, sticky="nw", pady=(10, 0)
        )
        self.lst_existing_zips = tk.Listbox(frm, width=50, height=5)
        self.lst_existing_zips.grid(row=3, column=1, pady=(10, 0))

        tk.Label(frm, text="New ZIPs to Ingest:").grid(
            row=4, column=0, sticky="nw", pady=(10, 0)
        )
        self.lst_pending_zips = tk.Listbox(frm, width=50, height=5)
        self.lst_pending_zips.grid(row=4, column=1, pady=(10, 0))

        btn_choose_zip = tk.Button(
            frm,
            text="Choose ListenBrainz Zip",
            command=self._choose_zip,
            width=25,
        )
        btn_choose_zip.grid(row=5, column=1, sticky="w", pady=5)

        # Save / Cancel
        frm_buttons = tk.Frame(frm)
        frm_buttons.grid(row=6, column=0, columnspan=2, pady=15)

        tk.Button(
            frm_buttons,
            text="Save User",
            command=self._save_user,
            width=15,
            bg="#4CAF50",
            fg="white",
        ).pack(side="left", padx=5)

        tk.Button(
            frm_buttons,
            text="Cancel",
            command=self.destroy,
            width=15,
            bg="#F44336",
            fg="white",
        ).pack(side="left", padx=5)

    # ------------------------------------------------------------
    # Populate fields for Edit User
    # ------------------------------------------------------------

    def _populate_from_user(self, user: User):
        self.ent_app_username.insert(0, user.username)
        self.ent_app_username.config(state="readonly")

        self.ent_lastfm.insert(0, user.get_lastfm_username() or "")
        self.ent_listenbrainz.insert(0, user.get_listenbrainz_username() or "")

        # Existing ZIPs (read-only)
        zips = user.sources.get("listenbrainz_zips", [])
        for z in zips:
            self.lst_existing_zips.insert(
                tk.END, f"{z.get('path')} (ingested {z.get('ingested_at')})"
            )

    # ------------------------------------------------------------
    # ZIP selection
    # ------------------------------------------------------------

    def _choose_zip(self):
        path = filedialog.askopenfilename(
            title="Select ListenBrainz ZIP",
            filetypes=[("ZIP files", "*.zip")],
        )
        if not path:
            return

        self.pending_zips.append(path)
        self.lst_pending_zips.insert(tk.END, path)

    # ------------------------------------------------------------
    # Save User
    # ------------------------------------------------------------

    def _save_user(self):
        app_username = self.ent_app_username.get().strip()
        lastfm_username = self.ent_lastfm.get().strip() or None
        listenbrainz_username = self.ent_listenbrainz.get().strip() or None

        # Validate app username
        if not app_username:
            messagebox.showerror("Error", "App Username is required.")
            return
        if not app_username.isalnum():
            messagebox.showerror(
                "Error", "App Username must contain only letters and numbers."
            )
            return

        # If editing, update existing user
        if self.existing_user:
            user = self.existing_user
            user.update_sources(lastfm_username, listenbrainz_username)

            # Ingest new ZIPs
            for zip_path in self.pending_zips:
                try:
                    user.ingest_listenbrainz_zip(zip_path)
                except Exception as e:
                    messagebox.showerror(
                        "Error Ingesting ZIP",
                        f"Failed to ingest ZIP '{zip_path}': {type(e).__name__}: {e}",
                    )
                    return

            self.on_save_callback(user.username)
            self.destroy()
            return

        # Creating a new user
        try:
            user = User.from_sources(
                username=app_username,
                lastfm_username=lastfm_username,
                listenbrainz_username=listenbrainz_username,
                listenbrainz_zips=[],
            )
        except Exception as e:
            messagebox.showerror(
                "Error Creating User",
                f"Failed to create user: {type(e).__name__}: {e}",
            )
            return

        # Ingest ZIPs
        for zip_path in self.pending_zips:
            try:
                user.ingest_listenbrainz_zip(zip_path)
            except Exception as e:
                messagebox.showerror(
                    "Error Ingesting ZIP",
                    f"Failed to ingest ZIP '{zip_path}': {type(e).__name__}: {e}",
                )
                return

        self.on_save_callback(user.username)
        self.destroy()

