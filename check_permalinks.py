import sqlite3
import os

db = os.path.join(os.environ['LOCALAPPDATA'], 'TitanScraper', 'fallback.sqlite3')
c = sqlite3.connect(db)

print('=== Exemples de permalinks ===')
cur = c.execute("""
    SELECT author, permalink 
    FROM posts 
    WHERE author != 'demo_recruteur' AND author != 'TEST_AUTHOR_MANUAL'
    ORDER BY collected_at DESC 
    LIMIT 15
""")
for r in cur.fetchall():
    author = (r[0] or 'None')[:30]
    permalink = r[1] or 'None'
    print(f'{author:30} | {permalink}')

print('\n=== Analyse des types de liens ===')
cur = c.execute("""
    SELECT 
        CASE 
            WHEN permalink LIKE '%/search/results/%' THEN 'search_results'
            WHEN permalink LIKE '%/feed/update/%' THEN 'real_post'
            WHEN permalink LIKE '%/posts/%' THEN 'company_post'
            ELSE 'other'
        END as link_type,
        COUNT(*) as cnt
    FROM posts 
    WHERE author != 'demo_recruteur'
    GROUP BY link_type
""")
for r in cur.fetchall():
    print(f'  {r[0]}: {r[1]} posts')

c.close()
