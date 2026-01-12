"""
gui_charts.py
Handles chart rendering using the native Matplotlib UI.
"""

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Ensure we use the TkAgg backend to share the loop with the main GUI
matplotlib.use("TkAgg")


def show_artist_trend_chart(pivot_df: pd.DataFrame):
    """
    Draw a Stacked Area Chart for the Artist Trend report in a native window.
    """
    # Create a new figure manager
    fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
    
    x = range(len(pivot_df.index))
    artists = pivot_df.columns.tolist()
    y_stack = [pivot_df[artist].values for artist in artists]
    
    cmap = plt.get_cmap("tab20")
    colors = [cmap(i % 20) for i in range(len(artists))]
    
    ax.stackplot(x, y_stack, labels=artists, colors=colors, alpha=0.8)
    
    ax.set_title("Top Artists Over Time (Stacked Trend)", fontsize=12, pad=15)
    ax.set_xlabel("Time Period")
    ax.set_ylabel("Listens")
    ax.margins(0, 0)
    
    # X-Axis Labels
    labels = [str(p) for p in pivot_df.index]
    tick_indices = list(range(len(labels)))
    
    if len(labels) > 15:
        step = len(labels) // 10
        tick_indices = tick_indices[::step]
        labels = [labels[i] for i in tick_indices]
        
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    
    # Legend - Keep outside for this one as it can be large
    handles, lbls = ax.get_legend_handles_labels()
    # Reverse legend to match visual stack order
    ax.legend(handles[::-1], lbls[::-1], loc='upper left', bbox_to_anchor=(1.02, 1), fontsize=9)
    
    plt.tight_layout()
    
    # Show native non-blocking window (with Zoom/Pan toolbar)
    plt.show(block=False)


def show_new_music_stacked_bar(df: pd.DataFrame):
    """
    Draw 3 Subplots (Artists, Albums, Tracks) showing New vs Recurring counts.
    Legends are placed INSIDE each subplot to prevent cropping.
    """
    if df.empty:
        return

    # Create a new figure manager
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14, 6), dpi=100, sharex=True)
    
    years = df["Year"].astype(str).tolist()
    x = np.arange(len(years))
    width = 0.6

    # Helper to plot one subplot
    def plot_entity(ax, title, unique_col, new_col):
        total = df[unique_col].values
        new_count = df[new_col].values
        recurring_count = total - new_count
        
        # Plot "Recurring" at bottom (Blue)
        ax.bar(x, recurring_count, width, label='Recurring', color='#4c72b0', alpha=0.9)
        # Plot "New" on top (Orange)
        ax.bar(x, new_count, width, bottom=recurring_count, label='New (First Listen)', color='#dd8452', alpha=0.9)
        
        ax.set_title(title, fontsize=11, pad=10)
        ax.set_xticks(x)
        ax.set_xticklabels(years, rotation=45, ha="right")
        ax.grid(axis='y', linestyle='--', alpha=0.5)
        
        # LEGEND FIX: Place inside the plot area (best fit)
        ax.legend(loc='best', fontsize=9, framealpha=0.9)

    # 1. Artists
    plot_entity(ax1, "Unique Artists", "Unique Artists", "New Artists")
    ax1.set_ylabel("Count")

    # 2. Albums
    plot_entity(ax2, "Unique Albums", "Unique Albums", "New Albums")

    # 3. Tracks
    plot_entity(ax3, "Unique Tracks", "Unique Tracks", "New Tracks")

    plt.tight_layout()
    plt.show(block=False)