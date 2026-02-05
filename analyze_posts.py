import sqlite3
import os
from collections import Counter

db = os.path.join(os.environ['LOCALAPPDATA'], 'TitanScraper', 'fallback.sqlite3')
c = sqlite3.connect(db)

# Posts per day
print('=== Posts distribution by day ===')
cur = c.execute('''
    SELECT DATE(collected_at) as day, COUNT(*) as cnt 
    FROM posts 
    WHERE author != 'demo_recruteur' 
    GROUP BY DATE(collected_at) 
    ORDER BY day DESC
''')
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]} posts')

# Unique authors
print('\n=== Stats ===')
cur = c.execute("SELECT COUNT(DISTINCT author) FROM posts WHERE author != 'demo_recruteur'")
print(f'Unique authors: {cur.fetchone()[0]}')

cur = c.execute("SELECT COUNT(*) FROM posts WHERE author != 'demo_recruteur'")
print(f'Real posts (excl demo): {cur.fetchone()[0]}')

cur = c.execute("SELECT COUNT(*) FROM posts WHERE author = 'demo_recruteur'")
print(f'Demo posts: {cur.fetchone()[0]}')

# Check hourly rate today
print('\n=== Hourly distribution today ===')
cur = c.execute('''
    SELECT strftime('%H', collected_at) as hour, COUNT(*) as cnt 
    FROM posts 
    WHERE DATE(collected_at) = DATE('now') AND author != 'demo_recruteur'
    GROUP BY hour
    ORDER BY hour
''')
for row in cur.fetchall():
    print(f'  Hour {row[0]}: {row[1]} posts')

# Recent authors
print('\n=== Last 10 real posts ===')
cur = c.execute('''
    SELECT author, keyword, collected_at 
    FROM posts 
    WHERE author != 'demo_recruteur' AND author != 'TEST_AUTHOR_MANUAL'
    ORDER BY collected_at DESC
    LIMIT 10
''')
for row in cur.fetchall():
    print(f'  {row[2][:16]} | {row[1][:20]} | {row[0][:30]}')

c.close()
