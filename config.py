"""
config.py
Centralized configuration management for BrainzMRI.
Handles file paths, constants, and persistent settings (config.json).
"""

import os
import json
import logging

class AppConfig:
    def __init__(self):
        # ------------------------------------------------------------------
        # 1. Static Paths & Constants
        # ------------------------------------------------------------------
        self.app_root = os.path.abspath(os.path.dirname(__file__))
        self.cache_dir = os.path.join(self.app_root, "cache")
        self.reports_dir = os.path.join(self.cache_dir, "reports")
        self.config_path = os.path.join(self.app_root, "config.json")
        self.log_file = os.path.join(self.app_root, "brainzmri.log")

        # API Endpoints
        self.lastfm_api_root = "https://ws.audioscrobbler.com/2.0/"
        self.musicbrainz_api_root = "https://musicbrainz.org/ws/2/"
        self.listenbrainz_api_root = "https://api.listenbrainz.org/1/"
        
        # User Agent
        self.user_agent = "BrainzMRI/1.0 (https://github.com/jasparagus/BrainzMRI)"

        # ------------------------------------------------------------------
        # 2. Dynamic Settings (Loaded from JSON/Env)
        # ------------------------------------------------------------------
        self.last_user = ""
        self.network_delay = 1.1  # Default safe delay
        self.max_retries = 5
        self.lastfm_api_key = os.environ.get("BRAINZMRI_LASTFM_API_KEY", "")
        self.lastfm_shared_secret = os.environ.get("BRAINZMRI_LASTFM_SECRET", "")
        self.log_level = "INFO" # none, INFO, DEBUG
        self.excluded_genres = []  # e.g. ["seen live", "spotify"] — lowercased at load

        # Initialize directories
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)

        # Load persistence
        self.load()

    def load(self):
        """Load settings from config.json if it exists."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.last_user = data.get("last_user", "")
                    self.network_delay = data.get("network_delay", 1.1)
                    
                    # API Key/Secret priority: Env Var > Config File > Empty
                    if not self.lastfm_api_key:
                        self.lastfm_api_key = data.get("lastfm_api_key", "")
                    if not self.lastfm_shared_secret:
                        self.lastfm_shared_secret = data.get("lastfm_shared_secret", "")
                    
                    self.log_level = data.get("log_level", "INFO")
                    self.excluded_genres = [g.lower().strip() for g in data.get("excluded_genres", [])]
        except Exception as e:
            logging.error(f"Failed to load config: {e}")

    def save(self):
        """Persist current settings to config.json."""
        data = {
            "last_user": self.last_user,
            "network_delay": self.network_delay,
            "lastfm_api_key": self.lastfm_api_key,
            "lastfm_shared_secret": self.lastfm_shared_secret,
            "log_level": self.log_level,
            "excluded_genres": self.excluded_genres
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

# Global Singleton instance
# Modules should import this: `from config import config`
config = AppConfig()