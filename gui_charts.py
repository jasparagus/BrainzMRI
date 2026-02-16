"""
gui_charts.py
Matplotlib visualization logic for BrainzMRI.
"""

import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import pandas as pd
import numpy as np
import math
import squarify  # Requires: pip install squarify

# Note: No Tkinter imports needed. We use native Matplotlib windows
# This provides improved speed and features (zooming, etc.)

def show_artist_trend_chart(df: pd.DataFrame):
    """
    Generate a Stacked Area Chart for Artist Trends (2 Rows).
    Top Row: Absolute Counts.
    Bottom Row: Normalized (Percentage) Dominance.
    """
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

    # Setup 2x1 Grid
    fig, axes = plt.subplots(2, 1, figsize=(10, 10), dpi=100, sharex=True)
    
    # Set Window Title
    if fig.canvas.manager:
        fig.canvas.manager.set_window_title("Favorite Artist Trend")
    
    ax_abs = axes[0]
    ax_norm = axes[1]
    
    x = chart_df.index
    labels = chart_df.columns
    
    # 1. Plot Absolute (Top)
    y_abs = [chart_df[col].values for col in chart_df.columns]
    ax_abs.stackplot(x, y_abs, labels=labels, alpha=0.8)
    
    ax_abs.set_title("Top Artist Dominance Over Time (Absolute)")
    ax_abs.set_ylabel("Listens")
    # Legend only on the top plot to avoid clutter
    ax_abs.legend(loc='upper left', bbox_to_anchor=(1, 1), title="Artists")
    
    # 2. Plot Normalized (Bottom)
    y_norm = [norm_df[col].values for col in norm_df.columns]
    ax_norm.stackplot(x, y_norm, labels=labels, alpha=0.8)
    
    ax_norm.set_title("Relative Dominance (Normalized)")
    ax_norm.set_ylabel("Fraction")
    ax_norm.set_xlabel("Time Period")
    ax_norm.set_ylim(0, 1.0)
    
    # Add a faint 50% line for reference
    ax_norm.axhline(y=0.5, color='gray', linestyle='--', alpha=0.3, linewidth=1)

    plt.tight_layout()
    plt.show()

def show_new_music_stacked_bar(df: pd.DataFrame):
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

    # Setup 2x3 Grid (2 Rows, 3 Columns)
    fig, axes = plt.subplots(2, 3, figsize=(14, 10), dpi=100, sharex=True)

    # Set Window Title
    if fig.canvas.manager:
        fig.canvas.manager.set_window_title("New Music By Year")
    
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
    for col_idx, (new_col, rec_col, title) in enumerate(metrics):
        
        # Get axes for this column (Top=Absolute, Bottom=Fraction)
        ax_abs = axes[0, col_idx]
        ax_frac = axes[1, col_idx]

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
    plt.tight_layout(rect=[0, 0.03, 1, 0.91])
    
    plt.show()

def show_genre_flavor_treemap(df: pd.DataFrame):
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
    
    # 3. Plot
    fig, ax = plt.subplots(figsize=(12, 8), dpi=100)

    # Set Window Title
    if fig.canvas.manager:
        fig.canvas.manager.set_window_title("Genre Flavor Profile")
    
    # Generate label text
    # e.g. "Metal\n5000 listens\n❤️270"
    labels = []
    for _, row in plot_df.iterrows():
        txt = f"{row[label_col]}\n{row[value_col]} listens"
        if like_col:
            txt += f"\n❤️{int(row[like_col])}"
        labels.append(txt)
    
    # Create color palette (viridis reversed looks nice for frequency)
    colors = plt.cm.viridis(np.linspace(0.8, 0.2, len(plot_df)))
    
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
    
    plt.tight_layout()
    plt.show()


def show_album_art_matrix(df: pd.DataFrame, cover_art_map: dict[str, str | None], filter_params: dict = None):
    """
    Render an N×M grid of album cover art thumbnails.
    
    Args:
        df: Album report DataFrame with artist, album, release_mbid, total_listens columns.
        cover_art_map: Dict mapping release_mbid -> local image filepath (or None).
        filter_params: Optional dict with report filter context for the title.
    """
    if df.empty:
        return

    # Limit to 150 albums max
    plot_df = df.head(150).copy()
    n = len(plot_df)

    # Calculate grid dimensions:
    #   - Landscape aspect ratio: ncols >= nrows, up to ncols <= 2*nrows
    #   - Prefer even grids (n % ncols == 0) to avoid hanging partial rows
    #   - Fallback: choose the layout with fewest empty cells in the last row
    best = None  # (ncols, nrows, empty_cells)
    for c in range(max(1, math.isqrt(n)), min(n + 1, 31)):  # reasonable col range
        r = math.ceil(n / c)
        if r < 1:
            continue
        ratio = c / r
        if ratio < 1.0 or ratio > 2.0:
            continue  # Outside the 1:1 to 2:1 window
        empty = (r * c) - n
        if best is None or empty < best[2] or (empty == best[2] and abs(ratio - 1.4) < abs(best[0] / best[1] - 1.4)):
            best = (c, r, empty)

    if best:
        ncols, nrows = best[0], best[1]
    else:
        # Fallback for very small n
        ncols = min(15, math.ceil(math.sqrt(n * 1.5)))
        nrows = math.ceil(n / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 1.5, nrows * 2.4), dpi=100)

    # Set Window Title
    if fig.canvas.manager:
        fig.canvas.manager.set_window_title("Album Art Matrix")

    # Build title with filter context
    title = f"Top {n} Albums"
    subtitle_parts = []
    if filter_params:
        # Date range
        t_start = filter_params.get("time_start_days", 0)
        t_end = filter_params.get("time_end_days", 0)
        if t_start > 0 or t_end > 0:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            d_from = (now - timedelta(days=t_end)).strftime("%Y-%m-%d")
            d_to = (now - timedelta(days=t_start)).strftime("%Y-%m-%d")
            subtitle_parts.append(f"{d_from} to {d_to}")

        # Thresholds
        min_l = filter_params.get("min_listens", 0)
        min_likes = filter_params.get("min_likes", 0)
        if min_l > 0 or min_likes > 0:
            subtitle_parts.append(f"{min_l}+ Listens")
            subtitle_parts.append(f"{min_likes}+ Likes")

    fig.suptitle(title, fontsize=14, weight="bold", y=0.99)
    if subtitle_parts:
        fig.text(0.5, 0.97, " | ".join(subtitle_parts), ha="center", fontsize=9, color="gray")

    # Flatten axes for easy indexing (handle single row/col edge cases)
    if nrows == 1 and ncols == 1:
        axes_flat = [axes]
    elif nrows == 1 or ncols == 1:
        axes_flat = list(axes)
    else:
        axes_flat = axes.flatten()

    for idx, ax in enumerate(axes_flat):
        ax.set_xticks([])
        ax.set_yticks([])

        if idx >= n:
            # Empty cell — hide it
            ax.axis("off")
            continue

        row = plot_df.iloc[idx]
        mbid = row.get("release_mbid", None)
        raw_album = str(row.get("album", ""))
        raw_artist = str(row.get("artist", ""))
        album = (raw_album[:32] + "...") if len(raw_album) > 32 else raw_album
        artist = (raw_artist[:30] + "...") if len(raw_artist) > 30 else raw_artist

        # Stats line
        listens = int(row.get("total_listens", 0))
        likes = int(row.get("Likes", 0))
        stats = f"{listens} listens | {likes}❤️"

        # Try to load cover art
        img_path = cover_art_map.get(mbid) if mbid else None

        if img_path:
            try:
                img = mpimg.imread(img_path)
                ax.imshow(img, aspect="equal")
            except Exception:
                # Fallback to solid color on read error
                img_path = None

        if not img_path:
            # Solid-color placeholder
            ax.set_facecolor("#333333")
            placeholder = (raw_album[:20] + "...") if len(raw_album) > 20 else (raw_album or "?")
            ax.text(
                0.5, 0.5, placeholder,
                transform=ax.transAxes,
                ha="center", va="center",
                color="white", fontsize=8, weight="bold",
                wrap=True,
            )

        # Label below cell: Album / Artist / Stats
        ax.set_xlabel(f"{album}\n{artist}\n{stats}", fontsize=6, labelpad=3)
        ax.xaxis.set_label_position("bottom")

        # Remove spines for cleaner look
        for spine in ax.spines.values():
            spine.set_visible(False)

    plt.subplots_adjust(hspace=0.8, wspace=0.15, top=0.94, bottom=0.04)
    plt.show()