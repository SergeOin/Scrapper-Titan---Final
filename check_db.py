import sqlite3
import os
import json
import uuid
from datetime import datetime, timezone

db = os.path.expandvars(r'%LOCALAPPDATA%\TitanScraper\fallback.sqlite3')
print(f"DB: {db}")
c = sqlite3.connect(db)

print(f"Total posts: {c.execute('SELECT COUNT(*) FROM posts').fetchone()[0]}")

# Check if posts with similar content_hash or permalink exist
print("\n--- Checking for potential collisions ---")
# The permalinks from last scraping
permalinks = [
    "https://www.linkedin.com/search/results/content/?keywords=recrute%20notaire#post-57c20af18b0a",
    "https://www.linkedin.com/search/results/content/?keywords=recrute%20notaire#post-063a8f44308d"
]
for plink in permalinks:
    count = c.execute("SELECT COUNT(*) FROM posts WHERE permalink = ?", (plink,)).fetchone()[0]
    if count > 0:
        row = c.execute("SELECT id, author, collected_at FROM posts WHERE permalink = ?", (plink,)).fetchone()
        print(f"PERMALINK EXISTS: {plink[:50]}... -> {row}")
    else:
        print(f"PERMALINK NOT FOUND: {plink[:50]}...")

print("\n--- 10 derniers posts par collected_at ---")
for row in c.execute("SELECT author, collected_at FROM posts ORDER BY collected_at DESC LIMIT 10"):
    print(row)

print("\n--- Posts from today (2026-01-21) ---")
count = c.execute("SELECT COUNT(*) FROM posts WHERE collected_at > '2026-01-21'").fetchone()[0]
print(f"Posts collected on 2026-01-21: {count}")


