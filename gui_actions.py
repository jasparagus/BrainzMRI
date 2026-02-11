"""
gui_actions.py
Bottom panel for Upstream Actions (Like, Resolve, Playlist).
Encapsulates API interaction logic.
"""

import tkinter as tk
from tkinter import simpledialog, messagebox, ttk, filedialog
from idlelib.tooltip import Hovertip
import threading
import time
import logging
from datetime import datetime

import enrichment
import parsing
from sync_engine import ProgressWindow
from api_client import ListenBrainzClient
# Import the new Sync Manager
from likes_sync import LikeSyncManager
from config import config

# ... [Confirmation Dialog Class remains unchanged] ...
class ActionConfirmDialog(tk.Toplevel):
    """
    A modal dialog that forces the user to choose between
    Live Execution, Dry Run, or Cancel.
    """
    def __init__(self, parent, title, prompt):
        super().__init__(parent)
        self.result = None  # None=Cancel, True=DryRun, False=Live
        self.title(title)
        self.geometry("450x200")
        self.resizable(False, False)
        
        # Center relative to parent
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + 50
            y = parent.winfo_rooty() + 50
            self.geometry(f"+{x}+{y}")
        except:
            pass

        # Content
        lbl = tk.Label(self, text=prompt, wraplength=400, justify="left", font=("Segoe UI", 10))
        lbl.pack(pady=20, padx=20, fill="x")

        # Buttons Frame
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=20)

        # 1. Execute (Red/Bold to indicate risk)
        btn_live = tk.Button(
            btn_frame, text="Execute (LIVE)", 
            bg="#EF5350", fg="white", font=("Segoe UI", 9, "bold"),
            command=self.on_live, width=15
        )
        btn_live.pack(side="left", padx=10)
        Hovertip(btn_live, "SEND data to ListenBrainz API.\nThis will modify your account.")

        # 2. Dry Run (Green/Safe)
        btn_dry = tk.Button(
            btn_frame, text="Dry Run (Test)", 
            bg="#66BB6A", fg="white",
            command=self.on_dry, width=15
        )
        btn_dry.pack(side="left", padx=10)
        Hovertip(btn_dry, "Simulate the action.\nNo data will be sent.")

        # 3. Cancel
        btn_cancel = tk.Button(btn_frame, text="Cancel", command=self.on_cancel, width=10)
        btn_cancel.pack(side="left", padx=10)

        # Modal Setup
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.wait_window()

    def on_live(self):
        self.result = False # dry_run = False
        self.destroy()

    def on_dry(self):
        self.result = True # dry_run = True
        self.destroy()

    def on_cancel(self):
        self.result = None # Abort
        self.destroy()


class ActionComponent:
    def __init__(self, parent: tk.Frame, app_state, table_view, on_update_callback, force_var: tk.BooleanVar = None):
        self.parent = parent
        self.state = app_state
        self.table_view = table_view
        self.on_update_callback = on_update_callback
        self.force_var = force_var

        self.frame = tk.Frame(parent, bg="#ECEFF1", bd=1, relief="groove")
        self.frame.pack(fill="x", side="bottom", padx=5, pady=5) # Always Visible
        
        logging.info("TRACE: ActionComponent initialized")

        # UI Elements
        tk.Label(self.frame, text="Actions:", bg="#ECEFF1", font=("Segoe UI", 9, "bold")).pack(side="left", padx=10, pady=5)

        self.btn_like_all = tk.Button(self.frame, text="Like All", bg="#FFB74D", command=self.action_like_all, state="disabled")
        self.btn_like_all.pack(side="left", padx=5)

        self.btn_like_sel = tk.Button(self.frame, text="Like Selected", bg="#FFCC80", command=self.action_like_selected, state="disabled")
        self.btn_like_sel.pack(side="left", padx=5)

        self.btn_resolve = tk.Button(self.frame, text="Resolve Metadata", bg="#4DD0E1", command=self.action_resolve, state="disabled")
        self.btn_resolve.pack(side="left", padx=5)

        # Export Group
        self.btn_export_lb = tk.Button(self.frame, text="Export to LB", bg="#9575CD", fg="white", command=self.action_export_lb, state="disabled")
        self.btn_export_lb.pack(side="left", padx=5)

        self.btn_export_jspf = tk.Button(self.frame, text="Export JSPF", bg="#B39DDB", fg="white", command=self.action_export_jspf, state="disabled")
        self.btn_export_jspf.pack(side="left", padx=2)

        self.btn_export_xspf = tk.Button(self.frame, text="Export XSPF", bg="#B39DDB", fg="white", command=self.action_export_xspf, state="disabled")
        self.btn_export_xspf.pack(side="left", padx=2)


    def update_state(self, has_mbids: bool, has_missing: bool):
        """Enable/Disable buttons based on available data."""
        logging.info(f"TRACE: ActionComponent.update_state called. mbids={has_mbids}, missing={has_missing}")
        if has_mbids:
            self.btn_like_all.config(state="normal")
            self.btn_like_sel.config(state="normal")
            self.btn_export_lb.config(state="normal")
        else:
            self.btn_like_all.config(state="disabled")
            self.btn_like_sel.config(state="disabled")
            self.btn_export_lb.config(state="disabled")
            
        # Local exports don't strictly require MBIDs, just data
        if self.state.filtered_df is not None and not self.state.filtered_df.empty:
            self.btn_export_jspf.config(state="normal")
            self.btn_export_xspf.config(state="normal")
        else:
            self.btn_export_jspf.config(state="disabled")
            self.btn_export_xspf.config(state="disabled")

        if has_missing:
            self.btn_resolve.config(state="normal")
        else:
            self.btn_resolve.config(state="disabled")

        # Import Likes is always available if a user is loaded (handled by main usually, 
        # but we can leave it enabled here as the handler checks for Last.fm user)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _ask_execution_mode(self, action_name, detail_text):
        """Helper to show the custom dialog and return dry_run boolean or None."""
        dlg = ActionConfirmDialog(
            self.parent, 
            f"Confirm {action_name}", 
            f"{detail_text}\n\nSelect execution mode:"
        )
        return dlg.result

    def _get_client(self, dry_run):
        return ListenBrainzClient(token=self.state.user.listenbrainz_token, dry_run=dry_run)

    def action_like_all(self):
        logging.info("User Action: Clicked 'Like All'")
        df = self.state.filtered_df
        if df is None or "recording_mbid" not in df.columns: return
        valid = df[df["recording_mbid"].notna() & (df["recording_mbid"] != "") & (df["recording_mbid"] != "None")]
        self._run_like_worker(list(valid["recording_mbid"].unique()))

    def action_like_selected(self):
        logging.info("User Action: Clicked 'Like Selected'")
        tree = self.table_view.tree
        if not tree: return
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Select rows first.")
            return
        
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
        
        dry_run = self._ask_execution_mode("Like Tracks", f"You are about to send 'Love' feedback for {count} tracks.")
        if dry_run is None: return 

        client = self._get_client(dry_run)
        mode_str = "[DRY RUN] " if dry_run else ""
        
        win = ProgressWindow(self.frame, f"{mode_str}Liking...")
        
        def worker():
            success = 0
            for i, mbid in enumerate(mbids):
                if win.cancelled: break
                
                def _upd():
                    if win.winfo_exists(): win.update_progress(i, count, f"{mode_str}Liking {i+1}/{count}...")
                win.after(0, _upd)

                try:
                    client.submit_feedback(mbid, 1)
                    success += 1
                except Exception as e:
                    logging.error(f"Like failed: {e}")
                    if "401" in str(e) or "429" in str(e):
                        win.cancelled = True
                        break
                
                if not dry_run: 
                    time.sleep(config.network_delay)
                else:
                    time.sleep(0.05)

            win.after(0, lambda: [win.destroy(), messagebox.showinfo("Done", f"{mode_str}Liked {success} tracks.")])

        threading.Thread(target=worker, daemon=True).start()

    def action_resolve(self):
        logging.info("User Action: Clicked 'Resolve Metadata'")
        if self.state.last_report_df is None: return
        
        win = ProgressWindow(self.frame, "Resolving...")
        df_in = self.state.last_report_df.copy()

        def worker():
            try:
                def cb(c, t, m):
                    if win.winfo_exists(): win.update_progress(c, t, m)
                
                # Use live variable if available, fallback to last params
                if self.force_var:
                    force = self.force_var.get()
                    logging.info(f"Resolution using LIVE force_update={force}")
                else:
                    force = self.state.last_params.get("force_cache_update", False) if self.state.last_params else False
                    logging.info(f"Resolution using STALE force_update={force}")
                
                df_res, ok, fail = enrichment.resolve_missing_mbids(
                    df_in, 
                    force_update=force,
                    progress_callback=cb, 
                    is_cancelled=lambda: win.cancelled
                )

                def _finish():
                    if win.winfo_exists(): win.destroy()
                    
                    # Re-apply Likes status to newly resolved MBIDs
                    liked_mbids = self.state.user.get_liked_mbids()
                    if "recording_mbid" in df_res.columns:
                         df_res["Likes"] = df_res["recording_mbid"].apply(
                             lambda x: 1 if x in liked_mbids else 0
                         )

                    self.state.last_report_df = df_res
                    self.state.original_df = df_res.copy()
                    self.state.filtered_df = df_res.copy()
                    self.on_update_callback(df_res, ok, fail)
                    messagebox.showinfo("Resolution Complete", f"Resolved: {ok}\nFailed: {fail}")

                win.after(0, _finish)
            except Exception as e:
                logging.error(f"Resolution crashed: {e}", exc_info=True)
                win.after(0, lambda: [win.destroy(), messagebox.showerror("Resolution Error", str(e))])



        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Export to ListenBrainz
    # ------------------------------------------------------------------
    def action_export_lb(self):
        logging.info("User Action: Clicked 'Export to LB'")
        df = self.state.filtered_df
        if df is None: return
        
        name = simpledialog.askstring("Export", "Playlist Name:", initialvalue=f"Export {datetime.now().strftime('%Y-%m-%d')}")
        if not name: return

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

        if not tracks:
            messagebox.showwarning("Empty", "No valid tracks found to export.")
            return

        dry_run = self._ask_execution_mode("Export Playlist", f"Create playlist '{name}' with {len(tracks)} tracks?")
        if dry_run is None: return

        client = self._get_client(dry_run)
        mode_str = "[DRY RUN] " if dry_run else ""
        win = ProgressWindow(self.frame, f"{mode_str}Exporting...")

        def worker():
            try:
                win.after(0, lambda: win.update_progress(50, 100, f"{mode_str}Sending..."))
                client.create_playlist(name, tracks)
                win.after(0, lambda: [win.destroy(), messagebox.showinfo("Success", f"{mode_str}Created playlist '{name}'.")])
            except Exception as e:
                err_msg = str(e)
                win.after(0, lambda: [win.destroy(), messagebox.showerror("Error", err_msg)])

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Local Exports (JSPF / XSPF)
    # ------------------------------------------------------------------
    def action_export_jspf(self):
        self._export_local("jspf")

    def action_export_xspf(self):
        self._export_local("xspf")

    def _export_local(self, fmt="jspf"):
        logging.info(f"User Action: Clicked 'Export {fmt.upper()}'")
        df = self.state.filtered_df
        if df is None or df.empty: return

        path = filedialog.asksaveasfilename(
            title=f"Export {fmt.upper()}",
            defaultextension=f".{fmt}",
            filetypes=[(f"{fmt.upper()} Playlist", f"*.{fmt}")]
        )
        if not path: return

        try:
            # We need to construct track objects
            tracks = []
            for _, row in df.iterrows():
                tracks.append(row)
            
            # Use helpers or manual construction?
            # Let's implement simple writers here to avoid circular dependencies with helpers/parser modules if possible,
            # OR better yet, let's use the logic from parsing.py if we put writers there?
            # Actually, `parsing.py` is for ingestion. `reporting` is for analysis.
            # Let's write small local helpers here or in `parsing.py`. 
            # The helpers/YouTubeMusicPlaylistParser.py has good writers. Let's adapt them inline here for simplicity 
            # OR move them to `parsing.py` as `write_jspf`.
            
            # Let's implement them here to keep Action logic together.
            
            if fmt == "jspf":
                self._write_jspf(path, tracks)
            else:
                self._write_xspf(path, tracks)
                
            messagebox.showinfo("Success", f"Exported {len(tracks)} tracks to {os.path.basename(path)}")
            
        except Exception as e:
             messagebox.showerror("Export Failed", str(e))
             logging.error(f"Export failed: {e}", exc_info=True)

    def _write_jspf(self, path, tracks):
        import json
        now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        playlist = {
            "playlist": {
                "title": "BrainzMRI Export",
                "creator": "BrainzMRI",
                "date": now_iso,
                "track": []
            }
        }
        
        for t in tracks:
            track_obj = {
                "title": str(t.get("track_name", "Unknown")),
                "creator": str(t.get("artist", "Unknown")),
                "album": str(t.get("album", "Unknown")),
                "duration": int(t.get("duration_ms", 0))
            }
            mbid = t.get("recording_mbid")
            if mbid and str(mbid) not in ("None", "", "nan"):
                track_obj["identifier"] = [f"https://musicbrainz.org/recording/{mbid}"]
                
            playlist["playlist"]["track"].append(track_obj)
            
        with open(path, "w", encoding="utf-8") as f:
            json.dump(playlist, f, indent=4)

    def _write_xspf(self, path, tracks):
        import xml.etree.ElementTree as ET
        from xml.dom import minidom
        
        root = ET.Element("playlist", version="1", xmlns="http://xspf.org/ns/0/")
        track_list = ET.SubElement(root, "trackList")
        
        for t in tracks:
            track = ET.SubElement(track_list, "track")
            
            ET.SubElement(track, "title").text = str(t.get("track_name", "Unknown"))
            ET.SubElement(track, "creator").text = str(t.get("artist", "Unknown"))
            ET.SubElement(track, "album").text = str(t.get("album", "Unknown"))
            
            ms = int(t.get("duration_ms", 0))
            if ms > 0:
                ET.SubElement(track, "duration").text = str(ms)
                
            mbid = t.get("recording_mbid")
            if mbid and str(mbid) not in ("None", "", "nan"):
                ET.SubElement(track, "identifier").text = f"https://musicbrainz.org/recording/{mbid}"

        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml_str)

    # NEW ACTION HANDLER
    def action_import_likes(self):
        logging.info("User Action: Clicked 'Import Last.fm Likes'")
        if not self.state.user.lastfm_username:
            messagebox.showwarning("Setup", "Please configure your Last.fm username in 'Edit User' first.")
            return
            
        manager = LikeSyncManager(self.state.user, self.state, self.parent)
        manager.import_lastfm_likes()