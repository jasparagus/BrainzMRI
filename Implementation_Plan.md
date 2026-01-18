Here is the proposed implementation strategy to deliver this feature while maintaining the application's stability and thread safety.

### Strategy: "Data Integrity: Auto-Refresh Likes"

This feature requires changes across three layers of the application to ensuring that the "Like" synchronization happens concurrently with the "Listen" download, without causing write conflicts on the user's cache files.

#### **Phase 1: Network Layer (`api_client.py`)**

We need a method to fetch the "Likes" from the API. Unlike listens, likes are stateless (they don't have timestamps we use for sync), so we must fetch the current snapshot.

* **New Method:** `get_user_likes(username, offset, count)`
* **Endpoint:** `GET https://api.listenbrainz.org/1/user/{username}/likes`
* **Logic:** The API returns likes in pages. We will need a loop to fetch *all* likes to ensure we catch everything (and correctly identify un-likes). We should request large batches (e.g., 500 or 1000 at a time) to minimize overhead.

#### **Phase 2: Persistence Layer (`user.py`)**

We need a thread-safe way to update the user's `liked_mbids` set.

* **New Method:** `sync_likes(new_mbids: set)`
* This method will *replace* the internal `self.liked_mbids` with the new set provided by the API. This ensures that tracks you have "un-liked" on the server are removed from your local cache.


* **Constraint:** Since we will have two threads potentially trying to save data (the "New Listens" crawler and the "Likes" fetcher), we must ensure `save_cache()` does not corrupt the JSON files.
* **Architecture Decision:** We will introduce a `threading.Lock` inside the `User` class to serialize access to `save_cache()`.



#### **Phase 3: Orchestration (`gui_main.py`)**

This is where the "Parallel Action" logic lives. We will modify `action_get_new_listens` to spawn a second worker thread.

* **Modification to `action_get_new_listens`:**
1. **Main Worker (Existing):** Continues to crawl "Backwards" for new listens and stages them in `intermediate_listens.jsonl`.
2. **Likes Worker (New):**
* Starts immediately alongside the Main Worker.
* Loops through the `api_client.get_user_likes` pages until all likes are retrieved.
* Collects them into a single `set`.
* Calls `user.sync_likes(new_set)` -> `user.save_cache()`.
* Updates the Status Bar (e.g., "Likes Synced: 1420 tracks").


3. **Synchronization:** The two threads operate independently. The `threading.Lock` in `user.py` ensures they don't crash the file writer if they finish at the exact same moment.



### Execution Plan

1. **Update `api_client.py`:** Implement the `get_user_likes` wrapper.
2. **Update `user.py`:** Add `sync_likes` and the write lock.
3. **Update `gui_main.py`:** Implement the `fetch_likes_worker` inside the update action.