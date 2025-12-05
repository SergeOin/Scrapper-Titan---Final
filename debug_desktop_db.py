#!/usr/bin/env python3
"""Debug script to check desktop DB state."""
import sqlite3

DB = r"C:\Users\plogr\AppData\Local\TitanScraper\fallback.sqlite3"

conn = sqlite3.connect(DB)
cur = conn.cursor()

print("=== DB DESKTOP ===")
cur.execute("SELECT COUNT(*) FROM posts")
print(f"Total posts: {cur.fetchone()[0]}")

try:
    cur.execute("SELECT COUNT(*) FROM post_flags")
    print(f"Total flags: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM post_flags WHERE is_deleted = 1")
    print(f"Posts supprimés (flagged): {cur.fetchone()[0]}")
except Exception as e:
    print(f"Pas de table post_flags: {e}")

# Check author filter
cur.execute("SELECT COUNT(*) FROM posts WHERE LOWER(author) = 'demo_recruteur'")
print(f"Demo posts: {cur.fetchone()[0]}")

# Check last collected
cur.execute("SELECT collected_at FROM posts ORDER BY collected_at DESC LIMIT 1")
print(f"Dernier post: {cur.fetchone()[0]}")

conn.close()
