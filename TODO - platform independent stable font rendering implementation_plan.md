# Bugfix Plan: Resolving Large Font Size & Treeview Row Overlap

## Root Cause Analysis

An investigation into `DEBUG 1.png` and `DEBUG 2.png` revealed two specific root causes:

1. **Tcl Font Registry Fallback to `Arial 15` (Huge Text)**:
   - Creating named fonts using Python's object wrapper (`tkfont.Font(name="AppFont", ...)`) does not register the font name in Tcl's global C-level font table.
   - When widgets (or `option_add("*Font", "AppFont")`) passed the string `"AppFont"` to Tcl, Tcl attempted to parse `"AppFont"` as a system font family name.
   - Because `"AppFont"` was not recognized as an installed OS font family, Tcl fell back to its internal fallback font: **15pt Arial**!
   - This caused buttons, checkbuttons, and labels across Windows to render in massive 15pt Arial instead of 9pt Segoe UI.

2. **Unadjusted Treeview Row Height (Overlapping Table Rows)**:
   - Increasing font size or applying TTK styles to `Treeview` changes text rendering height, but TTK's `Treeview` widget does not automatically adjust its `rowheight` style attribute.
   - As a result, 15pt text was rendered inside default ~18px row containers, causing vertical text collisions across rows.

---

## Technical Bugfix Steps

### 1. Register Named Fonts in Native Tcl Registry & Remove `option_add`

#### [MODIFY] [gui_main.py](file:///c:/Users/jaspe/AppData/Local/Programs/BrainzMRI/gui_main.py)

Update `_setup_fonts(scale)` in `gui_main.py`:

```python
def _setup_fonts(self, scale):
    family = self._resolve_font_family()

    s_normal = int(9 * scale)
    s_small = int(8 * scale)
    s_large = int(10 * scale)

    # 1. Override standard Tk named fonts so standard widgets automatically scale
    for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkCaptionFont"):
        try:
            tkfont.nametofont(font_name).configure(family=family, size=s_normal)
        except Exception:
            pass

    try:
        tkfont.nametofont("TkFixedFont").configure(size=s_normal)
    except Exception:
        pass

    try:
        tkfont.nametofont("TkHeadingFont").configure(family=family, size=s_normal, weight="bold")
    except Exception:
        pass

    # 2. Register custom named fonts directly in Tcl's native font registry
    #    (Prevents Tcl string lookup failure and fallback to Arial 15)
    for name, f_fam, f_sz, f_wt, f_sl in [
        ("AppFont", family, s_normal, "normal", "roman"),
        ("AppFontItalic", family, s_normal, "normal", "italic"),
        ("AppFontBold", family, s_normal, "bold", "roman"),
        ("AppFontSmall", family, s_small, "normal", "roman"),
        ("AppFontLarge", family, s_large, "normal", "roman"),
        ("AppFontLargeBold", family, s_large, "bold", "roman"),
    ]:
        try:
            if name in self.root.tk.call("font", "names"):
                self.root.tk.call("font", "configure", name, "-family", f_fam, "-size", f_sz, "-weight", f_wt, "-slant", f_sl)
            else:
                self.root.tk.call("font", "create", name, "-family", f_fam, "-size", f_sz, "-weight", f_wt, "-slant", f_sl)
        except Exception:
            pass

    # 3. Configure TTK Theme Style with explicit Treeview row height
    style = ttk.Style()
    style.configure(".", font=(family, s_normal))
    style.configure("Treeview", font=(family, s_normal), rowheight=int(22 * scale))
    style.configure("Treeview.Heading", font=(family, s_normal, "bold"))
```

---

## Expected Outcome

1. Standard buttons, labels, and dialog inputs render in exact **9pt Segoe UI** (or probed system font) without scaling up to 15pt Arial.
2. `ttk.Treeview` rows have explicit `rowheight=22`, eliminating vertical row text collisions.
3. Dialog geometry floors (`minsize`) operate on crisp 9pt font dimensions, keeping all buttons fully visible and proportioned.

---

## Verification Plan

1. Run `python gui_main.py` on Windows and verify fonts match standard Windows 9pt Segoe UI.
2. Confirm Treeview table rows display cleanly with no row overlap.
3. Confirm buttons and label frames fit within standard UI layouts without text truncation.
