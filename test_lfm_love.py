import sys
import os
import json

app_dir = r"c:\Users\jaspe\AppData\Local\Programs\BrainzMRI"
sys.path.insert(0, app_dir)

from api_client import LastFMClient
from config import config

client = LastFMClient()
session_key = config.lastfm_session_key if hasattr(config, "lastfm_session_key") else ""

print("Attempting to load user data for session key...")
with open(os.path.join(app_dir, "cache", "users", "jasparagus", "user.json"), "r") as f:
    user_data = json.load(f)
    session_key = user_data.get("lastfm_session_key")

print(f"Session key found: {'Yes' if session_key else 'No'}")

if session_key:
    # Test track that the user mentioned
    artist = "Sithu Aye"
    track = "Senpai, Please Notice Me!"
    print(f"Testing love_track for {artist} - {track}")
    try:
        method = "track.love"
        params = {
            "method": method,
            "api_key": client.api_key,
            "artist": artist,
            "track": track,
            "sk": session_key,
        }
        params["api_sig"] = client._sign_params(params)
        
        url = f"{client.base_url}?format=json"
        print(f"POSTing to url: {url}")
        resp = client.session.post(url, data=params, timeout=15)
        print(f"Status Code: {resp.status_code}")
        print(f"Response Body: {resp.text}")
        
    except Exception as e:
        print(f"Error: {e}")
