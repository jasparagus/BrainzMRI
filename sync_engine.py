"""
sync_engine.py
Handles background synchronization logic and progress UI.
Extracts threading orchestration from the main GUI.
"""

import threading
import time
import logging
import tkinter as tk
from tkinter import ttk
import parsing
from config import config

# ======================================================================
# Shared UI Components
# ======================================================================

class ProgressWindow(tk.Toplevel):
    """
    A modal dialog showing a progress bar and a Cancel button.
    Thread-safe updates must be handled via callbacks scheduling on main loop.
    """

    def __init__(self, parent, title="Processing..."):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x175")
        self.resizable(False, False)
        self.parent = parent
        self.cancelled = False

        # Center window
        self.update_idletasks()
        try:
            x = parent.winfo_x() + (parent.winfo_width() // 2) - (400 // 2)
            y = parent.winfo_y() + (parent.winfo_height() // 2) - (150 // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            self.geometry("400x175")

        # UI
        self.lbl_status = tk.Label(self, text="Initializing...", anchor="w")
        self.lbl_status.pack(fill="x", padx=20, pady=(20, 5))

        self.lbl_secondary = tk.Label(self, text="", anchor="w", fg="#666666", font=("Segoe UI", 9))
        self.lbl_secondary.pack(fill="x", padx=20, pady=(0, 5))

        self.progress = ttk.Progressbar(self, orient="horizontal", mode="indeterminate")
        self.progress.pack(fill="x", padx=20, pady=5)

        self.btn_cancel = tk.Button(self, text="Cancel", command=self.cancel, width=10)
        self.btn_cancel.pack(pady=20)

        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def update_progress(self, current, total, message):
        """Update the main progress bar."""
        # GUARD: Prevent updates to destroyed widgets
        if self.cancelled or not self.winfo_exists():
            return

        try:
            self.lbl_status.config(text=message)
            if total > 0:
                self.progress.config(mode="determinate")
                pct = (current / total) * 100
                self.progress["value"] = pct
            else:
                self.progress.config(mode="indeterminate")
                self.progress.start(10)
        except Exception:
            pass

    def update_secondary(self, message):
        """Update the secondary status label."""
        # GUARD: Prevent updates to destroyed widgets
        if self.cancelled or not self.winfo_exists():
            return

        try:
            self.lbl_secondary.config(text=message)
        except Exception:
            pass

    def cancel(self):
        self.cancelled = True
        try:
            if self.winfo_exists():
                self.lbl_status.config(text="Cancelling... please wait...")
                self.btn_cancel.config(state="disabled")
        except Exception:
            pass


# ======================================================================
# Sync Manager (The Logic Engine)
# ======================================================================

class SyncManager:
    def __init__(self, user, client, scheduler, callbacks):
        self.user = user
        self.client = client
        self.scheduler = scheduler # e.g. root.after
        self.callbacks = callbacks # Dict of callback functions

        self.barrier = {
            "listens_done": False,
            "likes_done": False,
            "gap_closed": False,
            "likes_count": 0,
            "listens_count": 0,
            "likes_failed": False
        }
        self.cancel_flag = False

    def cancel(self):
        logging.info("SyncManager: Cancellation requested by user.")
        self.cancel_flag = True

    def start(self, start_ts: int, local_head_ts: int):
        threading.Thread(target=self._likes_worker, daemon=True).start()
        threading.Thread(target=self._listens_worker, args=(start_ts, local_head_ts), daemon=True).start()

    def _check_barrier(self):
        """Check if all threads are done and notify main thread."""
        if self.barrier["listens_done"] and self.barrier["likes_done"]:
            self.scheduler(0, self.callbacks["on_complete"], self.barrier)

    # --- Worker: Likes ---
    def _likes_worker(self):
        try:
            self.scheduler(0, self.callbacks["update_secondary"], "Syncing User Likes...")
            logging.info("Starting background Likes sync...")

            username = self.user.get_listenbrainz_username()
            offset = 0
            count = 500
            all_likes_data = []

            while not self.cancel_flag:
                try:
                    # Using get_user_likes (Restored Logic)
                    resp = self.client.get_user_likes(username, offset=offset, count=count)
                except Exception as e:
                    logging.warning(f"Likes API Warning (Page {offset}): {e}")
                    self.barrier["likes_failed"] = True
                    break

                if resp is None or not isinstance(resp, dict):
                    logging.error(f"Likes API Error: Invalid response (None or not dict): {resp}")
                    self.barrier["likes_failed"] = True
                    break

                likes_page = resp.get("feedback", [])
                # Fallbacks for different API response structures
                if not likes_page and "likes" in resp: 
                    likes_page = resp["likes"]
                elif not likes_page and "payload" in resp: 
                    likes_page = resp["payload"].get("likes", [])

                if not likes_page:
                    logging.info("Likes Sync: No more pages found.")
                    break

                all_likes_data.extend(likes_page)
                offset += len(likes_page)

                self.scheduler(0, self.callbacks["update_secondary"],
                               f"Syncing User Likes ({len(all_likes_data)} found)...")

                # Pagination check
                total_count = resp.get("total_count")
                if total_count is None and "payload" in resp: 
                    total_count = resp["payload"].get("total_count")

                if total_count is not None and len(all_likes_data) >= total_count: 
                    break
                if len(likes_page) < count: 
                    break

                time.sleep(config.network_delay)

            if not self.cancel_flag:
                try:
                    new_mbids = parsing.load_feedback(all_likes_data)
                    self.user.sync_likes(new_mbids)
                    self.barrier["likes_count"] = len(new_mbids)
                    logging.info(f"Likes Sync Complete. Saved {len(new_mbids)} items.")
                    self.scheduler(0, self.callbacks["update_secondary"], f"Likes Sync Complete ({len(new_mbids)}).")
                except Exception as e:
                    logging.error(f"Error persisting likes: {e}")
                    self.barrier["likes_failed"] = True
            else:
                logging.info("Likes Sync: Aborted due to cancellation.")

        except Exception as e:
            logging.error(f"Background Likes Sync Failed: {e}", exc_info=True)
            self.barrier["likes_failed"] = True
            self.scheduler(0, self.callbacks["update_secondary"], "Likes Sync Failed.")

        finally:
            self.barrier["likes_done"] = True
            self.scheduler(0, self._check_barrier)

    # --- Worker: Listens ---
    def _listens_worker(self, start_ts, local_head_ts):
        try:
            logging.info(f"Starting Listens fetch. Start TS: {start_ts}, Local Head: {local_head_ts}")
            username = self.user.get_listenbrainz_username()
            fetched_total = 0
            current_max_ts = start_ts
            gap_closed = False
            warning_triggered = False

            while not self.cancel_flag:
                self.scheduler(0, self.callbacks["update_primary"], fetched_total, "Fetching batch...")

                try:
                    # Using get_user_listens (Restored Logic)
                    resp = self.client.get_user_listens(username, max_ts=current_max_ts, count=100)
                except Exception as e:
                    logging.error(f"API Error during listens fetch: {e}")
                    break

                if resp is None or not isinstance(resp, dict):
                    logging.error(f"Listens API Error: Invalid response: {resp}")
                    break

                payload = resp.get("payload", {})
                if payload is None: payload = {}
                listens = payload.get("listens", [])

                if not listens:
                    logging.info("Listens Sync: No more listens found in payload.")
                    gap_closed = True
                    break

                batch_ts = [l["listened_at"] for l in listens]
                batch_min = min(batch_ts)

                # FIX: Filter BEFORE saving/counting to handle overlap accurately
                # Only keep items strictly newer than the local head
                new_items = [x for x in listens if x["listened_at"] > local_head_ts]
                
                if new_items:
                    self.user.append_to_intermediate_cache(new_items)
                    fetched_total += len(new_items)

                # If the batch minimum dips into known history, we are done
                if batch_min <= local_head_ts:
                    logging.info("Listens Sync: Gap closed.")
                    gap_closed = True
                    break
                
                # If we're not done, prepare for next batch
                current_max_ts = batch_min

                # Safety Pause
                if fetched_total > 5000 and not warning_triggered:
                    warning_triggered = True
                    logging.info("Listens Sync: Safety pause triggered at 5000 items.")
                    
                    response_event = threading.Event()
                    user_response = [False]

                    def on_confirm_done(result):
                        user_response[0] = result
                        response_event.set()

                    self.scheduler(0, self.callbacks["request_confirmation"],
                                   f"Fetched {fetched_total} listens so far.\nGap not closed.\nContinue?",
                                   on_confirm_done)

                    response_event.wait()

                    if not user_response[0]:
                        logging.info("Listens Sync: User cancelled at safety pause.")
                        break

                time.sleep(config.network_delay)

            self.barrier["gap_closed"] = gap_closed
            self.barrier["listens_count"] = fetched_total
            if self.cancel_flag:
                logging.info("Listens Sync: Aborted due to cancellation.")

        except Exception as e:
            logging.error(f"Background Listens Sync Failed: {e}", exc_info=True)
            self.scheduler(0, self.callbacks["on_error"], str(e))

        finally:
            self.barrier["listens_done"] = True
            self.scheduler(0, self._check_barrier)