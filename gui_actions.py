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
from datetime import datetime, timezone
import os
import webbrowser
from urllib.parse import quote_plus

import enrichment
import parsing
from sync_engine import ProgressWindow
from api_client import ListenBrainzClient, LastFMClient
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
        
        # Center relative to parent (no update_idletasks — causes access violations)
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

        self.btn_open_mb = tk.Button(self.frame, text="Search Item On\nMusicBrainz", bg="#81C784", command=self.action_open_musicbrainz)
        self.btn_open_mb.pack(side="left", padx=5, ipadx=5)
        Hovertip(self.btn_open_mb, "Open the selected item's MusicBrainz page\nin your default browser.")

        self.btn_resolve = tk.Button(self.frame, text="Resolve\nMetadata", bg="#4DD0E1", command=self.action_resolve, state="disabled")
        self.btn_resolve.pack(side="left", padx=5, ipadx=5)
        Hovertip(self.btn_resolve, "Search MusicBrainz for metadata (mbids) for the items in the current view.", hover_delay=500)

        self.btn_like_all = tk.Button(self.frame, text="\u2665 All\nEverywhere", bg="#FFB74D", command=self.action_like_all, state="disabled")
        self.btn_like_all.pack(side="left", padx=5, ipadx=5)
        Hovertip(self.btn_like_all, "Like all tracks in the current view\non both ListenBrainz and Last.fm.", hover_delay=500)

        self.btn_like_sel = tk.Button(self.frame, text="\u2665 Selected\non ListenBrainz", bg="#353070", fg="white", command=self.action_like_selected, state="disabled")
        self.btn_like_sel.pack(side="left", padx=5, ipadx=5)
        Hovertip(self.btn_like_sel, "Like selected tracks on ListenBrainz.", hover_delay=500)

        self.btn_like_lfm = tk.Button(self.frame, text="\u2665 Selected\non Last.fm", bg="#D51007", fg="white", command=self.action_like_selected_lastfm, state="disabled")
        self.btn_like_lfm.pack(side="left", padx=5, ipadx=5)
        Hovertip(self.btn_like_lfm, "Love selected tracks on Last.fm.\nRequires Last.fm authentication.", hover_delay=500)

        # Export Group
        self.btn_export_lb = tk.Button(self.frame, text="Export Tracklist\nto ListenBrainz", bg="#9575CD", fg="#FFFEDD", command=self.action_export_lb, state="disabled")
        self.btn_export_lb.pack(side="left", padx=5, ipadx=5)
        Hovertip(self.btn_export_lb, "Export tracklist to ListenBrainz.", hover_delay=500)

        self.btn_export_jspf = tk.Button(self.frame, text="Export Tracklist\nto JSPF File", bg="#B39DDB", fg="white", command=self.action_export_jspf, state="disabled")
        self.btn_export_jspf.pack(side="left", padx=5, ipadx=5)
        Hovertip(self.btn_export_jspf, "Export tracklist to JSPF file for upload to ListenBrainz or sharing.", hover_delay=500)

        self.btn_export_xspf = tk.Button(self.frame, text="Export Tracklist\nto XSPF File", bg="#B39DDB", fg="white", command=self.action_export_xspf, state="disabled")
        self.btn_export_xspf.pack(side="left", padx=5, ipadx=5)
        Hovertip(self.btn_export_xspf, "Export tracklist to XSPF file for sharing with various apps.", hover_delay=500)


    def update_state(self, has_mbids: bool, has_missing: bool):
        """Enable/Disable buttons based on available data."""
        logging.info(f"TRACE: ActionComponent.update_state called. mbids={has_mbids}, missing={has_missing}")
        if has_mbids:
            self.btn_like_all.config(state="normal")
            self.btn_like_sel.config(state="normal")
            self.btn_export_lb.config(state="normal")
            # Last.fm like button requires session key
            if self.state.user and self.state.user.lastfm_session_key:
                self.btn_like_lfm.config(state="normal")
            else:
                self.btn_like_lfm.config(state="disabled")
        else:
            self.btn_like_all.config(state="disabled")
            self.btn_like_sel.config(state="disabled")
            self.btn_like_lfm.config(state="disabled")
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

    def action_open_musicbrainz(self):
        """Open the MusicBrainz page for the first selected row's entity."""
        logging.info("User Action: Clicked 'Open in MusicBrainz'")
        df = self.state.filtered_df
        if df is None or df.empty:
            messagebox.showwarning("No Data", "Generate a report first.")
            return

        tree = self.table_view.tree
        if not tree: 
            messagebox.showwarning("No Data", "Generate a report first.")
            return
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Select a row in the table first.")
            return

        children = tree.get_children()
        try:
            idx = children.index(selected[0])
        except ValueError:
            messagebox.showwarning("Error", "Could not locate selected row.")
            return
        row = df.iloc[idx]

        # Try most specific MBID first: recording > release > artist
        mbid_map = [
            ("recording_mbid", "recording"),
            ("release_mbid",   "release"),
            ("artist_mbid",    "artist"),
        ]
        for col, entity_type in mbid_map:
            mbid = row.get(col)
            if mbid and str(mbid).strip() and str(mbid) != "nan":
                url = f"https://musicbrainz.org/{entity_type}/{mbid}"
                logging.info(f"Opening MusicBrainz {entity_type}: {url}")
                webbrowser.open(url)
                return

        # No MBID available — fall back to search
        search_type_map = [
            ("track_name",  "recording"),
            ("album",       "release_group"),
            ("artist",      "artist"),
        ]
        for col, search_type in search_type_map:
            name = row.get(col)
            if name and str(name).strip() and str(name) != "nan":
                query = quote_plus(str(name))
                url = f"https://musicbrainz.org/search?query={query}&type={search_type}&limit=25&method=indexed"
                logging.info(f"Opening MusicBrainz search ({search_type}): {url}")
                webbrowser.open(url)
                return

        messagebox.showwarning("No Data", "Selected row has no identifiable entity.")

    def action_like_all(self):
        logging.info("User Action: Clicked 'Like All Everywhere'")
        df = self.state.filtered_df
        if df is None or "recording_mbid" not in df.columns: return
        valid = df[df["recording_mbid"].notna() & (df["recording_mbid"] != "") & (df["recording_mbid"] != "None")]
        mbids = list(valid["recording_mbid"].unique())
        
        # Also collect artist/track names for Last.fm
        tracks_for_lastfm = []
        if self.state.user and self.state.user.lastfm_session_key:
            for _, row in valid.drop_duplicates(subset=["recording_mbid"]).iterrows():
                artist = str(row.get("artist", "")).strip()
                track = str(row.get("track_name", "")).strip()
                if artist and track:
                    tracks_for_lastfm.append({"artist": artist, "track": track})
        
        # Run LB likes first
        self._run_like_worker(mbids, also_lastfm=tracks_for_lastfm if tracks_for_lastfm else None)

    def action_like_selected(self):
        logging.info("User Action: Clicked 'Like Selected ListenBrainz'")
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

    def action_like_selected_lastfm(self):
        """Love selected tracks on Last.fm."""
        logging.info("User Action: Clicked 'Like Selected Last.fm'")
        if not self.state.user or not self.state.user.lastfm_session_key:
            messagebox.showwarning("Setup", "Last.fm not authenticated.\nGo to Edit User → 'Connect Last.fm' first.")
            return
        
        tree = self.table_view.tree
        if not tree: return
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Select rows first.")
            return
        
        df = self.state.filtered_df
        children = tree.get_children()
        tracks = []
        
        for item in selected:
            try:
                idx = children.index(item)
                if idx < len(df):
                    row = df.iloc[idx]
                    artist = str(row.get("artist", "")).strip()
                    track = str(row.get("track_name", "")).strip()
                    if artist and track:
                        tracks.append({"artist": artist, "track": track})
            except: pass
        
        if not tracks:
            messagebox.showinfo("Info", "No valid artist/track names in selection.")
            return
        
        self._run_lastfm_love_worker(tracks)

    def _run_like_worker(self, mbids, also_lastfm=None):
        count = len(mbids)
        if count == 0: return
        
        dry_run = self._ask_execution_mode("Like Tracks", f"You are about to send 'Love' feedback for {count} tracks.")
        if dry_run is None: return 

        client = self._get_client(dry_run)
        mode_str = "[DRY RUN] " if dry_run else ""
        
        win = ProgressWindow(self.frame, f"{mode_str}Liking...")
        
        def worker():
            success = 0
            liked_set = set()
            for i, mbid in enumerate(mbids):
                if win.cancelled: break
                
                def _upd():
                    if win.winfo_exists(): win.update_progress(i, count, f"{mode_str}Liking {i+1}/{count}...")
                win.after(0, _upd)

                try:
                    client.submit_feedback(mbid, 1)
                    success += 1
                    liked_set.add(mbid)
                except Exception as e:
                    logging.error(f"Like failed: {e}")
                    if "401" in str(e) or "429" in str(e):
                        win.cancelled = True
                        break
                
                if not dry_run: 
                    client.wait_for_rate_limit()
                else:
                    time.sleep(0.05)

            def _finish():
                win.destroy()
                # Update local state and refresh table (live mode only)
                if not dry_run and success > 0:
                    self.state.user.liked_recording_mbids.update(liked_set)
                    self.state.user._save_likes()
                    all_liked = self.state.user.get_liked_mbids()
                    for df in [self.state.filtered_df, self.state.last_report_df, self.state.original_df]:
                        if df is not None and "recording_mbid" in df.columns:
                            df["Likes"] = df["recording_mbid"].apply(lambda x: 1 if x in all_liked else 0)
                    if self.state.filtered_df is not None:
                        self.table_view.show_table(self.state.filtered_df)
                messagebox.showinfo("Done", f"{mode_str}Liked {success} tracks on ListenBrainz.")
                
                # Chain Last.fm love if requested ("Like All Everywhere")
                if also_lastfm and not dry_run and not win.cancelled:
                    if self.state.user and self.state.user.lastfm_session_key:
                        self._run_lastfm_love_worker(also_lastfm)
                    else:
                        messagebox.showwarning("Last.fm Skipped",
                            "Last.fm account not connected — only ListenBrainz likes were sent.\n"
                            "Connect Last.fm in Edit User to sync likes to both services.")

            win.after(0, _finish)

        threading.Thread(target=worker, daemon=True).start()

    def _run_lastfm_love_worker(self, tracks):
        """Push tracks as loved on Last.fm via track.love API."""
        count = len(tracks)
        if count == 0: return
        
        if not self.state.user or not self.state.user.lastfm_session_key:
            messagebox.showwarning("Setup", "Last.fm not authenticated.")
            return
        
        dry_run = self._ask_execution_mode("Love on Last.fm", f"You are about to love {count} tracks on Last.fm.")
        if dry_run is None: return
        
        lfm_client = LastFMClient()
        session_key = self.state.user.lastfm_session_key
        mode_str = "[DRY RUN] " if dry_run else ""
        
        win = ProgressWindow(self.frame, f"{mode_str}Loving on Last.fm...")
        
        def worker():
            success = 0
            for i, t in enumerate(tracks):
                if win.cancelled: break
                
                def _upd(i=i):
                    if win.winfo_exists(): win.update_progress(i, count, f"{mode_str}Loving {i+1}/{count}...")
                win.after(0, _upd)
                
                try:
                    if not dry_run:
                        lfm_client.love_track(t["artist"], t["track"], session_key)
                    success += 1
                except Exception as e:
                    logging.error(f"Last.fm love failed: {t['artist']} - {t['track']}: {e}")
                
                if not dry_run:
                    lfm_client.wait_for_rate_limit()
                else:
                    time.sleep(0.05)
            
            def _finish():
                win.destroy()
                messagebox.showinfo("Done", f"{mode_str}Loved {success} tracks on Last.fm.")
            
            win.after(0, _finish)
        
        threading.Thread(target=worker, daemon=True).start()

    def action_resolve(self):
        logging.info("User Action: Clicked 'Resolve Metadata'")
        if self.state.last_report_df is None: return
        
        win = ProgressWindow(self.frame, "Resolving Metadata...")
        df_in = self.state.last_report_df.copy()

        def worker():
            try:
                def cb(c, t, m):
                    if not win.winfo_exists(): return
                    # m format: "Resolving [N OK / M Fail]  ✓ Artist - Track"
                    # Split into header (counts) and detail (item result)
                    parts = m.split("  ", 1)
                    header = parts[0]  # "Resolving [N OK / M Fail]"
                    detail = parts[1] if len(parts) > 1 else ""  # "✓ Artist - Track"
                    win.update_progress(c, t, header)
                    if detail:
                        win.update_secondary(detail)
                
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
        skipped = 0
        for _, row in df.iterrows():
            mbid = row.get("recording_mbid")
            if not mbid or str(mbid) in ("None", "", "nan"):
                skipped += 1
                continue
            
            tracks.append({
                "title": str(row.get("track_name", "Unknown")),
                "artist": str(row.get("artist", "Unknown")),
                "album": str(row.get("album", "Unknown")),
                "mbid": str(mbid)
            })

        if not tracks:
            messagebox.showwarning("Empty", "No tracks with valid recording MBIDs found.\n\nUse 'Resolve Metadata' to resolve MBIDs before exporting.")
            return

        # Warn user about skipped tracks
        skip_msg = ""
        if skipped > 0:
            skip_msg = f"\n\n⚠ {skipped} track(s) lack recording MBIDs and will be excluded."

        dry_run = self._ask_execution_mode("Export Playlist", f"Create playlist '{name}' with {len(tracks)} tracks?{skip_msg}")
        if dry_run is None: return

        client = self._get_client(dry_run)
        mode_str = "[DRY RUN] " if dry_run else ""
        win = ProgressWindow(self.frame, f"{mode_str}Exporting...")

        def worker():
            try:
                win.after(0, lambda: win.update_progress(50, 100, f"{mode_str}Sending..."))
                client.create_playlist(name, tracks)
                win.after(0, lambda: [win.destroy(), messagebox.showinfo("Success", f"{mode_str}Created playlist '{name}' ({len(tracks)} tracks).")])
            except Exception as e:
                err_msg = str(e)
                # Log the full response body for API errors
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        logging.error(f"API Response Body: {e.response.text}")
                    except Exception:
                        pass
                logging.error(f"Playlist export failed: {err_msg}")
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

