import sqlite3
import os

# Check post_cache.sqlite3
cache_db = os.path.join(os.environ['LOCALAPPDATA'], 'TitanScraper', 'post_cache.sqlite3')
print(f"Cache DB: {cache_db}")
print(f"Exists: {os.path.exists(cache_db)}")

if os.path.exists(cache_db):
    c = sqlite3.connect(cache_db)
    tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"Tables: {[t[0] for t in tables]}")
    for t in tables:
        tname = t[0]
        count = c.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
        print(f"  {tname}: {count} rows")
        if count > 0:
            cols = c.execute(f"PRAGMA table_info({tname})").fetchall()
            col_names = [col[1] for col in cols]
            print(f"    Columns: {col_names}")
            sample = c.execute(f"SELECT * FROM {tname} ORDER BY rowid DESC LIMIT 3").fetchall()
            for s in sample:
                print(f"    -> {s}")
    c.close()

# Also check fallback.sqlite3
print("\n--- Main DB Analysis ---")
main_db = os.path.join(os.environ['LOCALAPPDATA'], 'TitanScraper', 'fallback.sqlite3')
c = sqlite3.connect(main_db)

# Check for specific permalinks from recent scraping
test_permalinks = [
    'https://www.linkedin.com/search/results/content/?keywords=recrute%20juriste#post-2d9ca0f64ac9',
    'https://www.linkedin.com/feed/update/urn:li:share:7346217203173654529/',
]

print("\nChecking if recent posts exist:")
for pl in test_permalinks:
    cur = c.execute("SELECT id, author FROM posts WHERE permalink = ?", (pl,))
    row = cur.fetchone()
    if row:
        print(f"  FOUND: {row[1]}")
    else:
        print(f"  NOT FOUND: {pl[:50]}...")

# Check unique indexes
print("\nIndexes on posts table:")
idxs = c.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='posts'").fetchall()
for idx in idxs:
    print(f"  {idx[0]}")

# Check content_hash duplicates 
print("\nContent hash analysis:")
cur = c.execute("SELECT content_hash, COUNT(*) FROM posts GROUP BY content_hash HAVING COUNT(*) > 1 LIMIT 5")
dups = cur.fetchall()
if dups:
    print("  Duplicates found:")
    for d in dups:
        print(f"    {d}")
else:
    print("  No content_hash duplicates")

# Sample recent posts
print("\nLast 5 posts (by collected_at):")
cur = c.execute("SELECT author, permalink, collected_at, content_hash FROM posts ORDER BY collected_at DESC LIMIT 5")
for r in cur.fetchall():
    print(f"  {r[0][:25]} | {(r[1] or 'no-link')[:40]} | {r[2]}")

c.close()
