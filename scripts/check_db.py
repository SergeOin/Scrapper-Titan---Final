"""Check database content."""
import sqlite3
import os

db = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'TitanScraper', 'fallback.sqlite3')
print(f"=== Base de données: {db} ===")
print(f"Taille: {os.path.getsize(db) / 1024:.1f} KB")

conn = sqlite3.connect(db)
cur = conn.cursor()

# Tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cur.fetchall()]
print(f"\nTables: {tables}")

for table in tables:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    print(f"  {table}: {count} enregistrements")

# Derniers posts
if 'posts' in tables:
    print("\n=== 10 derniers posts ===")
    cur.execute("SELECT keyword, author, collected_at FROM posts ORDER BY collected_at DESC LIMIT 10")
    for r in cur.fetchall():
        print(f"  {r[0][:25]:25} | {r[1][:30]:30} | {r[2]}")
        
    # Posts d'aujourd'hui
    cur.execute("SELECT COUNT(*) FROM posts WHERE date(collected_at) = date('now')")
    today = cur.fetchone()[0]
    print(f"\nPosts collectés aujourd'hui: {today}")
    
    # Posts d'hier
    cur.execute("SELECT COUNT(*) FROM posts WHERE date(collected_at) = date('now', '-1 day')")
    yesterday = cur.fetchone()[0]
    print(f"Posts collectés hier: {yesterday}")

conn.close()
