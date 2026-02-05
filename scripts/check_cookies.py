#!/usr/bin/env python3
"""Check for expired cookies in storage_state.json."""
import json
import time

STORAGE_PATH = r"C:\Users\plogr\AppData\Local\TitanScraper\storage_state.json"

def main():
    with open(STORAGE_PATH) as f:
        storage = json.load(f)
    
    now = time.time()
    print(f"Current time: {now:.0f}")
    print("-" * 60)
    
    expired_count = 0
    for c in storage.get("cookies", []):
        name = c.get("name", "?")
        exp = c.get("expires", -1)
        if exp == -1:
            status = "session"
        elif exp < now:
            status = "EXPIRED"
            expired_count += 1
        else:
            status = "valid"
        print(f"{name:20} expires={exp:15.0f} status={status}")
    
    print("-" * 60)
    print(f"Total cookies: {len(storage.get('cookies', []))}, Expired: {expired_count}")

if __name__ == "__main__":
    main()
