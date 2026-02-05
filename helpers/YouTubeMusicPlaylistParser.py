import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
import json
import os
from datetime import datetime, timezone

class Track:
    def __init__(self, title, artist, album, duration_str):
        self.title = title
        self.artist = artist
        self.album = album
        self.duration_str = duration_str
        self.duration_ms = self._convert_duration_to_ms(duration_str)

    def _convert_duration_to_ms(self, duration_str):
        if not duration_str:
            return 0
        try:
            parts = list(map(int, duration_str.split(':')))
            if len(parts) == 2:
                return ((parts[0] * 60) + parts[1]) * 1000
            elif len(parts) == 3:
                return ((parts[0] * 3600) + (parts[1] * 60) + parts[2]) * 1000
        except ValueError:
            return 0
        return 0

class PlaylistParser:
    @staticmethod
    def clean_text(text):
        # Remove tags if they appear
        return text.strip()

    @staticmethod
    def parse(file_content):
        tracks = []
        
        # Normalize newlines
        content = file_content.replace('\r\n', '\n')
        
        # Split by duration lines (digits:digits)
        parts = re.split(r'\n\s*(\d{1,2}:\d{2})\s*\n', content)
        
        current_block_text = parts[0]
        
        for i in range(1, len(parts), 2):
            duration = parts[i]
            track = PlaylistParser._process_block(current_block_text, duration)
            if track:
                tracks.append(track)
            
            if i + 1 < len(parts):
                current_block_text = parts[i+1]

        return tracks

    @staticmethod
    def _process_block(text_block, duration):
        text_block = PlaylistParser.clean_text(text_block)
        lines = [line.strip() for line in text_block.split('\n') if line.strip()]
        
        if len(lines) < 2:
            return None

        # Logic: Line 0 = Title, Last Line = Album, In-between = Artist
        title = lines[0]
        album = lines[-1]
        
        if len(lines) > 2:
            artist_lines = lines[1:-1]
            raw_artist = " ".join(artist_lines)
            artist = re.sub(r'\s+([,&])\s+', r'\1 ', raw_artist)
            artist = artist.replace(" ,", ",").replace(" &", " &") 
        else:
            artist = lines[1]
            album = "Unknown Album"

        return Track(title, artist, album, duration)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Music -> ListenBrainz Converter")
        self.geometry("800x600")
        
        self.tracks = []

        # -- UI Layout --
        btn_frame = tk.Frame(self)
        btn_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)
        
        self.btn_load = tk.Button(btn_frame, text="Load Text File", command=self.load_file)
        self.btn_load.pack(side=tk.LEFT, padx=5)
        
        self.btn_save = tk.Button(btn_frame, text="Save Playlists (XSPF & JSPF)", command=self.save_playlists, state=tk.DISABLED)
        self.btn_save.pack(side=tk.LEFT, padx=5)
        
        self.lbl_status = tk.Label(btn_frame, text="No file loaded", fg="gray")
        self.lbl_status.pack(side=tk.LEFT, padx=15)

        tree_frame = tk.Frame(self)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        cols = ("Title", "Artist", "Album", "Duration")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
            
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def load_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            raw_tracks = PlaylistParser.parse(content)
            
            # --- REMOVE DUPLICATES ---
            unique_tracks = []
            seen = set()
            for t in raw_tracks:
                # Create a unique key: (Title, Artist, Album) lowercased
                key = (t.title.strip().lower(), t.artist.strip().lower(), t.album.strip().lower())
                if key not in seen:
                    seen.add(key)
                    unique_tracks.append(t)
            
            self.tracks = unique_tracks

            # --- SORT ---
            # Sorts by Artist (case-insensitive), then by Album (case-insensitive)
            self.tracks.sort(key=lambda t: (t.artist.lower(), t.album.lower()))
            
            self.refresh_table()
            
            self.lbl_status.config(text=f"Loaded {len(self.tracks)} tracks (Duplicates removed).", fg="green")
            self.btn_save.config(state=tk.NORMAL)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse file: {e}")

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for t in self.tracks:
            self.tree.insert("", tk.END, values=(t.title, t.artist, t.album, t.duration_str))

    def save_playlists(self):
        if not self.tracks:
            return
            
        file_path = filedialog.asksaveasfilename(title="Save Playlists", filetypes=[("Playlist Files", "*.*")])
        if not file_path:
            return

        base_path = os.path.splitext(file_path)[0]
        
        try:
            self.write_xspf(base_path + ".xspf")
            self.write_jspf_listenbrainz(base_path + ".jspf")
            messagebox.showinfo("Success", f"Saved:\n{base_path}.xspf\n{base_path}.jspf")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save files: {e}")

    def write_xspf(self, path):
        # Standard XSPF (unchanged)
        root = ET.Element("playlist", version="1", xmlns="http://xspf.org/ns/0/")
        track_list = ET.SubElement(root, "trackList")
        
        for t in self.tracks:
            track_elem = ET.SubElement(track_list, "track")
            
            title = ET.SubElement(track_elem, "title")
            title.text = t.title
            
            creator = ET.SubElement(track_elem, "creator")
            creator.text = t.artist
            
            album = ET.SubElement(track_elem, "album")
            album.text = t.album
            
            if t.duration_ms > 0:
                duration = ET.SubElement(track_elem, "duration")
                duration.text = str(t.duration_ms)

        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml_str)

    def write_jspf_listenbrainz(self, path):
        # Generates JSPF with ListenBrainz specific extension fields
        
        now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        
        playlist_data = {
            "playlist": {
                "title": "YouTube Music Export",
                "creator": "YouTubeMusicPlaylistParser",
                "date": now_iso,
                "extension": {
                    "https://musicbrainz.org/doc/jspf#playlist": {
                        "created_for": "user",
                        "creator": "YouTubeMusicPlaylistParser",
                        "public": False,
                        "last_modified_at": now_iso
                    }
                },
                "track": []
            }
        }
        
        for t in self.tracks:
            track_obj = {
                "title": t.title,
                "creator": t.artist,
                "album": t.album,
                "extension": {
                    "https://musicbrainz.org/doc/jspf#track": {
                        "added_by": "user",
                        "added_at": now_iso
                    }
                }
            }
            if t.duration_ms > 0:
                track_obj["duration"] = t.duration_ms
            
            playlist_data["playlist"]["track"].append(track_obj)
            
        with open(path, "w", encoding="utf-8") as f:
            json.dump(playlist_data, f, indent=4)

if __name__ == "__main__":
    app = App()
    app.mainloop()