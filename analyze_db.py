"""Analyze SQLite database for QA report."""
import sqlite3
import os
from datetime import datetime

db_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'TitanScraper', 'fallback.sqlite3')
print('Database path:', db_path)
print('Exists:', os.path.exists(db_path))

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Tables existantes
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    print('Tables:', [t[0] for t in tables])
    
    # Compte des posts
    c.execute('SELECT COUNT(*) FROM posts')
    print('Total posts:', c.fetchone()[0])
    
    # Meta
    try:
        c.execute('SELECT * FROM meta')
        print('Meta:', c.fetchall())
    except:
        print('No meta table')
    
    # Distribution par intent
    try:
        c.execute('SELECT intent, COUNT(*) FROM posts GROUP BY intent')
        print('Intent distribution:', c.fetchall())
    except:
        print('No intent column')
    
    # Posts par date
    c.execute('SELECT DATE(collected_at) as d, COUNT(*) as c FROM posts GROUP BY DATE(collected_at) ORDER BY d DESC LIMIT 10')
    print('Posts by date:', c.fetchall())
    
    # Auteurs uniques
    c.execute('SELECT COUNT(DISTINCT author) FROM posts')
    print('Unique authors:', c.fetchone()[0])
    
    # Keywords
    c.execute('SELECT keyword, COUNT(*) as cnt FROM posts GROUP BY keyword ORDER BY cnt DESC LIMIT 10')
    print('Top keywords:', c.fetchall())
    
    # Check columns
    c.execute("PRAGMA table_info(posts)")
    cols = [row[1] for row in c.fetchall()]
    print('Columns in posts:', cols)
    
    # Sample des derniers posts
    c.execute('SELECT id, author, keyword, substr(text, 1, 150), permalink, collected_at FROM posts ORDER BY collected_at DESC LIMIT 8')
    print('\nLast 8 posts:')
    for row in c.fetchall():
        print(f'  ID: {row[0][:30]}...')
        print(f'    Author: {row[1]}')
        print(f'    Keyword: {row[2]}')
        print(f'    Collected: {row[5]}')
        print(f'    Permalink: {row[4][:60] if row[4] else "N/A"}...')
        print(f'    Text: {row[3][:120]}...')
        print()
    
    # Doublons potentiels
    c.execute('SELECT permalink, COUNT(*) as cnt FROM posts WHERE permalink IS NOT NULL GROUP BY permalink HAVING cnt > 1')
    dupes = c.fetchall()
    print('Duplicate permalinks:', len(dupes))
    
    conn.close()
else:
    print('Database not found')
