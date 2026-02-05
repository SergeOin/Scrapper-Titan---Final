import sqlite3
import os

# Check main posts database
db = os.path.join(os.environ['LOCALAPPDATA'], 'TitanScraper', 'fallback.sqlite3')
c = sqlite3.connect(db)

print("=== MAIN DATABASE ===")
print("Path:", db)
print()

# List all tables
tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("Tables:", tables)
print()

# Count posts
print("Total posts:", c.execute('SELECT COUNT(*) FROM posts').fetchone()[0])
print()

# Search for specific authors
print("Search for 'Victor Charpiat':")
rows = c.execute("SELECT id, author, permalink FROM posts WHERE author LIKE '%Victor%'").fetchall()
print(rows if rows else "  Not found")

print()
print("Search for 'Lucien':")
rows = c.execute("SELECT id, author, permalink FROM posts WHERE author LIKE '%Lucien%'").fetchall()
print(rows if rows else "  Not found")

print()
print("Search for non-demo authors:")
rows = c.execute("SELECT DISTINCT author FROM posts WHERE author != 'demo_recruteur'").fetchall()
print(rows if rows else "  Only demo_recruteur found")

print()
print("Last 5 rowids:")
rows = c.execute("SELECT rowid, id, author FROM posts ORDER BY rowid DESC LIMIT 5").fetchall()
for r in rows:
    print(f"  rowid={r[0]} id={r[1][:12]}... author={r[2]}")
