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

artist = "Sithu Aye"
track = "Senpai, Please Notice Me!"

print(f"Fetching track info for {artist} - {track}...")
try:
    method = "track.getInfo"
    params = {
        "method": method,
        "api_key": client.api_key,
        "artist": artist,
        "track": track,
        "username": username,
        "format": "json"
    }
    
    url = f"{client.base_url}"
    print(f"GET url: {url}")
    resp = client.session.get(url, params=params, timeout=15)
    print(f"Status Code: {resp.status_code}")
    
    data = resp.json()
    t = data.get("track", {})
    userloved = t.get("userloved")
    userplaycount = t.get("userplaycount")
    
    print(f"userloved: {userloved}")
    print(f"userplaycount: {userplaycount}")
    
except Exception as e:
    print(f"Error: {e}")
