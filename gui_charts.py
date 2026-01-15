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
    window.geometry("1000x700")
    
    canvas = FigureCanvasTkAgg(fig, master=window)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)

def show_artist_trend_chart(df: pd.DataFrame):
    """
    Generate a Stacked Area Chart for Artist Trends.
    """
    chart_df = df.copy()
    if not isinstance(chart_df.index, pd.DatetimeIndex):
        try:
            chart_df.index = pd.to_datetime(chart_df.index)
        except Exception:
            pass 
    
    chart_df = chart_df.sort_index()

    fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
    
    x = chart_df.index
    y = [chart_df[col].values for col in chart_df.columns]
    labels = chart_df.columns

    ax.stackplot(x, y, labels=labels, alpha=0.8)
    
    ax.set_title("Top Artist Dominance Over Time")
    ax.set_xlabel("Time Period")
    ax.set_ylabel("Listens")
    ax.legend(loc='upper left', bbox_to_anchor=(1, 1), title="Artists")
    
    plt.tight_layout()
    _show_figure_window(fig, title="Favorite Artist Trend")

def show_new_music_stacked_bar(df: pd.DataFrame):
    """
    Generate a Stacked Bar Chart for New Music By Year.
    Legend removed; Title color-coded manually.
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

    fig, axes = plt.subplots(1, 3, figsize=(14, 7), dpi=100, sharey=False)
    
    metrics = [
        ("New Artists", "Recurring Artists", "Artists"),
        ("New Albums", "Recurring Albums", "Albums"),
        ("New Tracks", "Recurring Tracks", "Tracks"),
    ]
    
    years = plot_df["Year"]
    
    # Colors
    c_new = "#4CAF50" # Green
    c_rec = "#2196F3" # Blue

    for ax, (new_col, rec_col, title) in zip(axes, metrics):
        if new_col not in plot_df.columns or rec_col not in plot_df.columns:
            ax.text(0.5, 0.5, "Data Missing", ha='center')
            continue
            
        ax.bar(years, plot_df[new_col], label="New", alpha=0.8, color=c_new)
        ax.bar(years, plot_df[rec_col], bottom=plot_df[new_col], label="Recurring", alpha=0.8, color=c_rec)
        
        ax.set_title(title)
        ax.set_xlabel("Year")
        if ax == axes[0]:
            ax.set_ylabel("Count")
            # LEGEND REMOVED as per request
            # ax.legend()

    # Custom Multi-Colored Title Construction
    # We use fig.text relative coordinates to simulate a rich-text title
    
    # Main Header
    fig.text(0.5, 0.96, "Music Discovery by Year", ha='center', fontsize=16, weight='bold')
    
    # Color-coded Sub-header acting as Title + Legend
    # Centered alignment logic: 
    # [New Artists] [vs.] [Recurring Artists]
    
    fig.text(0.42, 0.92, "New Artists", color=c_new, weight='bold', ha='right', fontsize=12)
    fig.text(0.50, 0.92, "vs.", color='black', ha='center', fontsize=12)
    fig.text(0.58, 0.92, "Recurring Artists", color=c_rec, weight='bold', ha='left', fontsize=12)

    # Adjust layout to make room for the custom header
    plt.tight_layout(rect=[0, 0.03, 1, 0.90])
    
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