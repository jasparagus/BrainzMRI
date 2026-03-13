import sys
import os
import json

app_dir = r"c:\Users\jaspe\AppData\Local\Programs\BrainzMRI"
sys.path.insert(0, app_dir)

from api_client import LastFMClient

client = LastFMClient()

print("Attempting to load user data...")
with open(os.path.join(app_dir, "cache", "users", "jasparagus", "user.json"), "r") as f:
    user_data = json.load(f)
    username = user_data.get("lastfm_username", "jasparagus")

print(f"Fetching loved tracks for {username}...")
try:
    loves = client.get_user_loved_tracks(username, limit=50)
    print(f"Found {len(loves)} loved tracks.")
    
    # Check if the specific track is in there
    found = False
    for t in loves:
        if "sithu aye" in t.get("artist", "").lower() or "senpai" in t.get("track", "").lower():
            print(f"Found match in recent loves: {t}")
            found = True
            
    if not found:
        print("Did not find 'Senpai, Please Notice Me!' in recent loves.")
        
except Exception as e:
    print(f"Error: {e}")
