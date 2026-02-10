"""
likes_sync.py
Logic for Cross-Platform Like Synchronization.
"""

import pandas as pd
import threading
import time
from tkinter import messagebox

import enrichment
from sync_engine import ProgressWindow
from config import config

class LikeSyncManager:
    def __init__(self, user, app_state, parent_window):
        self.user = user
        self.state = app_state
        self.parent = parent_window
        # Import client here to avoid circular imports if possible, or pass it in
        from api_client import ListenBrainzClient, LastFMClient
        self.lb_client = ListenBrainzClient(user.listenbrainz_token)
        self.lfm_client = LastFMClient()

    def import_lastfm_likes(self):
        """
        Fetch Last.fm likes, resolve them to MBIDs, and push to ListenBrainz.
        """
        lfm_user = self.user.lastfm_username
        if not lfm_user:
            messagebox.showerror("Error", "No Last.fm username configured.")
            return

        # FIX: Check for API Key presence
        if not self.lfm_client.api_key:
            messagebox.showerror("Setup Error", "Last.fm API Key is missing.\nPlease add 'lastfm_api_key' to your config.json.")
            return

        win = ProgressWindow(self.parent, "Importing Last.fm Likes...")

        def worker():
            try:
                # 1. Fetch
                win.update_progress(0, 0, "Fetching Last.fm Loves...")
                loves = self.lfm_client.get_user_loved_tracks(lfm_user)
                
                if not loves:
                    win.after(0, lambda: [win.destroy(), messagebox.showinfo("Info", "No loved tracks found on Last.fm.")])
                    return

                # 2. Prepare Data
                df_loves = pd.DataFrame(loves)
                df_loves.rename(columns={"track": "track_name"}, inplace=True)
                df_loves["album"] = "" 
                
                existing_mbids = self.user.get_liked_mbids()
                
                # 3. Resolve Missing MBIDs (Cached & Persistent)
                win.update_progress(10, 100, f"Resolving {len(df_loves)} tracks...")
                
                df_resolved, ok, fail = enrichment.resolve_missing_mbids(
                    df_loves, 
                    progress_callback=lambda c, t, m: win.after(0, lambda: win.update_progress(c, t, m)),
                    is_cancelled=lambda: win.cancelled
                )
                
                if win.cancelled: return

                # 4. Filter for New Likes (The Diff)
                valid_new_mbids = []
                new_tracks_info = [] # For user review
                
                for _, row in df_resolved.iterrows():
                    mbid = row.get("recording_mbid")
                    if mbid and str(mbid) not in ["", "nan", "None"]:
                        if mbid not in existing_mbids:
                            valid_new_mbids.append(mbid)
                            new_tracks_info.append(f"{row['artist']} - {row['track_name']}")

                # 5. User Review / Confirmation
                if not valid_new_mbids:
                    win.after(0, lambda: [win.destroy(), messagebox.showinfo("Done", "All Last.fm likes are already synced!")])
                    return

                count = len(valid_new_mbids)
                
                # Create preview text (Top 5)
                preview_list = "\n".join(new_tracks_info[:5])
                if count > 5:
                    preview_list += f"\n...and {count - 5} more."
                
                confirm_msg = (
                    f"Found {count} NEW likes to add to ListenBrainz.\n\n"
                    f"Examples:\n{preview_list}\n\n"
                    "Proceed with import?"
                )

                # Threading trick: We need to pause the worker to ask the user
                # We can't use messagebox directly in thread usually, but askyesno blocks.
                # However, it must run on main thread.
                
                response_container = {"ok": False}
                done_event = threading.Event()

                def ask_user():
                    response_container["ok"] = messagebox.askyesno("Confirm Import", confirm_msg, parent=self.parent)
                    done_event.set()

                win.after(0, ask_user)
                done_event.wait()

                if not response_container["ok"]:
                    win.after(0, lambda: [win.destroy(), messagebox.showinfo("Cancelled", "Import aborted.")])
                    return

                # 6. Push to ListenBrainz
                win.after(0, lambda: win.update_progress(0, count, "Submitting to ListenBrainz..."))
                
                success = 0
                for i, mbid in enumerate(valid_new_mbids):
                    if win.cancelled: break
                    try:
                        self.lb_client.submit_feedback(mbid, 1) # Love
                        success += 1
                        self.user.liked_recording_mbids.add(mbid)
                    except Exception as e:
                        print(f"Failed to submit {mbid}: {e}")
                    
                    if i % 5 == 0:
                        win.after(0, lambda i=i: win.update_progress(i, count, f"Submitting {i}/{count}..."))
                    
                    time.sleep(config.network_delay) 

                self.user._save_likes()
                win.after(0, lambda: [win.destroy(), messagebox.showinfo("Success", f"Imported {success} new likes.")])

            except Exception as e:
                err = str(e)
                win.after(0, lambda: [win.destroy(), messagebox.showerror("Error", err)])

        threading.Thread(target=worker, daemon=True).start()