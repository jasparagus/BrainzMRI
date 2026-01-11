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
        self.geometry("900x600")
        
        # Container for the plot
        self.plot_frame = tk.Frame(self)
        self.plot_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Close button
        btn_close = tk.Button(self, text="Close", command=self.destroy)
        btn_close.pack(pady=5)

    def draw_artist_trend_area_chart(self, pivot_df: pd.DataFrame):
        """
        Draw a Stacked Area Chart for the Artist Trend report.
        
        Parameters
        ----------
        pivot_df : pd.DataFrame
            Index: Period (Time)
            Columns: Artists
            Values: Listen Counts
        """
        # Create Figure
        fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
        
        # Data preparation
        x = range(len(pivot_df.index))
        # Use simple integers for X-axis to avoid date parsing issues in matplotlib, 
        # then map labels back later.
        
        # Prepare stackplot data
        # Columns are artists (sorted by total volume in reporting.py ideally, or here)
        artists = pivot_df.columns.tolist()
        y_stack = [pivot_df[artist].values for artist in artists]
        
        # Plot
        # Use a colormap to distinguish artists
        cmap = plt.get_cmap("tab20")
        colors = [cmap(i % 20) for i in range(len(artists))]
        
        ax.stackplot(x, y_stack, labels=artists, colors=colors, alpha=0.8)
        
        # Styling
        ax.set_title("Top Artists Over Time (Stacked Trend)", fontsize=12, pad=15)
        ax.set_xlabel("Time Period")
        ax.set_ylabel("Listens")
        ax.margins(0, 0) # Remove white space at edges
        
        # X-Axis Labels (Reduce clutter if many bins)
        # We show every Nth label to prevent overlap
        labels = [str(p) for p in pivot_df.index]
        tick_indices = list(range(len(labels)))
        
        if len(labels) > 15:
            # Show ~10 ticks max
            step = len(labels) // 10
            tick_indices = tick_indices[::step]
            labels = [labels[i] for i in tick_indices]
            
        ax.set_xticks(tick_indices)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
        
        # Legend (Outside the plot to avoid covering data)
        # Reverse legend to match visual stack order (optional, but often preferred)
        handles, lbls = ax.get_legend_handles_labels()
        ax.legend(handles[::-1], lbls[::-1], loc='upper left', bbox_to_anchor=(1.02, 1), fontsize=9)
        
        plt.tight_layout()

        # Embed in Tkinter
        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)