# Font Scaling — Revised Diagnosis and Implementation Plan

## Root Cause (Not What We Expected)

The font scaling problem is **not** a point-vs-pixel issue or a `tk scaling` quirk. It is a **missing Xft/Freetype linkage** in the Tk library shipped by `uv`.

I ran diagnostics that prove this conclusively:

| Test | Result |
|---|---|
| Available font families | **1** (`fixed` — a bitmap font) |
| `Font(family="DejaVu Sans", size=24)` | Resolves to `fixed`, 13px |
| `Font(family="sans-serif", size=9)` | Resolves to `fixed`, 13px |
| Doubling `tk scaling` | No change (still 13px) |
| Negative pixel sizes (`size=-24`) | No change (still 13px) |

The `uv`-managed Python (cpython-3.13) bundles its own Tk 9.0.3 library (`libtcl9tk9.0.so`), which was compiled **without** Xft or Freetype linkage. It can only render the single X11 bitmap font `fixed`, which has exactly one size. No amount of font configuration in our code can fix this — the rendering engine literally cannot draw scalable fonts.

### Why did the app look "fine" before?
Because the default `fixed` font at 13px is legible at the original `1000x900` window size. When you increase `display_scale`, the window grows but the fonts stay stuck at 13px, making them appear too small.

## Proposed Strategy: Resilient Font Setup with Diagnostic Warning

Since this is an environment-level issue that varies by system (some Linux installs will have a properly-linked Tk, others won't), the best approach is:

### 1. Detect the problem at startup and warn the user
Add a check in `_setup_fonts` that inspects how many font families are available. If only `fixed` is found, log a clear warning explaining the issue and how to fix it (install system `tk` package so it links against Xft/Fontconfig).

### 2. Keep the Named Font architecture (it's correct)
Our centralized named font strategy is architecturally sound and will work perfectly once the Tk library can actually render scalable fonts. We should keep it as-is.

### 3. When scalable fonts ARE available, use `tk scaling` for universal scaling
On a system with proper font support, `tk scaling` is actually the most elegant approach. It scales:
- All point-based font sizes automatically (no negative pixel hacks needed)
- Padding/spacing specified in point units
- Widget internal metrics

The current code already calls `tk scaling` — this is correct and should stay.

## Open Questions

> [!IMPORTANT]
> **The fix for the actual font rendering requires a system-level Tk with Xft support.** This is typically accomplished by installing the OS package for Tk (e.g., `tk` on Arch, `python3-tk` on Debian/Ubuntu), and then ensuring that `uv` uses a Python that links against it rather than its bundled standalone Tk.
> 
> There are two paths forward:
> 1. **Install system Tk** and configure `uv` to use the system Python (or a Python built against system Tk). This is a one-time environment setup.
> 2. **Accept the limitation** for now and add a startup warning so users know exactly why fonts aren't scaling and what to do about it.
> 
> Which approach would you prefer? Or would you like me to implement the warning + keep the font architecture, and then you can fix the Tk linkage on your system separately?

## Proposed Changes

### [MODIFY] [gui_main.py](file:///home/jasper/Projects/BrainzMRI/gui_main.py)

#### `_setup_fonts` method
- Add a probe at the top: create a test font at two different sizes and compare `metrics('linespace')`.
- If the metrics are identical (fonts aren't scaling), log a `WARNING` with an actionable message explaining the Tk/Xft issue.
- Keep all the named font definitions — they will activate correctly once the environment is fixed.

```python
def _setup_fonts(self, scale):
    family = "sans-serif"
    
    s_normal = int(9 * scale)
    s_small = int(8 * scale)
    s_large = int(10 * scale)
    
    # Probe: can Tk actually render scalable fonts?
    probe_small = tkfont.Font(family=family, size=9)
    probe_large = tkfont.Font(family=family, size=24)
    if probe_small.metrics('linespace') == probe_large.metrics('linespace'):
        logging.warning(
            "Font scaling unavailable: Tk cannot find scalable fonts. "
            "All fonts resolve to the bitmap 'fixed' font. "
            "To fix: install a system Tk package with Xft/Freetype support "
            "(e.g., 'tk' on Arch, 'python3-tk' on Debian/Ubuntu)."
        )
    
    # Override default named fonts (effective when scalable fonts are available)
    # ... (existing code unchanged)
```

No other files need modification — the `AppFont*` references in `gui_header.py`, `gui_actions.py`, `sync_engine.py`, and `gui_user_editor.py` are already correct.
