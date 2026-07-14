# Standardize Font Rendering Across All UI Components

## Problem

The app has three distinct font consistency issues visible in the TODO screenshots:

1. **Screenshot 3** — [Resolve Metadata dialog](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/TODO%20-%20platform%20independent%20stable%20font%20rendering%203.png): Dialog buttons ("Skip Previously Failed", "Re-check Failures", "Cancel") are **obscured/clipped** because the dialog has a **fixed geometry** (`480x210`) that doesn't account for the actual rendered font metrics. On Linux (or with different DPI), the `AppFontBold` text in the multi-line buttons overflows the allocated space. The same issue affects `ActionConfirmDialog` (`450x200`).

2. **Screenshot 2** — [Main UI](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/TODO%20-%20platform%20independent%20stable%20font%20rendering%202.png): Many `tk.Button` widgets throughout the app (header, report settings, actions bar, filter bar, user editor) **do not specify a `font=` parameter**, causing them to use Tk's default font. Meanwhile, a subset of widgets explicitly use named fonts like `AppFontBold` or `AppFontSmall`. On Linux, the Tk default may differ from the configured `sans-serif` family, producing **visually inconsistent button text** vs. labels.

3. **Screenshot 1** — [ProgressWindow](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/TODO%20-%20platform%20independent%20stable%20font%20rendering%201.png): The `ProgressWindow` primary label (`lbl_status`) has no `font=` specified, while `lbl_secondary` explicitly uses `font="AppFont"`. The Cancel button also lacks a font specification. This creates mismatched rendering within the same dialog.

**Root causes:**
- `_setup_fonts()` in [gui_main.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py#L160-L186) correctly configures `TkDefaultFont`, `TkTextFont`, `TkFixedFont`, and `TkHeadingFont` — but **does not** configure `TkMenuFont` or `TkCaptionFont`, leaving some Tk-internal fonts untouched.
- Dialog windows use hardcoded pixel geometries that don't adapt to font size changes.
- No `ttk.Style` configuration exists, so `ttk.Combobox`, `ttk.Progressbar`, etc. may use platform-default fonts.
- Matplotlib charts have no `rcParams` font family configuration, so chart text uses matplotlib's default (`DejaVu Sans`) instead of the app's chosen family.

---

## Proposed Changes

### 1. Font Infrastructure — Centralize & Complete

#### [MODIFY] [gui_main.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py)

**`_setup_fonts()` method (lines 160–186):**

- **Platform-aware family selection**: Replace the hardcoded `family = "sans-serif"` with a probe that checks available font families and selects the best match:
  ```python
  def _resolve_font_family(self):
      """Select a concrete font family available on this platform."""
      available = set(tkfont.families())
      # Preference order: clean cross-platform sans-serif fonts
      for candidate in ("Segoe UI", "Helvetica Neue", "Helvetica",
                        "Noto Sans", "DejaVu Sans", "Liberation Sans",
                        "Arial", "sans-serif"):
          if candidate in available:
              return candidate
      return "TkDefaultFont"  # Absolute last resort
  ```
- **Configure ALL standard Tk named fonts**: Add `TkMenuFont` and `TkCaptionFont` to the override list so messagebox dialogs and menus also use the app font.
- **Configure `ttk.Style`**: Set the font for `TLabel`, `TButton`, `TCombobox`, `TCheckbutton`, `Treeview`, and `Treeview.Heading` so all themed widgets are consistent.
- **Configure Matplotlib `rcParams`**: Set `matplotlib.rcParams['font.family']` and `matplotlib.rcParams['font.sans-serif']` to the resolved family, ensuring chart labels/titles match the UI.
- **Store the resolved family** on `self` (e.g. `self._font_family`) so it can be referenced if needed elsewhere.

> [!IMPORTANT]
> The `_resolve_font_family()` probe **must** run after `tk.Tk()` is created (font families aren't available before the Tk interpreter initializes). The current call site at line 202 already satisfies this.

---

### 2. Dialog Geometry — Replace Fixed Sizes with Auto-Sizing

#### [MODIFY] [gui_actions.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_actions.py)

**`ActionConfirmDialog.__init__()` (line 34):**
- Remove `self.geometry("450x200")`.
- Instead, set only a `minsize(450, 180)` as a floor, and let Tk auto-size the window to fit its content. This ensures the dialog grows if font metrics are larger on a given platform.

**`ResolveConfirmDialog.__init__()` (line 103):**
- Remove `self.geometry("480x210")`.
- Set `self.minsize(480, 190)` as a floor.
- This is the dialog shown in **Screenshot 3** where buttons are cut off.

#### [MODIFY] [sync_engine.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/sync_engine.py)

**`ProgressWindow.__init__()` (line 28):**
- Remove `self.geometry("400x175")`.
- Set `self.minsize(400, 160)` as a floor.

> [!NOTE]
> Using `minsize()` + natural auto-sizing is the idiomatic Tkinter approach for platform-independent dialogs. The window will be at least as large as the `minsize` but can grow to fit content. This is safe with the existing deferred-centering pattern (`self.after(10, _center)`), which will calculate geometry after auto-sizing completes.

---

### 3. Explicit `font=` on All Buttons & Labels Missing It

The following widgets currently rely on `TkDefaultFont` implicitly. While `_setup_fonts()` *does* configure `TkDefaultFont`, adding explicit `font="AppFont"` makes the intent clear and guards against any platform where `TkDefaultFont` resolution differs. These widgets should all use `font="AppFont"`:

#### [MODIFY] [gui_header.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_header.py)

| Line | Widget | Current | Change to |
|------|--------|---------|-----------|
| 47 | `tk.Button "New User"` | no font | `font="AppFont"` |
| 48 | `tk.Button "Edit User"` | no font | `font="AppFont"` |
| 51 | `tk.Button "Import Playlist File"` | no font | `font="AppFont"` |
| 56 | `tk.Button "Get New ListenBrainz Data"` | no font | `font="AppFont"` |
| 66 | `tk.Button "Get Last.fm ♥"` | no font | `font="AppFont"` |

#### [MODIFY] [gui_main.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py)

| Line | Widget | Current | Change to |
|------|--------|---------|-----------|
| 340 | `tk.Button "Generate Report"` | no font | `font="AppFont"` |
| 343 | `tk.Button "Show Graph"` | no font | `font="AppFont"` |
| 346 | `tk.Button "Show Art Matrix"` | no font | `font="AppFont"` |
| 349 | `tk.Button "Save Report"` | no font | `font="AppFont"` |

#### [MODIFY] [gui_tableview.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_tableview.py)

| Line | Widget | Current | Change to |
|------|--------|---------|-----------|
| 116 | `tk.Button "Filter"` | no font | `font="AppFont"` |
| 119 | `tk.Button "Clear Filter"` | no font | `font="AppFont"` |

#### [MODIFY] [gui_actions.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_actions.py)

| Line | Widget | Current | Change to |
|------|--------|---------|-----------|
| 64 | `tk.Button "Dry Run (Test)"` | no font | `font="AppFont"` |
| 72 | `tk.Button "Cancel"` (ActionConfirmDialog) | no font | `font="AppFont"` |
| 141 | `tk.Button "Cancel"` (ResolveConfirmDialog) | no font | `font="AppFont"` |
| 180 | `tk.Button "Search Item On MusicBrainz"` | no font | `font="AppFont"` |
| 184 | `tk.Button "Resolve Metadata"` | no font | `font="AppFont"` |
| 188 | `tk.Button "♥ All Everywhere"` | no font | `font="AppFont"` |
| 192 | `tk.Button "♥ Selected on ListenBrainz"` | no font | `font="AppFont"` |
| 196 | `tk.Button "♥ Selected on Last.fm"` | no font | `font="AppFont"` |
| 201 | `tk.Button "Export Tracklist to ListenBrainz"` | no font | `font="AppFont"` |
| 205 | `tk.Button "Export Tracklist to JSPF File"` | no font | `font="AppFont"` |
| 209 | `tk.Button "Export Tracklist to XSPF File"` | no font | `font="AppFont"` |

#### [MODIFY] [sync_engine.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/sync_engine.py)

| Line | Widget | Current | Change to |
|------|--------|---------|-----------|
| 46 | `tk.Label "Initializing..."` (lbl_status) | no font | `font="AppFont"` |
| 55 | `tk.Button "Cancel"` | no font | `font="AppFont"` |

#### [MODIFY] [gui_user_editor.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_user_editor.py)

| Line | Widget | Current | Change to |
|------|--------|---------|-----------|
| 86 | `tk.Button "Complete Connection"` | no font | `font="AppFont"` |
| 93 | `tk.Button "Disconnect"` | no font | `font="AppFont"` |
| 134 | `tk.Button "Choose ListenBrainz Zip"` | no font | `font="AppFont"` |
| 146 | `tk.Button "Save User"` | no font | `font="AppFont"` |
| 155 | `tk.Button "Cancel"` | no font | `font="AppFont"` |

---

### Summary of Files Changed

| File | Changes |
|------|---------|
| [gui_main.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py) | Font family probe, complete named-font coverage, ttk style, matplotlib rcParams, 4 buttons |
| [gui_actions.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_actions.py) | Remove fixed dialog geometry (2 dialogs), add `font="AppFont"` to ~13 buttons |
| [sync_engine.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/sync_engine.py) | Remove fixed ProgressWindow geometry, add `font="AppFont"` to label + button |
| [gui_header.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_header.py) | Add `font="AppFont"` to 5 buttons |
| [gui_tableview.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_tableview.py) | Add `font="AppFont"` to 2 buttons |
| [gui_user_editor.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_user_editor.py) | Add `font="AppFont"` to 5 buttons |

---

## Open Questions

> [!IMPORTANT]
> **Font family preference**: The plan proposes a preference cascade of `Segoe UI → Helvetica Neue → Helvetica → Noto Sans → DejaVu Sans → Liberation Sans → Arial → sans-serif`. Should any family be added, removed, or re-prioritized? For example, if you want the Windows look to match the Linux look exactly, `Noto Sans` could be first (it's available on both if installed).

> [!NOTE]
> **Matplotlib font family**: The plan configures matplotlib to use the same resolved font family as the Tk UI. This means chart titles/labels will match the app's buttons and labels. If you prefer matplotlib to keep its default `DejaVu Sans` for charts (which has excellent glyph coverage), let me know.

---

## Verification Plan

### Manual Verification
- Launch the app on **Windows** and confirm:
  - All buttons render with consistent font family and size
  - Dialog windows (ActionConfirmDialog, ResolveConfirmDialog, ProgressWindow) auto-size to fit their content with no clipped buttons
  - Matplotlib chart titles use the same font family as the UI
  - `messagebox` dialogs (info, error, warning) use the app font
- Launch the app on **Linux** (if available) and confirm the same items above, particularly that:
  - The font probe selects an appropriate available family
  - Dialog buttons are fully visible and not clipped
