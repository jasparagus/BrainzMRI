"""
gui_charts.py
Matplotlib visualization logic for BrainzMRI.
"""

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
import pandas as pd
import numpy as np
import squarify  # Requires: pip install squarify

def _show_figure_window(fig, title="Chart"):
    """Helper to display a matplotlib figure in a new Tkinter window."""
    window = tk.Toplevel()
    window.title(title)
    window.geometry("1000x800")
    
    canvas = FigureCanvasTkAgg(fig, master=window)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)

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
    # fillna(0) handles potential division by zero if a time block has 0 listens
    norm_df = chart_df.div(chart_df.sum(axis=1), axis=0).fillna(0)

    # Setup 2x1 Grid
    fig, axes = plt.subplots(2, 1, figsize=(10, 10), dpi=100, sharex=True)
    
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
    _show_figure_window(fig, title="Favorite Artist Trend")

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
    # sharex=True aligns the years between top and bottom rows
    fig, axes = plt.subplots(2, 3, figsize=(14, 10), dpi=100, sharex=True)
    
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
    
    _show_figure_window(fig, title="New Music By Year")

def show_genre_flavor_treemap(df: pd.DataFrame):
    """
    Generate a Treemap for Genre Flavor using squarify.
    Expects a DataFrame with a string column (Genre) and numeric column (Count).
    """
    # 1. Identify Columns
    str_cols = df.select_dtypes(include=['object', 'string']).columns
    num_cols = df.select_dtypes(include=['number']).columns
    
    if len(str_cols) == 0 or len(num_cols) == 0:
        raise ValueError("Data must have at least one text column and one numeric column.")
        
    label_col = str_cols[0]
    value_col = num_cols[0]
    
    # 2. Filter Top 30
    plot_df = df.sort_values(by=value_col, ascending=False).head(30)
    
    # 3. Plot
    fig, ax = plt.subplots(figsize=(12, 8), dpi=100)
    
    # Generate label text with counts: "Metal\n(7619)"
    labels = [
        f"{row[label_col]}\n({row[value_col]})" 
        for _, row in plot_df.iterrows()
    ]
    
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
    _show_figure_window(fig, title="Genre Flavor Profile")