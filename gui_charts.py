"""
gui_charts.py
Matplotlib visualization logic for BrainzMRI.
Refactored to use Object-Oriented API embedded in Tkinter windows to prevent mainloop crashes.
"""

import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg, NavigationToolbar2Tk
)
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
import matplotlib.image as mpimg
import matplotlib.patheffects as pe
import pandas as pd
import numpy as np
import math
import os
import textwrap
import squarify  # Requires: pip install squarify
from config import config

# Helper for Rectangle since we don't import pyplot
from matplotlib.patches import Rectangle as plt_Rectangle


def create_chart_window(fig, title, parent=None):
    """
    Helper to embed a Matplotlib Figure into a new Tkinter Toplevel window.
    """
    if parent:
        window = tk.Toplevel(parent)
    else:
        # Fallback if no parent provided (dev testing)
        window = tk.Toplevel()
    
    window.title(title)
    window.geometry("1000x800")
    
    # 1. Create Canvas
    canvas = FigureCanvasTkAgg(fig, master=window)
    canvas.draw()
    
    # 2. Add Toolbar
    toolbar = NavigationToolbar2Tk(canvas, window)
    toolbar.update()
    
    # 3. Pack
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)
    
    # Bring to front
    window.lift()
    return window


# ================================================================
# Shared Helpers for Album Art Matrix
# ================================================================

def _load_fallback_logo():
    """Load and return the BrainzMRI logo image, cropped to square.
    Returns None if the logo cannot be loaded."""
    logo_path = os.path.join(config.app_root, "BrainzMRI_Transparent.png")
    try:
        raw = mpimg.imread(logo_path)
        h, w = raw.shape[:2]
        if h != w:
            min_dim = min(h, w)
            sy = (h - min_dim) // 2
            sx = (w - min_dim) // 2
            raw = raw[sy:sy+min_dim, sx:sx+min_dim]
        return raw
    except Exception:
        return None


def _render_album_cell(ax, cover_art_map, mbid, fallback_logo,
                       artist_text=None, album_text=None, stats_text=None):
    """Render a single album art cell on the given Axes.

    Image is loaded from cover_art_map[mbid], falling back to the logo
    or a black rectangle.

    If artist_text/album_text/stats_text are None, no text overlay is drawn
    (used for entity sub-grid cells which are art-only).
    """
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # --- Image ---
    img_path = cover_art_map.get(mbid) if mbid else None
    img_display = None

    if img_path:
        try:
            img = mpimg.imread(img_path)
            h, w = img.shape[:2]
            if h != w:
                min_dim = min(h, w)
                start_y = (h - min_dim) // 2
                start_x = (w - min_dim) // 2
                img = img[start_y:start_y+min_dim, start_x:start_x+min_dim]
            img_display = img
        except Exception:
            img_display = None

    if img_display is not None:
        ax.imshow(img_display, aspect="equal", extent=[0, 1, 0, 1])
    elif fallback_logo is not None:
        ax.imshow(fallback_logo, aspect="equal", extent=[0, 1, 0, 1])
    else:
        rect = plt_Rectangle((0, 0), 1, 1, color="#111111")
        ax.add_patch(rect)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

    # --- Text Overlay (only when explicitly provided) ---
    if artist_text is None and album_text is None and stats_text is None:
        return  # Art-only cell

    text_style = dict(
        ha='center',
        color='white',
        weight='bold',
        transform=ax.transAxes,
        path_effects=[pe.withStroke(linewidth=2.5, foreground='black')]
    )

    if artist_text:
        ax.text(0.5, 0.96, artist_text, va='top', fontsize=9, **text_style)
    if stats_text:
        ax.text(0.5, 0.03, stats_text, va='bottom', fontsize=8, **text_style)
    if album_text:
        ax.text(0.5, 0.15, album_text, va='bottom', fontsize=9, **text_style)


def _format_text(text, max_chars=25, max_lines=2):
    """Wrap text for cell annotations, truncating with '...' if needed."""
    if not text:
        return ""
    text = str(text)
    text = " ".join(text.split())
    lines = textwrap.wrap(text, width=max_chars)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if len(lines[-1]) > (max_chars - 3):
            lines[-1] = lines[-1][:(max_chars-3)] + "..."
        else:
            lines[-1] += "..."
    return "\n".join(lines)


def _build_filter_subtitle(filter_params):
    """Build a subtitle string from filter parameters."""
    subtitle_parts = []
    if filter_params:
        t_start = filter_params.get("time_start_days", 0)
        t_end = filter_params.get("time_end_days", 0)
        if t_start > 0 or t_end > 0:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            d_from = (now - timedelta(days=t_end)).strftime("%Y-%m-%d")
            d_to = (now - timedelta(days=t_start)).strftime("%Y-%m-%d")
            subtitle_parts.append(f"{d_from} to {d_to}")

        min_l = filter_params.get("min_listens", 0)
        min_likes = filter_params.get("min_likes", 0)
        if min_l > 0:
            subtitle_parts.append(f"{min_l}+ Listens")
        if min_likes > 0:
            subtitle_parts.append(f"{min_likes}+ Likes")
    return " | ".join(subtitle_parts)


# ================================================================
# Entity Trend Charts
# ================================================================

def show_entity_trend_chart(df: pd.DataFrame, entity_label: str = "Artist", parent=None):
    """
    Generate a Stacked Area Chart for Entity Trends (2 Rows).
    Top Row: Absolute Counts.
    Bottom Row: Normalized (Percentage) Dominance.
    Entities 11-20 get cross-hatch patterns to differentiate from
    the first 10 which share the same tab10 palette colors.
    """
    import matplotlib.colors as mcolors
    chart_df = df.copy()
    if not isinstance(chart_df.index, pd.DatetimeIndex):
        try:
            chart_df.index = pd.to_datetime(chart_df.index)
        except Exception:
            pass 
    
    chart_df = chart_df.sort_index()

    # Calculate Normalized Data (Row-wise percentage)
    # Divide each row by its sum to get fractions (0.0 - 1.0)
    norm_df = chart_df.div(chart_df.sum(axis=1), axis=0).fillna(0)

    # Setup Figure (OO API)
    # 2x1 Grid
    fig = Figure(figsize=(10, 10), dpi=100)
    ax_abs = fig.add_subplot(211)
    ax_norm = fig.add_subplot(212, sharex=ax_abs)
    
    x = chart_df.index
    entities = chart_df.columns.tolist()

    # Color + hatch: entities 11-20 reuse tab10 colors but get hatching
    tab10 = list(mcolors.TABLEAU_COLORS.values())
    hatch_patterns = ['//', '\\\\', 'xx', '++', '..', 'oo', '**', 'OO', '--', '||']

    def _get_style(i):
        color = tab10[i % 10]
        hatch = '...'  if i >= 10 else None
        return color, hatch

    # 1. Plot Absolute (Top) — manual fill_between for hatch support
    cumulative = np.zeros(len(x))
    for i, entity in enumerate(entities):
        y = chart_df[entity].values
        color, hatch = _get_style(i)
        ax_abs.fill_between(
            x, cumulative, cumulative + y,
            label=entity, color=color, alpha=0.8,
            hatch=hatch, edgecolor='white' if hatch else None,
            linewidth=0.3,
        )
        cumulative = cumulative + y
    
    ax_abs.set_title(f"Top {entity_label} Dominance Over Time (Absolute)")
    ax_abs.set_ylabel("Listens")
    ax_abs.legend(loc='upper left', bbox_to_anchor=(1, 1), title=f"{entity_label}s", fontsize=8)
    
    # 2. Plot Normalized (Bottom) — same fill_between approach
    cumulative = np.zeros(len(x))
    for i, entity in enumerate(entities):
        y = norm_df[entity].values
        color, hatch = _get_style(i)
        ax_norm.fill_between(
            x, cumulative, cumulative + y,
            label=entity, color=color, alpha=0.8,
            hatch=hatch, edgecolor='white' if hatch else None,
            linewidth=0.3,
        )
        cumulative = cumulative + y
    
    ax_norm.set_title("Relative Dominance (Normalized)")
    ax_norm.set_ylabel("Fraction")
    ax_norm.set_xlabel("Time Period")
    ax_norm.set_ylim(0, 1.0)
    
    # Add a faint 50% line for reference
    ax_norm.axhline(y=0.5, color='gray', linestyle='--', alpha=0.3, linewidth=1)

    fig.tight_layout()
    create_chart_window(fig, f"Favorite {entity_label} Trend", parent)

# Backward-compatible alias
show_artist_trend_chart = show_entity_trend_chart

def show_new_music_stacked_bar(df: pd.DataFrame, parent=None):
    """
    Generate a 2-Row Stacked Bar Chart for New Music By Year.
    Top Row: Absolute Counts.
    Bottom Row: Normalized Fractions (0.0 - 1.0).
    """
    # Work on a copy to avoid modifying the source view
    plot_df = df.copy()

    # Calculate missing "Recurring" columns if they don't exist
    if "Recurring Artists" not in plot_df.columns and "Unique Artists" in plot_df.columns:
        plot_df["Recurring Artists"] = plot_df["Unique Artists"] - plot_df["New Artists"]
    
    if "Recurring Albums" not in plot_df.columns and "Unique Albums" in plot_df.columns:
        plot_df["Recurring Albums"] = plot_df["Unique Albums"] - plot_df["New Albums"]

    if "Recurring Tracks" not in plot_df.columns and "Unique Tracks" in plot_df.columns:
        plot_df["Recurring Tracks"] = plot_df["Unique Tracks"] - plot_df["New Tracks"]

    # Setup Figure (OO API)
    # 2x3 Grid
    fig = Figure(figsize=(14, 10), dpi=100)
    
    metrics = [
        ("New Artists", "Recurring Artists", "Artists"),
        ("New Albums", "Recurring Albums", "Albums"),
        ("New Tracks", "Recurring Tracks", "Tracks"),
    ]
    
    years = plot_df["Year"]
    
    # Colors
    c_new = "#4CAF50" # Green
    c_rec = "#2196F3" # Blue

    # Iterate through columns (Artists, Albums, Tracks)
    # We add subplots dynamically: 231, 232, 233, etc.
    # Logic: Row 1 is 231, 232, 233. Row 2 is 234, 235, 236.
    
    # Pre-create axes to share X
    axes_top = []
    axes_bottom = []

    for col_idx, (new_col, rec_col, title) in enumerate(metrics):
        
        # Top Row (Absolute)
        # subplot index is 1-based: col_idx + 1
        ax_abs = fig.add_subplot(2, 3, col_idx + 1)
        axes_top.append(ax_abs)
        
        # Bottom Row (Fraction)
        # subplot index: col_idx + 1 + 3 (since 3 cols)
        ax_frac = fig.add_subplot(2, 3, col_idx + 4, sharex=ax_abs)
        axes_bottom.append(ax_frac)

        if new_col not in plot_df.columns or rec_col not in plot_df.columns:
            ax_abs.text(0.5, 0.5, "Data Missing", ha='center')
            ax_frac.text(0.5, 0.5, "Data Missing", ha='center')
            continue
            
        # --- TOP ROW: ABSOLUTE COUNTS ---
        ax_abs.bar(years, plot_df[new_col], label="New", alpha=0.8, color=c_new)
        ax_abs.bar(years, plot_df[rec_col], bottom=plot_df[new_col], label="Recurring", alpha=0.8, color=c_rec)
        
        ax_abs.set_title(title)
        if col_idx == 0:
            ax_abs.set_ylabel("Count")

        # --- BOTTOM ROW: FRACTIONS ---
        # Calculate totals for normalization
        total = plot_df[new_col] + plot_df[rec_col]
        # Avoid division by zero
        total = total.replace(0, 1)
        
        frac_new = plot_df[new_col] / total
        frac_rec = plot_df[rec_col] / total

        ax_frac.bar(years, frac_new, label="New", alpha=0.8, color=c_new)
        ax_frac.bar(years, frac_rec, bottom=frac_new, label="Recurring", alpha=0.8, color=c_rec)
        
        ax_frac.set_xlabel("Year")
        ax_frac.set_ylim(0, 1.0) # Lock Y-axis to 0-100%
        
        # Add a faint 50% line for reference
        ax_frac.axhline(y=0.5, color='gray', linestyle='--', alpha=0.3, linewidth=1)

        if col_idx == 0:
            ax_frac.set_ylabel("Fraction")

    # Custom Multi-Colored Title Construction
    fig.text(0.5, 0.96, "Music Discovery by Year", ha='center', fontsize=16, weight='bold')
    
    # Color-coded Legend/Subtitle
    fig.text(0.42, 0.93, "New Artists", color=c_new, weight='bold', ha='right', fontsize=12)
    fig.text(0.50, 0.93, "vs.", color='black', ha='center', fontsize=12)
    fig.text(0.58, 0.93, "Recurring Artists", color=c_rec, weight='bold', ha='left', fontsize=12)

    # Adjust layout to make room for the custom header
    fig.tight_layout(rect=[0, 0.03, 1, 0.91])
    
    create_chart_window(fig, "New Music By Year", parent)

def show_genre_flavor_treemap(df: pd.DataFrame, parent=None):
    """
    Generate a Treemap for Genre Flavor using squarify.
    Expects a DataFrame with columns: Genre, Listens, Likes.
    """
    # 1. Identify Columns
    if "Genre" not in df.columns or "Listens" not in df.columns:
        raise ValueError("Data must have 'Genre' and 'Listens' columns.")
        
    label_col = "Genre"
    value_col = "Listens"
    like_col = "Likes" if "Likes" in df.columns else None
    
    # 2. Filter Top 30
    plot_df = df.sort_values(by=value_col, ascending=False).head(30)
    
    # 3. Plot (OO API)
    fig = Figure(figsize=(12, 8), dpi=100)
    ax = fig.add_subplot(111)

    # Generate label text
    labels = []
    for _, row in plot_df.iterrows():
        txt = f"{row[label_col]}\n{row[value_col]} listens"
        if like_col:
            txt += f"\n❤️{int(row[like_col])}"
        labels.append(txt)
    
    # Create color palette (viridis reversed looks nice for frequency)
    # We need to import cm from matplotlib? No, we didn't import matplotlib.pyplot as plt
    # But we can import cm directly or through figure?
    # Actually, we imported matplotlib.pyplot as plt in the original code. 
    # Here we are trying to avoid it. Use matplotlib.cm
    import matplotlib.cm as cm
    colors = cm.viridis(np.linspace(0.8, 0.2, len(plot_df)))
    
    squarify.plot(
        sizes=plot_df[value_col], 
        label=labels, 
        color=colors, 
        alpha=0.8, 
        text_kwargs={'fontsize': 9, 'color': 'white', 'weight': 'bold'},
        ax=ax
    )
    
    ax.axis('off')
    ax.set_title(f"Top {len(plot_df)} Genres (Treemap)", fontsize=14)
    
    fig.tight_layout()
    create_chart_window(fig, "Genre Flavor Profile", parent)


# ================================================================
# Album Art Matrix (Album Mode — "Top Albums")
# ================================================================

def show_album_art_matrix(df: pd.DataFrame, cover_art_map: dict[str, str | None], filter_params: dict = None, parent=None):
    """
    Render an N×M grid of album cover art thumbnails.
    
    Args:
        df: Album report DataFrame with artist, album, release_mbid, total_listens columns.
        cover_art_map: Dict mapping release_mbid -> local image filepath (or None).
        filter_params: Optional dict with report filter context for the title.
        parent: Tkinter parent widget.
    """
    if df.empty:
        return

    fallback_logo = _load_fallback_logo()

    # Limit to 150 albums max
    plot_df = df.head(150).copy()
    n = len(plot_df)

    # Calculate grid dimensions...
    best = None
    start_c = max(1, math.isqrt(n))
    for c in range(start_c, n + 2):
        r = math.ceil(n / c)
        if r == 0: continue
        ratio = c / r
        if ratio < 0.8 or ratio > 2.2:
            continue
        empty_spots = (r * c) - n
        score = (empty_spots * 10.0) + abs(ratio - 1.6)
        if best is None or score < best[2]:
            best = (c, r, score)

    if best:
        ncols, nrows = best[0], best[1]
    else:
        ncols = math.ceil(math.sqrt(n * 1.5))
        nrows = math.ceil(n / ncols)

    # Create figure (OO API)
    fig = Figure(figsize=(ncols * 2, nrows * 2), dpi=100)

    # Build title with filter context
    title_main = f"Top {n} Albums"
    subtitle = _build_filter_subtitle(filter_params)
    full_title = title_main
    if subtitle:
        full_title += " - " + subtitle

    fig.suptitle(full_title, fontsize=14, weight="bold", y=0.98)

    # Iterate 0..n-1
    for idx in range(n):
        ax = fig.add_subplot(nrows, ncols, idx + 1)

        row = plot_df.iloc[idx]
        mbid = row.get("release_mbid", None)
        raw_album = str(row.get("album", "Unknown Album"))
        raw_artist = str(row.get("artist", "Unknown Artist"))

        listens = int(row.get("total_listens", 0))
        likes = int(row.get("Likes", 0))
        stats_str = f"{listens} Listens"
        if likes > 0:
            stats_str += f" | {likes} ❤️"

        _render_album_cell(
            ax, cover_art_map, mbid, fallback_logo,
            artist_text=_format_text(raw_artist, max_chars=20, max_lines=3),
            album_text=_format_text(raw_album, max_chars=20, max_lines=3),
            stats_text=stats_str,
        )

    # Tight layout: minimize gaps
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.92, wspace=0.02, hspace=0.02)
    
    create_chart_window(fig, "Album Art Matrix", parent)


# ================================================================
# Entity Art Matrix (Artist/Track Mode)
# ================================================================

def show_entity_art_matrix(
    artist_data: list[dict],
    cover_art_map: dict[str, str | None],
    filter_params: dict = None,
    parent=None,
):
    """
    Render a composite matrix with per-artist square sub-grids.

    Args:
        artist_data: List of dicts, each with keys:
            - artist (str): Artist name
            - total_listens (int): Artist-level listen count
            - likes (int): Artist-level like count
            - albums (list[dict]): Each with 'album', 'release_mbid'
              Sorted by listens descending. Max 9 entries.
        cover_art_map: Dict mapping release_mbid -> local image filepath (or None).
        filter_params: Optional dict with report filter context for the title.
        parent: Tkinter parent widget.
    """
    if not artist_data:
        return

    fallback_logo = _load_fallback_logo()

    n_artists = len(artist_data)

    # Determine outer grid: arrange artists in a flowing grid
    # Target ~5 columns for a nice wide layout, but adapt to small counts
    outer_cols = min(5, n_artists)
    outer_rows = math.ceil(n_artists / outer_cols)

    # Each artist block needs:
    #   1 row for the header text label
    #   side×side rows for the album sub-grid (side = ceil(sqrt(n_albums)), max 3)
    # We use a fixed cell size; the figure scales to fit.
    # sub_side for each artist is computed individually.

    # Pre-compute sub-grid sizes
    artist_sides = []
    for entry in artist_data:
        n_albums = len(entry.get("albums", []))
        if n_albums == 0:
            artist_sides.append(1)  # Single empty cell
        else:
            side = min(3, math.ceil(math.sqrt(n_albums)))
            artist_sides.append(side)

    max_side = max(artist_sides) if artist_sides else 1

    # GridSpec layout:
    # Each artist block occupies (max_side + 1) rows (1 for header + max_side for art)
    # and max_side columns.
    # We use height_ratios to give the header row less space.
    block_rows = max_side + 1  # 1 header + max_side art rows
    total_gs_rows = outer_rows * block_rows
    total_gs_cols = outer_cols * max_side

    # Figure size: scale by number of cells
    fig_w = max(6, total_gs_cols * 1.8)
    fig_h = max(4, total_gs_rows * 1.6)
    fig = Figure(figsize=(fig_w, fig_h), dpi=100)

    # Build title
    title_main = f"Art Matrix — {n_artists} Artists"
    subtitle = _build_filter_subtitle(filter_params)
    full_title = title_main
    if subtitle:
        full_title += " — " + subtitle
    fig.suptitle(full_title, fontsize=14, weight="bold", y=0.99)

    # Build height_ratios: for each block_row set, header row is shorter
    height_ratios = []
    for _ in range(outer_rows):
        height_ratios.append(0.4)  # Header row (shorter)
        for _ in range(max_side):
            height_ratios.append(1.0)  # Art rows

    outer_gs = GridSpec(
        total_gs_rows, total_gs_cols, figure=fig,
        height_ratios=height_ratios,
        hspace=0.15, wspace=0.05,
        left=0.01, right=0.99, bottom=0.01, top=0.93,
    )

    for artist_idx, entry in enumerate(artist_data):
        # Determine position in outer grid
        outer_r = artist_idx // outer_cols
        outer_c = artist_idx % outer_cols

        # Row/col offsets in the GridSpec
        gs_row_start = outer_r * block_rows
        gs_col_start = outer_c * max_side

        artist_name = entry.get("artist", "Unknown Artist")
        total_listens = entry.get("total_listens", 0)
        likes = entry.get("likes", 0)
        albums = entry.get("albums", [])
        side = artist_sides[artist_idx]

        # --- Header Row ---
        # Span the full width of this artist's block
        ax_header = fig.add_subplot(
            outer_gs[gs_row_start, gs_col_start:gs_col_start + max_side]
        )
        ax_header.set_xticks([])
        ax_header.set_yticks([])
        for spine in ax_header.spines.values():
            spine.set_visible(False)
        ax_header.set_facecolor("#1a1a2e")

        # Header text: artist name + stats
        header_text = _format_text(artist_name, max_chars=30, max_lines=1)
        stats_str = f"{total_listens} Listens"
        if likes > 0:
            stats_str += f" | {likes} ❤️"

        ax_header.text(
            0.5, 0.65, header_text, ha='center', va='center',
            fontsize=9, weight='bold', color='white',
            transform=ax_header.transAxes,
            path_effects=[pe.withStroke(linewidth=2, foreground='black')]
        )
        ax_header.text(
            0.5, 0.15, stats_str, ha='center', va='center',
            fontsize=7, color='#cccccc',
            transform=ax_header.transAxes,
            path_effects=[pe.withStroke(linewidth=1.5, foreground='black')]
        )

        # --- Album Sub-Grid ---
        album_idx = 0
        for sr in range(max_side):
            for sc in range(max_side):
                gs_r = gs_row_start + 1 + sr  # +1 to skip header
                gs_c = gs_col_start + sc

                ax = fig.add_subplot(outer_gs[gs_r, gs_c])

                if sr < side and sc < side and album_idx < len(albums):
                    # Render album art (art-only, no text)
                    album_entry = albums[album_idx]
                    mbid = album_entry.get("release_mbid", None)
                    _render_album_cell(ax, cover_art_map, mbid, fallback_logo)
                    album_idx += 1
                else:
                    # Empty cell — hide completely
                    ax.set_xticks([])
                    ax.set_yticks([])
                    for spine in ax.spines.values():
                        spine.set_visible(False)
                    ax.set_facecolor("#0a0a15")

    create_chart_window(fig, "Entity Art Matrix", parent)