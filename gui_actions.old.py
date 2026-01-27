"""
gui_actions.py
Bottom panel for Upstream Actions (Like, Resolve, Playlist).
Encapsulates API interaction logic.
"""

import tkinter as tk
from tkinter import simpledialog, messagebox
from idlelib.tooltip import Hovertip
import threading
import time
import logging
from datetime import datetime

import enrichment
import parsing
from sync_engine import ProgressWindow
from api_client import ListenBrainzClient

class ActionComponent:
    def __init__(self, parent: tk.Frame, app_state, table_view, on_update_callback):
        self.parent = parent
        self.state = app_state
        self.table_view = table_view
        self.on_update_callback = on_update_callback # Called after Resolve to refresh table

        self.frame = tk.Frame(parent, bg="#ECEFF1", bd=1, relief="groove")
        # Don't pack immediately; set_visible handles that

        # UI Elements
        tk.Label(self.frame, text="Send To ListenBrainz:", bg="#ECEFF1", font=("Segoe UI", 9, "bold")).pack(side="left", padx=10, pady=5)

        self.dry_run_var = tk.BooleanVar(value=True)
        chk = tk.Checkbutton(self.frame, text="Dry Run", variable=self.dry_run_var, bg="#ECEFF1")
        chk.pack(side="left", padx=(0, 15))
        Hovertip(chk, "Simulate actions without sending data.")

        self.btn_like_all = tk.Button(self.frame, text="Like All", bg="#FFB74D", command=self.action_like_all)
        self.btn_like_all.pack(side="left", padx=5)

        self.btn_like_sel = tk.Button(self.frame, text="Like Selected", bg="#FFCC80", command=self.action_like_selected)
        self.btn_like_sel.pack(side="left", padx=5)

        self.btn_resolve = tk.Button(self.frame, text="Resolve Metadata", bg="#4DD0E1", command=self.action_resolve)
        # Packed conditionally

        self.btn_playlist = tk.Button(self.frame, text="Export Playlist", bg="#9575CD", fg="white", command=self.action_export)
        self.btn_playlist.pack(side="left", padx=5)

    def set_visible(self, visible: bool, has_mbids: bool, has_missing: bool):
        if not visible:
            self.frame.pack_forget()
            return
        
        self.frame.pack(fill="x", side="bottom", padx=5, pady=5)
        
        state = "normal" if has_mbids else "disabled"
        self.btn_like_all.config(state=state)
        self.btn_like_sel.config(state=state)

        if has_missing:
            self.btn_resolve.pack(side="left", padx=5)
        else:
            self.btn_resolve.pack_forget()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _get_client(self):
        return ListenBrainzClient(token=self.state.user.listenbrainz_token, dry_run=self.dry_run_var.get())

    def action_like_all(self):
        df = self.state.filtered_df
        if df is None or "recording_mbid" not in df.columns: return
        valid = df[df["recording_mbid"].notna() & (df["recording_mbid"] != "") & (df["recording_mbid"] != "None")]
        self._run_like_worker(list(valid["recording_mbid"].unique()))

    def action_like_selected(self):
        tree = self.table_view.tree
        if not tree: return
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Select rows first.")
            return
        
        # Map visual selection to MBIDs
        df = self.state.filtered_df
        mbids = set()
        children = tree.get_children()
        
        for item in selected:
            try:
                idx = children.index(item)
                if idx < len(df):
                    val = df.iloc[idx]["recording_mbid"]
                    if val and str(val) not in ("None", "", "nan"):
                        mbids.add(val)
            except: pass
        
        if not mbids:
            messagebox.showinfo("Info", "No valid MBIDs in selection.")
            return
        
        self._run_like_worker(list(mbids))

    def _run_like_worker(self, mbids):
        count = len(mbids)
        if count == 0: return
        
        if not messagebox.askyesno("Confirm", f"Like {count} tracks?"): return

        client = self._get_client()
        win = ProgressWindow(self.frame, "Liking...")
        
        def worker():
            success = 0
            for i, mbid in enumerate(mbids):
                if win.cancelled: break
                
                # UI Update
                def _upd():
                    if win.winfo_exists(): win.update_progress(i, count, f"Liking {i+1}/{count}...")
                win.after(0, _upd)

                try:
                    client.submit_feedback(mbid, 1)
                    success += 1
                except Exception as e:
                    logging.error(f"Like failed: {e}")
                    # Stop on 401/429
                    if "401" in str(e) or "429" in str(e):
                        win.cancelled = True
                        break
                
                if not self.dry_run_var.get(): time.sleep(0.3)

            win.after(0, lambda: [win.destroy(), messagebox.showinfo("Done", f"Liked {success} tracks.")])

        threading.Thread(target=worker, daemon=True).start()

    def action_resolve(self):
        if self.state.last_report_df is None: return
        
        win = ProgressWindow(self.frame, "Resolving...")
        df_in = self.state.last_report_df.copy()

        def worker():
            def cb(c, t, m):
                win.after(0, lambda: win.update_progress(c, t, m))
            
            # Run Logic
            df_res, ok, fail = enrichment.resolve_missing_mbids(
                df_in, progress_callback=cb, is_cancelled=lambda: win.cancelled
            )

            # Finish on Main Thread
            def _finish():
                if win.winfo_exists(): win.destroy()
                
                # Update State
                self.state.last_report_df = df_res
                self.state.original_df = df_res.copy()
                self.state.filtered_df = df_res.copy()
                
                # Notify Main to refresh table
                self.on_update_callback(df_res, ok, fail)

            win.after(0, _finish)

        threading.Thread(target=worker, daemon=True).start()

    def action_export(self):
        df = self.state.filtered_df
        if df is None: return
        
        name = simpledialog.askstring("Export", "Playlist Name:", initialvalue=f"Export {datetime.now().strftime('%Y-%m-%d')}")
        if not name: return

        client = self._get_client()
        win = ProgressWindow(self.frame, "Exporting...")

        # Prepare Payload
        tracks = []
        for _, row in df.iterrows():
            mbid = row.get("recording_mbid")
            if not mbid or str(mbid) in ("None", "", "nan"): continue
            
            tracks.append({
                "title": str(row.get("track_name", "Unknown")),
                "artist": str(row.get("artist", "Unknown")),
                "album": str(row.get("album", "Unknown")),
                "mbid": str(mbid)
            })

        def worker():
            try:
                win.after(0, lambda: win.update_progress(50, 100, "Sending..."))
                client.create_playlist(name, tracks)
                win.after(0, lambda: [win.destroy(), messagebox.showinfo("Success", f"Created playlist '{name}' with {len(tracks)} tracks.")])
            except Exception as e:
                # FIX: Capture exception string
                err_msg = str(e)
                win.after(0, lambda: [win.destroy(), messagebox.showerror("Error", err_msg)])

        threading.Thread(target=worker, daemon=True).start()