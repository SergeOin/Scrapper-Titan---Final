#!/usr/bin/env python3
"""Fetch posts from API and write to file."""
import urllib.request
import json
import os

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api_posts.json")

try:
    # Call API
    req = urllib.request.Request("http://127.0.0.1:8000/api/posts?per_page=20")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    
    # Write to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"Wrote {len(data.get('posts', []))} posts to {OUTPUT_FILE}")
    print(f"Total: {data.get('total', 'N/A')}")
except Exception as e:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"Error: {e}")
    print(f"Error: {e}")

# Auto-run
if __name__ != "__main__":
    pass
