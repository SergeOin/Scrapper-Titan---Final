#!/usr/bin/env python3
"""Check permalink types in database."""
import sqlite3
import os

db_path = os.path.join(os.environ['LOCALAPPDATA'], 'TitanScraper', 'fallback.sqlite3')
conn = sqlite3.connect(db_path)

print("=" * 90)
print("20 posts les plus récents (tous):")
print("=" * 90)

c = conn.execute("""
    SELECT author, permalink, collected_at 
    FROM posts 
    ORDER BY collected_at DESC 
    LIMIT 20
""")

for row in c.fetchall():
    author = row[0][:25] if row[0] else "?"
    permalink = row[1] or ""
    collected = row[2][:16] if row[2] else ""
    
    # Classify permalink type
    if "/search/results/" in permalink:
        ptype = "SEARCH (old)"
    elif "#post-" in permalink:
        ptype = "PROFILE+HASH"
    elif "/feed/update/" in permalink:
        ptype = "REAL POST"
    else:
        ptype = "OTHER"
    
    print(f"{collected} | {author:25s} | {ptype:12s} | {permalink[:50]}")

print("\n" + "=" * 90)
print("Statistiques des types de permalinks:")
print("=" * 90)

stats = conn.execute("""
    SELECT 
        CASE 
            WHEN permalink LIKE '%/search/results/%' THEN 'SEARCH (old)'
            WHEN permalink LIKE '%#post-%' THEN 'PROFILE+HASH (new)'
            WHEN permalink LIKE '%/feed/update/%' THEN 'REAL POST URL'
            ELSE 'OTHER'
        END as type,
        COUNT(*) as count
    FROM posts 
    GROUP BY type
    ORDER BY count DESC
""")

for row in stats.fetchall():
    print(f"  {row[0]:25s}: {row[1]} posts")

conn.close()
