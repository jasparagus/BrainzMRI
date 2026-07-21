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
from matplotlib.patches import Rectangle
import matplotlib.patheffects as pe
import pandas as pd
import numpy as np
import math
import os
import textwrap
import squarify  # Requires: pip install squarify
from PIL import Image  # For tile resizing in art matrix compositing
from config import config


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
# Shared Helpers for Art Matrix (Pre-Compositing)
# ================================================================

# Tile size in pixels for pre-compositing album art. All images are resized
# to TILE_PX × TILE_PX before being stitched into a single composite array.
# Higher values yield sharper images but increase memory and render time.
# 250px is a good balance for up to ~50 blocks. Reduce to 150px if
# performance becomes an issue (search for TILE_PX to find all usages).
TILE_PX = 250


def _load_tile(path, tile_px=TILE_PX):
    """Load an image from *path*, center-crop to square, resize to tile_px.
    Returns a uint8 RGB numpy array, or None on failure."""
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        if w != h:
            d = min(w, h)
            left, top = (w - d) // 2, (h - d) // 2
            img = img.crop((left, top, left + d, top + d))
        img = img.resize((tile_px, tile_px), Image.LANCZOS)
        return np.array(img, dtype=np.uint8)
    except Exception:
        return None


def _make_dark_tile(tile_px=TILE_PX):
    """Solid dark tile for empty grid cells (uint8 RGB)."""
    return np.full((tile_px, tile_px, 3), 17, dtype=np.uint8)  # #111111


def _load_logo_tile(tile_px=TILE_PX):
    """Load the BrainzMRI logo as a tile_px × tile_px uint8 RGB array.
    Used for albums with missing cover art (distinct from empty cells)."""
    logo_path = os.path.join(config.app_root, "BrainzMRI_Transparent.png")
    tile = _load_tile(logo_path, tile_px)
    if tile is not None:
        return tile
    return _make_dark_tile(tile_px)


def _composite_grid(albums, side, cover_art_map, logo_tile, dark_tile):
    """Stitch album images into a single (side*TILE_PX) × (side*TILE_PX) composite.

    - Albums with cover art  → loaded and resized
    - Albums with missing art → logo_tile (fallback logo)
    - Empty grid cells       → dark_tile (solid dark fill)
    """
    tile_px = logo_tile.shape[0]
    rows = []
    idx = 0
    for _r in range(side):
        row_tiles = []
        for _c in range(side):
            if idx < len(albums):
                mbid = albums[idx].get("release_mbid")
                img_path = cover_art_map.get(mbid) if mbid else None
                tile = _load_tile(img_path, tile_px) if img_path else None
                row_tiles.append(tile if tile is not None else logo_tile.copy())
                idx += 1
            else:
                row_tiles.append(dark_tile.copy())
        rows.append(np.concatenate(row_tiles, axis=1))
    return np.concatenate(rows, axis=0)


def _render_art_block(fig, subplot_spec, composite,
                      title, subtitle, detail=None,
                      header_bg="#1a1a2e"):
    """Render a single art block: dark header row + composite image.

    Uses a single axes so that the header and image share the same data
    coordinate x-range.  The image is rendered with aspect='equal' (always
    square), and the header is a Rectangle patch spanning the same x-range,
    guaranteeing the header width always matches the art width.

    Args:
        fig:           matplotlib Figure
        subplot_spec:  outer GridSpec cell to place this block in
        composite:     numpy uint8 RGB array of the composited album art
        title:         Primary header text (e.g., artist name)
        subtitle:      Secondary text (e.g., album name or stats)
        detail:        Optional tertiary text (e.g., stats when subtitle is album name)
        header_bg:     Header background colour
    """
    has_detail = detail is not None
    # Header height as a fraction of image height (in data units)
    hdr_h = 0.40 if has_detail else 0.28

    ax = fig.add_subplot(subplot_spec)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)

    # Image occupies data coords [0, 1] × [0, 1]  (y=0 bottom, y=1 top).
    # Header occupies [0, 1] × [1, 1+hdr_h] — same x-range, above image.
    ax.imshow(composite[::-1], extent=[0, 1, 0, 1], origin='lower',
              aspect='equal', zorder=1)

    # Header background — shares the image's x-range so width always matches
    ax.add_patch(Rectangle((0, 1), 1, hdr_h,
                            facecolor=header_bg, edgecolor='none',
                            zorder=2, clip_on=False))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1 + hdr_h)

    # --- Text (data coordinates, centred on x=0.5) ---
    stroke_thin = [pe.withStroke(linewidth=2, foreground='black')]
    stroke_bold = [pe.withStroke(linewidth=3, foreground='black')]

    if has_detail:
        ax.text(0.5, 1 + hdr_h * 0.85, _format_text(title, 25, 2),
                ha='center', va='top', fontsize=12, weight='bold',
                color='white', path_effects=stroke_bold, zorder=3,
                clip_on=False)
        ax.text(0.5, 1 + hdr_h * 0.42, _format_text(subtitle, 25, 2),
                ha='center', va='center', fontsize=12, color='#dddddd',
                path_effects=stroke_thin, zorder=3, clip_on=False)
        ax.text(0.5, 1 + hdr_h * 0.12, detail,
                ha='center', va='center', fontsize=11, color='#cccccc',
                path_effects=stroke_thin, zorder=3, clip_on=False)
    else:
        ax.text(0.5, 1 + hdr_h * 0.78, _format_text(title, 30, 2),
                ha='center', va='top', fontsize=12, weight='bold',
                color='white', path_effects=stroke_bold, zorder=3,
                clip_on=False)
        ax.text(0.5, 1 + hdr_h * 0.15, subtitle,
                ha='center', va='center', fontsize=11, color='#cccccc',
                path_effects=stroke_thin, zorder=3, clip_on=False)


def _format_text(text, max_chars=25, max_lines=2):
    """Wrap text for header annotations, truncating with '...' if needed."""
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
    c_new = "#2196F3" # Blue
    c_rec = "#AF4C50" # Red

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

    Each album is rendered as a block with a dark header row (artist, album,
    stats) above a single pre-composited 1×1 image.  This uses the same
    _render_art_block helper as the entity matrix for visual consistency.

    Args:
        df: Album report DataFrame with artist, album, release_mbid, total_listens columns.
        cover_art_map: Dict mapping release_mbid -> local image filepath (or None).
        filter_params: Optional dict with report filter context for the title.
        parent: Tkinter parent widget.
    """
    if df.empty:
        return

    logo_tile = _load_logo_tile()
    dark_tile = _make_dark_tile()

    # Limit to 100 albums max (was 150)
    plot_df = df.head(100).copy()
    n = len(plot_df)

    # Calculate grid dimensions (favour wider-than-tall layouts)
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

    # Figure size: each block is ~2.5 wide, ~3.0 tall (header + art)
    fig = Figure(figsize=(ncols * 2.5, nrows * 3.0), dpi=100)

    title_main = f"Top {n} Albums"
    subtitle = _build_filter_subtitle(filter_params)
    full_title = title_main
    if subtitle:
        full_title += " - " + subtitle
    fig.suptitle(full_title, fontsize=16, weight="bold", y=0.98)

    outer_gs = GridSpec(
        nrows, ncols, figure=fig,
        hspace=0.3, wspace=0.15,
        left=0.02, right=0.98, bottom=0.02, top=0.93,
    )

    for idx in range(n):
        row = plot_df.iloc[idx]
        mbid = row.get("release_mbid", None)
        raw_album = str(row.get("album", "Unknown Album"))
        raw_artist = str(row.get("artist", "Unknown Artist"))

        listens = int(row.get("total_listens", 0))
        likes = int(row.get("Likes", 0))
        stats_str = f"{listens} Listens"
        if likes > 0:
            stats_str += f" | {likes} ❤️"

        # 1×1 composite for single album
        albums = [{"release_mbid": mbid}]
        composite = _composite_grid(albums, 1, cover_art_map, logo_tile, dark_tile)

        r = idx // ncols
        c = idx % ncols
        _render_art_block(
            fig, outer_gs[r, c], composite,
            title=raw_artist,
            subtitle=raw_album,
            detail=stats_str,
        )

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

    Each artist is rendered as a block with a dark header row (artist name,
    stats) above a single pre-composited side×side image.  The composite
    guarantees pixel-perfect squares with zero inter-tile gaps regardless
    of window size.

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

    logo_tile = _load_logo_tile()
    dark_tile = _make_dark_tile()

    n_artists = len(artist_data)

    # Layout: choose columns/rows to produce a landscape-friendly figure.
    # Each block is ~1 wide × 1.3 tall (square art + header), so a naive
    # sqrt layout would be too tall.  We target a figure aspect ratio of
    # ~1.6:1 (landscape) and solve for the column count that achieves it:
    #   (cols * block_w) / (rows * block_h) ≈ 1.6
    #   cols / ceil(n/cols) * (1/1.3) ≈ 1.6  →  cols ≈ sqrt(n * 1.6 * 1.3)
    block_aspect = 1.3   # height / width of each block (art + header)
    target_ratio = 1.6   # desired figure width / height
    outer_cols = max(1, min(n_artists, round(math.sqrt(n_artists * target_ratio * block_aspect))))
    outer_rows = math.ceil(n_artists / outer_cols)

    fig_w = max(8, outer_cols * 3.0)
    fig_h = max(5, outer_rows * 3.8)
    fig = Figure(figsize=(fig_w, fig_h), dpi=100)

    title_main = f"Art Matrix — {n_artists} Artists"
    subtitle = _build_filter_subtitle(filter_params)
    full_title = title_main
    if subtitle:
        full_title += " — " + subtitle
    fig.suptitle(full_title, fontsize=16, weight="bold", y=0.98)

    outer_gs = GridSpec(
        outer_rows, outer_cols, figure=fig,
        hspace=0.35, wspace=0.25,
        left=0.02, right=0.98, bottom=0.02, top=0.93,
    )

    for artist_idx, entry in enumerate(artist_data):
        outer_r = artist_idx // outer_cols
        outer_c = artist_idx % outer_cols

        artist_name = entry.get("artist", "Unknown Artist")
        total_listens = entry.get("total_listens", 0)
        likes = entry.get("likes", 0)
        albums = entry.get("albums", [])

        n_albums = len(albums)
        side = min(3, math.ceil(math.sqrt(n_albums))) if n_albums > 0 else 1

        stats_str = f"{total_listens} Listens"
        if likes > 0:
            stats_str += f" | {likes} ❤️"

        composite = _composite_grid(albums, side, cover_art_map, logo_tile, dark_tile)

        _render_art_block(
            fig, outer_gs[outer_r, outer_c], composite,
            title=artist_name,
            subtitle=stats_str,
        )

    create_chart_window(fig, "Entity Art Matrix", parent)