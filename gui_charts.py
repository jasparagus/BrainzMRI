"""
gui_charts.py
Handles chart rendering and window management using Matplotlib and Tkinter.
"""

import tkinter as tk
from tkinter import ttk
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
import numpy as np

# Ensure we use the TkAgg backend
matplotlib.use("TkAgg")


class ChartWindow(tk.Toplevel):
    """
    A modal (or non-modal) window to display a Matplotlib chart.
    """

    def __init__(self, parent, title="Chart"):
        super().__init__(parent)
        self.title(title)
        self.geometry("1100x600") # Wider to accommodate subplots
        
        # Container for the plot
        self.plot_frame = tk.Frame(self)
        self.plot_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Close button
        btn_close = tk.Button(self, text="Close", command=self.destroy)
        btn_close.pack(pady=5)

    def draw_artist_trend_area_chart(self, pivot_df: pd.DataFrame):
        """
        Draw a Stacked Area Chart for the Artist Trend report.
        """
        fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
        
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
        
        labels = [str(p) for p in pivot_df.index]
        tick_indices = list(range(len(labels)))
        
        if len(labels) > 15:
            step = len(labels) // 10
            tick_indices = tick_indices[::step]
            labels = [labels[i] for i in tick_indices]
            
        ax.set_xticks(tick_indices)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
        
        handles, lbls = ax.get_legend_handles_labels()
        ax.legend(handles[::-1], lbls[::-1], loc='upper left', bbox_to_anchor=(1.02, 1), fontsize=9)
        
        plt.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def draw_new_music_stacked_bar(self, df: pd.DataFrame):
        """
        Draw 3 Subplots (Artists, Albums, Tracks) showing New vs Recurring counts per year.
        Expected columns: Year, Unique Artists, New Artists, etc.
        """
        if df.empty:
            return

        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(12, 5), dpi=100, sharex=True)
        
        years = df["Year"].astype(str).tolist()
        x = np.arange(len(years))
        width = 0.6

        # Helper to plot one subplot
        def plot_entity(ax, title, unique_col, new_col):
            total = df[unique_col].values
            new_count = df[new_col].values
            # Recurring = Total - New
            recurring_count = total - new_count
            
            # Plot "Recurring" at bottom (Blue)
            p1 = ax.bar(x, recurring_count, width, label='Recurring', color='#4c72b0', alpha=0.9)
            # Plot "New" on top (Orange)
            p2 = ax.bar(x, new_count, width, bottom=recurring_count, label='New', color='#dd8452', alpha=0.9)
            
            ax.set_title(title, fontsize=11)
            ax.set_xticks(x)
            ax.set_xticklabels(years, rotation=45, ha="right")
            ax.grid(axis='y', linestyle='--', alpha=0.5)
            
            return p1, p2

        # 1. Artists
        plot_entity(ax1, "Unique Artists", "Unique Artists", "New Artists")
        ax1.set_ylabel("Count")

        # 2. Albums
        plot_entity(ax2, "Unique Albums", "Unique Albums", "New Albums")

        # 3. Tracks
        p1, p2 = plot_entity(ax3, "Unique Tracks", "Unique Tracks", "New Tracks")

        # Shared Legend
        fig.legend([p2, p1], ["New (Discovered)", "Recurring"], loc='upper center', bbox_to_anchor=(0.5, 1.05), ncol=2)
        
        plt.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)