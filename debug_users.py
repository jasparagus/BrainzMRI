"""
debug_users.py
Diagnose why users are not being detected in the cache.
"""
import os
from config import config

print("=== User Discovery Diagnostics ===")
print(f"1. App Root:   {config.app_root}")
print(f"2. Cache Dir:  {config.cache_dir}")

users_root = os.path.join(config.cache_dir, "users")
print(f"3. Users Root: {users_root}")

if not os.path.exists(users_root):
    print("   [ERROR] Users root directory does not exist!")
else:
    print("   [OK] Users root directory exists.")
    print("\n4. Scanning entries:")
    
    count = 0
    with os.scandir(users_root) as it:
        for entry in it:
            print(f"   - Found: '{entry.name}'")
            if entry.is_dir():
                json_path = os.path.join(entry.path, "user.json")
                exists = os.path.exists(json_path)
                status = "[VALID]" if exists else "[INVALID - Missing user.json]"
                print(f"     Type: Directory | user.json: {exists} -> {status}")
            else:
                print(f"     Type: File (Ignored)")
            count += 1
    
    if count == 0:
        print("\n   [WARN] No entries found in users directory.")

print("\n=== End Diagnostics ===")
input("Press Enter to close...")