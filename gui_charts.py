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
    plt.show(block=False)

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
    
    plt.show(block=False)

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
    plt.show(block=False)


def show_album_art_matrix(df: pd.DataFrame, cover_art_map: dict[str, str | None], filter_params: dict = None):
    """
    Render an N×M grid of album cover art thumbnails.
    
    Args:
        df: Album report DataFrame with artist, album, release_mbid, total_listens columns.
        cover_art_map: Dict mapping release_mbid -> local image filepath (or None).
        filter_params: Optional dict with report filter context for the title.
    """
    import matplotlib.patheffects as pe
    import textwrap

    if df.empty:
        return

    # Limit to 150 albums max
    plot_df = df.head(150).copy()
    n = len(plot_df)

    # Calculate grid dimensions to maximize square artwork area
    # We enforce a stricter aspect ratio (cols/rows) to avoid very wide strips.
    # User prefers 4x2 for N=7 (ratio 2.0) and 5x3 for N=15 (ratio 1.66).
    best = None
    
    # Heuristic: iterate through possible column counts
    # Start from approx sqrt(n) up to n
    start_c = max(1, math.isqrt(n))
    for c in range(start_c, n + 2):
        r = math.ceil(n / c)
        if r == 0: continue
        
        ratio = c / r
        
        # Hard constraint: Ratio must be within reasonable landscape limits
        # 4x2 = 2.0 is acceptable. 8x2 = 4.0 is not.
        if ratio < 0.8 or ratio > 2.2:
            continue
            
        empty_spots = (r * c) - n
        
        # Score: minimize empty spots first, then closeness to ideal ratio (1.6)
        # We weigh empty spots heavily
        score = (empty_spots * 10.0) + abs(ratio - 1.6)
        
        if best is None or score < best[2]:
            best = (c, r, score)

    if best:
        ncols, nrows = best[0], best[1]
    else:
        # Fallback if no valid ratio found
        ncols = math.ceil(math.sqrt(n * 1.5))
        nrows = math.ceil(n / ncols)

    # Create figure with very thin margins
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 2, nrows * 2), dpi=100)

    # Set Window Title
    if fig.canvas.manager:
        fig.canvas.manager.set_window_title("Album Art Matrix")

    # Build title with filter context
    title_main = f"Top {n} Albums"
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
        if min_l > 0:
            subtitle_parts.append(f"{min_l}+ Listens")
        if min_likes > 0:
            subtitle_parts.append(f"{min_likes}+ Likes")

    full_title = title_main
    if subtitle_parts:
        full_title += " - " + " | ".join(subtitle_parts)

    fig.suptitle(full_title, fontsize=14, weight="bold", y=0.98)

    # Flatten axes for easy indexing
    if nrows == 1 and ncols == 1:
        axes_flat = [axes]
    elif nrows == 1 or ncols == 1:
        axes_flat = list(axes)
    else:
        axes_flat = axes.flatten()

    def format_text(text, max_chars=25, max_lines=2):
        if not text: return ""
        text = str(text)
        # normalize spaces
        text = " ".join(text.split())
        lines = textwrap.wrap(text, width=max_chars)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            if len(lines[-1]) > (max_chars - 3):
                lines[-1] = lines[-1][:(max_chars-3)] + "..."
            else:
                lines[-1] += "..."
        return "\n".join(lines)

    for idx, ax in enumerate(axes_flat):
        ax.set_xticks([])
        ax.set_yticks([])
        # Remove spines
        for spine in ax.spines.values():
            spine.set_visible(False)

        if idx >= n:
            # Empty cell
            ax.axis("off")
            continue

        row = plot_df.iloc[idx]
        mbid = row.get("release_mbid", None)
        raw_album = str(row.get("album", "Unknown Album"))
        raw_artist = str(row.get("artist", "Unknown Artist"))
        
        # 1. Image Handling
        img_path = cover_art_map.get(mbid) if mbid else None
        img_display = None
        
        if img_path:
            try:
                img = mpimg.imread(img_path)
                
                # Check dimensions and crop to square
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
        else:
            # Black/Dark Gray square background
            rect = plt.Rectangle((0, 0), 1, 1, color="#111111")
            ax.add_patch(rect)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)

        # 2. Text Overlay
        # Common style: White text, Black outline
        text_style = dict(
            ha='center', 
            color='white', 
            weight='bold', 
            transform=ax.transAxes,
            path_effects=[pe.withStroke(linewidth=2.5, foreground='black')]
        )

        # Artist: Top, centered
        artist_str = format_text(raw_artist, max_chars=20, max_lines=3)
        ax.text(0.5, 0.96, artist_str, va='top', fontsize=9, **text_style)

        # Stats: Very Bottom
        listens = int(row.get("total_listens", 0))
        likes = int(row.get("Likes", 0))
        stats_str = f"{listens} Listens"
        if likes > 0:
            stats_str += f" | {likes} ❤️"
        
        # We place Stats at bottom (e.g. 0.03)
        t_stats = ax.text(0.5, 0.03, stats_str, va='bottom', fontsize=8, **text_style)

        # Album: Bottom, above stats
        # We need to estimate where the stats text ends, or just place it at a fixed position like 0.12
        # A 2-line wrapped text might take up more space.
        album_str = format_text(raw_album, max_chars=20, max_lines=3)
        ax.text(0.5, 0.15, album_str, va='bottom', fontsize=9, **text_style)

    # Tight layout: minimize gaps
    # Leave room at top for title
    plt.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.92, wspace=0.02, hspace=0.02)
    plt.show(block=False)