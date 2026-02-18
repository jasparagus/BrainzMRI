"""
gui_user_editor.py
Tkinter GUI for BrainzMRI - User Creation/Editing.
"""

import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import webbrowser
import logging
from user import User
from config import config

# ======================================================================
# User Editor Window (New User / Edit User)
# ======================================================================

class UserEditorWindow(tk.Toplevel):
    """
    A modal dialog for creating or editing a user.
    """

    def __init__(self, parent, existing_user: User | None, on_save_callback):
        super().__init__(parent)
        self.title("User Editor")
        self.resizable(False, False)
        self.parent = parent
        self.existing_user = existing_user
        self.on_save_callback = on_save_callback

        self.pending_zips = []
        self._auth_token = None  # Temporary token during Last.fm auth flow
        self._obtained_session_key = None  # Session key obtained during this editor session

        self._build_ui()

        if existing_user:
            self._populate_from_user(existing_user)

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
        self.ent_app_username = tk.Entry(frm, width=40)
        self.ent_app_username.grid(row=0, column=1, pady=3)

        # Last.fm Username
        tk.Label(frm, text="Last.fm Username:").grid(row=1, column=0, sticky="w")
        self.ent_lastfm = tk.Entry(frm, width=40)
        self.ent_lastfm.grid(row=1, column=1, pady=3)

        # Last.fm Connection Status (replaces old API Key field)
        tk.Label(frm, text="Last.fm Auth:").grid(row=2, column=0, sticky="w")
        self.frm_lastfm_auth = tk.Frame(frm)
        self.frm_lastfm_auth.grid(row=2, column=1, sticky="w", pady=3)

        # Status label (updated dynamically)
        self.lbl_lastfm_status = tk.Label(self.frm_lastfm_auth, text="Not connected", fg="gray")
        self.lbl_lastfm_status.pack(side="left")

        # Connect button
        self.btn_lastfm_connect = tk.Button(
            self.frm_lastfm_auth,
            text="\U0001F517 Connect Last.fm",
            command=self._start_lastfm_auth,
            bg="#D51007", fg="white",
            font=("TkDefaultFont", 9, "bold"),
        )
        self.btn_lastfm_connect.pack(side="left", padx=(8, 0))

        # Complete Connection button (hidden initially)
        self.btn_lastfm_complete = tk.Button(
            self.frm_lastfm_auth,
            text="Complete Connection",
            command=self._complete_lastfm_auth,
            bg="#4CAF50", fg="white",
        )
        # Not packed yet - shown after browser auth starts

        # Disconnect button (hidden initially)
        self.btn_lastfm_disconnect = tk.Button(
            self.frm_lastfm_auth,
            text="Disconnect",
            command=self._disconnect_lastfm,
            fg="#D51007",
        )
        # Not packed yet - shown when connected

        # Check if shared secret is configured
        if not config.lastfm_shared_secret:
            self.btn_lastfm_connect.config(state="disabled")
            self.lbl_lastfm_status.config(text="Setup needed (see config.json)", fg="orange")

        # ListenBrainz Username
        tk.Label(frm, text="ListenBrainz Username:").grid(row=3, column=0, sticky="w")
        self.ent_listenbrainz = tk.Entry(frm, width=40)
        self.ent_listenbrainz.grid(row=3, column=1, pady=3)

        # ListenBrainz Token
        lbl_token = tk.Label(frm, text="ListenBrainz User Token:")
        lbl_token.grid(row=4, column=0, sticky="w")
        
        self.ent_token = tk.Entry(frm, width=40, show="*") # Masked input
        self.ent_token.grid(row=4, column=1, pady=3)
        
        # Helper link
        link = tk.Label(frm, text="(Get token from your profile)", fg="blue", cursor="hand2")
        link.grid(row=5, column=1, sticky="w")
        link.bind("<Button-1>", lambda e: webbrowser.open("https://listenbrainz.org/profile/"))

        # Separator
        ttk.Separator(frm, orient="horizontal").grid(row=6, column=0, columnspan=2, sticky="ew", pady=10)

        # ZIP selection (New ZIPs only)
        tk.Label(frm, text="Import New ListenBrainz Data (ZIP):").grid(
            row=7, column=0, sticky="nw", pady=(0, 0)
        )
        
        self.lst_pending_zips = tk.Listbox(frm, width=60, height=4)
        self.lst_pending_zips.grid(row=7, column=1, pady=(0, 0))

        btn_choose_zip = tk.Button(
            frm,
            text="Choose ListenBrainz Zip",
            command=self._choose_zip,
            width=25,
        )
        btn_choose_zip.grid(row=8, column=1, sticky="w", pady=5)

        # Save / Cancel
        frm_buttons = tk.Frame(frm)
        frm_buttons.grid(row=9, column=0, columnspan=2, pady=15)

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
        
        # Show Last.fm connection status
        if user.lastfm_session_key:
            self._show_connected_state()
        
        self.ent_listenbrainz.insert(0, user.get_listenbrainz_username() or "")
        
        if user.listenbrainz_token:
            self.ent_token.insert(0, user.listenbrainz_token)

    # ------------------------------------------------------------
    # Last.fm Auth Flow
    # ------------------------------------------------------------

    def _start_lastfm_auth(self):
        """Step 1: Get token, open browser for user approval."""
        try:
            from api_client import LastFMClient
            client = LastFMClient()
            result = client.start_auth()
            self._auth_token = result["token"]
            
            # Open browser for user to approve
            webbrowser.open(result["auth_url"])
            
            # Update UI: hide connect, show complete
            self.btn_lastfm_connect.pack_forget()
            self.btn_lastfm_complete.pack(side="left", padx=(8, 0))
            self.lbl_lastfm_status.config(
                text="Approve in browser, then click \u2192",
                fg="#D51007"
            )
            
        except Exception as e:
            logging.error(f"Last.fm auth start failed: {e}")
            messagebox.showerror("Auth Error", f"Failed to start Last.fm auth:\n{e}", parent=self)

    def _complete_lastfm_auth(self):
        """Step 2: Exchange approved token for permanent session key."""
        if not self._auth_token:
            messagebox.showerror("Error", "No auth token. Please start the connection first.", parent=self)
            return
            
        try:
            from api_client import LastFMClient
            client = LastFMClient()
            session_key = client.complete_auth(self._auth_token)
            self._auth_token = None  # Consumed
            
            # Store on the user (will be saved when Save User is clicked)
            if self.existing_user:
                self.existing_user.lastfm_session_key = session_key
            
            # Store for new user creation
            self._obtained_session_key = session_key
            
            self._show_connected_state()
            messagebox.showinfo("Connected!", "Last.fm account connected successfully.", parent=self)
            
        except Exception as e:
            logging.error(f"Last.fm auth completion failed: {e}")
            # Reset UI
            self.btn_lastfm_complete.pack_forget()
            self.btn_lastfm_connect.pack(side="left", padx=(8, 0))
            self.lbl_lastfm_status.config(text="Auth failed \u2014 try again", fg="#D51007")
            self._auth_token = None
            messagebox.showerror("Auth Error", f"Failed to complete Last.fm auth:\n{e}", parent=self)

    def _disconnect_lastfm(self):
        """Clear the session key."""
        if self.existing_user:
            self.existing_user.lastfm_session_key = ""
        self._obtained_session_key = None
        self._show_disconnected_state()

    def _show_connected_state(self):
        """Update UI to show connected status."""
        self.btn_lastfm_connect.pack_forget()
        self.btn_lastfm_complete.pack_forget()
        self.lbl_lastfm_status.config(text="\u2713 Connected", fg="#4CAF50")
        self.btn_lastfm_disconnect.pack(side="left", padx=(8, 0))

    def _show_disconnected_state(self):
        """Update UI to show disconnected status."""
        self.btn_lastfm_disconnect.pack_forget()
        self.btn_lastfm_complete.pack_forget()
        self.lbl_lastfm_status.config(text="Not connected", fg="gray")
        if config.lastfm_shared_secret:
            self.btn_lastfm_connect.pack(side="left", padx=(8, 0))

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
        token = self.ent_token.get().strip() or None

        # Determine session key: existing user's value, or obtained during this session
        lastfm_session_key = None
        if self.existing_user:
            lastfm_session_key = self.existing_user.lastfm_session_key or None
        elif self._obtained_session_key:
            lastfm_session_key = self._obtained_session_key

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
            user.update_sources(lastfm_username, lastfm_session_key, listenbrainz_username, token)

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
                lastfm_session_key=lastfm_session_key or "",
                listenbrainz_username=listenbrainz_username,
                listenbrainz_token=token,
                listenbrainz_zips=[],
            )
        except Exception as e:
            messagebox.showerror(
                "Error Creating User",
                f"Failed to create user: {type(e).__name__}: {e}",
            )
            return

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