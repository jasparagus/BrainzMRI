# Likes for Days: Post-Implementation Audit & Fixes

Post-implementation review of all changes made to enable the new "Likes for Days" report mode. This plan covers bug fixes, standards compliance corrections, and documentation updates.

---

## Findings Summary

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | **Critical** | `report_engine.py` | Empty-data guard clause rejects Likes for Days when `df` is empty |
| 2 | **Critical** | `gui_main.py` | `parsing` import scoped inside LB sync `try` block; used later in resolve block |
| 3 | **High** | `gui_main.py` | Late-binding lambda closure bug in `resolve_cb` — `c`, `t`, `header`, `detail` variables captured by reference |
| 4 | **Medium** | `reporting.py` | `get_resolved_likes` missing keyword-only enforcement (`*` separator) |
| 5 | **Medium** | `gui_actions.py` | `LikesSyncPromptDialog` uses fixed `geometry("+x+y")` centering instead of deferred centering via `after(10, _center)` |
| 6 | **Low** | `gui_main.py` | `resolve_cb` calls `win.update_secondary(detail)` from background thread without routing through `self.root.after()` |
| 7 | **Low** | `README.md` | Raw task prompt appended to end of README; needs replacement with feature documentation |

---

## Proposed Changes

### Bug Fixes

---

#### [FIX 1 — Critical] [MODIFY] [report_engine.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/report_engine.py)

The existing empty-data guard clause at [line 133](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/report_engine.py#L133) only exempts `mode == "Likes"`:

```python
if df.empty and mode != "Likes":
```

"Likes for Days" will also be called with an empty or minimal `df` when the user has a likes cache but limited listening history. This guard incorrectly aborts the pipeline with "No data available." before it reaches the specialized handler, which has its own graceful empty-data checks.

**Fix:** Extend the exemption to include `"Likes for Days"`:

```diff
-        if df.empty and mode != "Likes":
+        if df.empty and mode not in ("Likes", "Likes for Days"):
```

---

#### [FIX 2 — Critical] [MODIFY] [gui_main.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py)

`import parsing` appears at [line 614](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py#L614), inside the `try` block that handles LB likes syncing. If the user has no ListenBrainz username configured (i.e., `lb_user` is falsy), that `try` block is skipped entirely, and `parsing` is never imported. The resolve block at [line 660](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py#L660) then calls `parsing.make_track_key(...)`, raising an unhandled `NameError` that crashes the worker thread.

This would occur when a user has Last.fm loves but no ListenBrainz username — a supported configuration.

**Fix:** Move `import parsing` out of the LB sync `try` block to the top of the `sync_and_resolve` block, ensuring it's available regardless of which sync paths execute:

```diff
                     if sync_and_resolve:
+                        import parsing
                         cb(5, 100, "Syncing ListenBrainz likes...")
                         lb_user = self.state.user.get_listenbrainz_username()
                         if lb_user:
                             try:
                                 from api_client import ListenBrainzClient
-                                import parsing
```

---

#### [FIX 3 — High] [MODIFY] [gui_main.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py)

The `resolve_cb` lambda at [lines 671-674](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py#L671-L674) schedules a `root.after(0, lambda: [...])` that captures `c`, `t`, `header`, and `detail` by closure reference, not by value. Because `resolve_cb` is called rapidly from the resolver loop, by the time the scheduled lambda actually fires on the main thread, those variables have already advanced to the next iteration's values. This causes stale/mismatched progress updates — the progress bar counter jumps erratically and the secondary label shows wrong items.

This is the same class of late-binding bug that Instantiation.md §1.2 ("Exception Scope Safety") warns about for `lambda` inside handlers.

**Fix:** Capture values at scheduling time using default arguments:

```diff
                                 def resolve_cb(c, t, m):
                                     if not win.cancelled:
                                         parts = m.split("  ", 1)
                                         header = parts[0]
                                         detail = parts[1] if len(parts) > 1 else ""
-                                        self.root.after(0, lambda: [
-                                            win.update_progress(c, t, header),
-                                            win.update_secondary(detail) if detail else None
-                                        ])
+                                        self.root.after(0, lambda _c=c, _t=t, _h=header, _d=detail: [
+                                            win.update_progress(_c, _t, _h),
+                                            win.update_secondary(_d) if _d else None
+                                        ])
```

---

#### [FIX 4 — Medium] [MODIFY] [reporting.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/reporting.py)

`get_resolved_likes` at [line 946](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/reporting.py#L946) is a new pipeline function but lacks the `*` keyword-only separator required by §1.2 ("Keyword-Only Enforcement") of the Instantiation document for all logic pipeline functions.

**Fix:** Add `*` separator after `self`-like first parameter:

```diff
 def get_resolved_likes(
+    *,
     df: pd.DataFrame,
     liked_mbids: set,
```

> [!NOTE]
> The call site in [report_engine.py line 192](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/report_engine.py#L192) already uses keyword arguments, so this is a standards compliance fix that won't break the calling code.

---

#### [FIX 5 — Medium] [MODIFY] [gui_actions.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_actions.py)

`LikesSyncPromptDialog.__init__` at [line 172](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_actions.py#L172) centers the window using immediate `self.geometry(f"+{x}+{y}")` in a `try` block. This violates §3.9 ("Deferred Window Centering") of the Instantiation document. On Windows, querying `winfo_rootx()` / `winfo_rooty()` on a freshly-created `Toplevel` before Tcl has processed pending events can return `0, 0` or stale values, placing the dialog at the screen origin rather than centered on the parent.

The existing `ResolveConfirmDialog` has the same pattern (it predates the deferred centering standard), but new dialogs should follow the correct pattern.

**Fix:** Replace the immediate centering with `self.after(10, _center)`:

```diff
-        try:
-            x = parent.winfo_rootx() + 50
-            y = parent.winfo_rooty() + 50
-            self.geometry(f"+{x}+{y}")
-        except Exception:
-            pass
+        def _center():
+            try:
+                x = parent.winfo_rootx() + 50
+                y = parent.winfo_rooty() + 50
+                self.geometry(f"+{x}+{y}")
+            except Exception:
+                pass
+        self.after(10, _center)
```

---

#### [FIX 6 — Low] [MODIFY] [gui_main.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py)

Within the `resolve_cb` lambda at [line 673](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py#L673), `win.update_secondary(detail)` is called inside a `root.after(0, ...)` lambda which is correct. However, the list-expression `[win.update_progress(...), win.update_secondary(...)]` evaluates `update_secondary` as a conditional expression (`... if detail else None`), which is fine functionally but unconventional. This is already resolved by Fix 3 above — once the lambda uses default-arg capture, the pattern becomes clean.

No separate action required; covered by Fix 3.

---

### Documentation Updates

---

#### [MODIFY] [README.md](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/README.md)

The raw task prompt currently appended at [lines 224-233](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/README.md#L224-L233) should be replaced with proper feature documentation, matching the tone and structure of the existing feature entries in the README.

1. **§ Key Features → Advanced Analysis & Reporting:** Add a bullet for "Likes for Days" describing the analysis mode:
   - Cross-service liked tracks with 2+ listens, weighted by MusicBrainz-verified track durations.
   - Dual Top-N lists (Tracks and Artists), sorted by total listen duration.

2. **§ Key Features → Rich Visualizations:** Add a bullet for the dual treemap visualization.

3. **§ Key Features → Metadata Enrichment:** Add a bullet for the duration cache (`cache/global/duration_cache.json`).

4. **§ Likes For Days (lines 224-233):** Remove the raw task prompt entirely. It is implementation scaffolding, not documentation.

---

#### [MODIFY] [Instantiation.md](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/Instantiation.md)

Updates to maintain the Instantiation Document as the immutable Source of Truth for the project architecture:

1. **§3.8 Report Mode Decoupling:** Add a "Dedicated Likes for Days Mode" paragraph describing the pipeline:
   - Specialized pipeline: resolved likes → ≥2 listens pre-filter → MusicBrainz duration enrichment → TopN compilation.
   - Operates on the loaded User History (same data isolation as other analytical reports).
   - Pre-flight dialog prompts the user to optionally sync & resolve likes before generation.
   - Uses `duration_cache.json` for persistent MusicBrainz recording duration lookups.

2. **§6.4 Global Caches:** Add `duration_cache.json` to the cache manifest:
   - `duration_cache.json`: Caches `recording_mbid` → `{duration_ms, title, artist, last_updated}`. Supports negative caching (`duration_ms: 0`) to prevent redundant API calls for recordings with no duration in MusicBrainz.

3. **§4.1 The View (Components) → `gui_charts.py`:** Update the responsibility line to include "Likes for Days Treemaps":
   - Current: "Entity Trends for Artist/Track/Album, New Music, Genre Treemap, Album Art Matrix"
   - Updated: "Entity Trends for Artist/Track/Album, New Music, Genre Treemap, Likes for Days Treemaps, Album Art Matrix"

4. **§4.1 The View (Components) → `gui_actions.py`:** Note the new `LikesSyncPromptDialog` modal.

---

## Verification Plan

### Automated Tests
- Re-run `scratch/test_likes_for_days.py` after applying fixes.
- Add a specific test case with `df.empty` to verify Fix 1 (guard clause) returns gracefully instead of aborting.

### Manual Verification
- Launch the app and select "Likes for Days" with a user who has no ListenBrainz username but does have Last.fm loves. Verify Fix 2 doesn't crash the worker.
- Verify the pre-flight dialog centers correctly on the parent window (Fix 5).
