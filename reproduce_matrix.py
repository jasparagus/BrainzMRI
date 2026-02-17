
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from gui_charts import show_album_art_matrix

# 1. Create Dummy Images
os.makedirs("test_images", exist_ok=True)

# Square image (Red gradient)
img_sq = np.zeros((200, 200, 3), dtype=np.uint8)
for i in range(200):
    img_sq[i, :, 0] = i * 255 // 200
img_sq[:, :, 1] = 50  # Fixed Green
img_sq[:, :, 2] = 50  # Fixed Blue
plt.imsave("test_images/square.png", img_sq)

# Wide image (Blue gradient) - to be cropped
img_wide = np.zeros((200, 300, 3), dtype=np.uint8)
for i in range(300):
    img_wide[:, i, 2] = i * 255 // 300
img_wide[:, :, 0] = 50 
img_wide[:, :, 1] = 50
plt.imsave("test_images/wide.png", img_wide)

# Tall image (Green gradient) - to be cropped
img_tall = np.zeros((300, 200, 3), dtype=np.uint8)
for i in range(300):
    img_tall[i, :, 1] = i * 255 // 300
img_tall[:, :, 0] = 50
img_tall[:, :, 2] = 50
plt.imsave("test_images/tall.png", img_tall)

# 2. Generate Data
def generate_df(n):
    data = []
    for i in range(n):
        # Alternate specific cases to test robustness
        if i % 3 == 0:
            mbid = "square_mbid"
            artist = "Square Artist Very Long Name That Should Wrap At Some Point"
            album = "Square Album That Is Also Quite Long And Needs Wrapping"
        elif i % 3 == 1:
            mbid = "wide_mbid"
            artist = "Wide Artist"
            album = "Wide Album"
        else:
            mbid = "tall_mbid"
            artist = "Tall Artist"
            album = "Tall Album"
            
        data.append({
            "artist": artist + f" {i}",
            "album": album + f" {i}",
            "release_mbid": mbid, # Using same mbid to map to same image
            "total_listens": (n - i) * 100,
            "Likes": (n - i) * 5
        })
    return pd.DataFrame(data)

cover_art_map = {
    "square_mbid": "test_images/square.png",
    "wide_mbid": "test_images/wide.png",
    "tall_mbid": "test_images/tall.png"
}

filter_params = {
    "time_start_days": 30,
    "time_end_days": 0,
    "min_listens": 10,
    "min_likes": 5
}

# 3. Run Tests
for n in [7, 15, 150]:
    print(f"Generating matrix for N={n}...")
    df = generate_df(n)
    
    # We need to monkeypatch plt.show so it doesn't block or pop up windows, 
    # but we can save the figure.
    # Actually gui_charts uses plt.show(block=False), so execution continues.
    # We just need to grab the figure.
    
    # Close any existing figures
    plt.close('all')
    
    show_album_art_matrix(df, cover_art_map, filter_params)
    
    # Save the current figure
    fig = plt.gcf()
    fig.savefig(f"matrix_test_{n}.png")
    print(f"Saved matrix_test_{n}.png")

print("Done.")
