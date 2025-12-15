import sqlite3
import os

db = os.path.expandvars('%LOCALAPPDATA%\\TitanScraper\\fallback.sqlite3')
print('DB:', db)
conn = sqlite3.connect(db)
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:', [r[0] for r in c.fetchall()])

c.execute("SELECT COUNT(*) FROM posts")
print('Posts count:', c.fetchone()[0])

c.execute("SELECT id, author, keyword FROM posts LIMIT 5")
for row in c.fetchall():
    print(row)
