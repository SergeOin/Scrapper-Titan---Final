"""Analyze company names in database."""
import sqlite3

db_path = r'C:\Users\plogr\AppData\Local\TitanScraper\fallback.sqlite3'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute('SELECT author, company FROM posts')
posts = cursor.fetchall()

print('=== ANALYSE DES NOMS D ENTREPRISES ===')
print(f'Total posts: {len(posts)}')
print()

# Categorize
no_company = []
good_company = []
buggy_company = []

for author, company in posts:
    if not company:
        no_company.append(author)
    elif len(company) > 60 or '\n' in str(company) or company.count(' ') > 8:
        buggy_company.append((author, company[:100]))
    else:
        good_company.append((author, company))

print(f'Sans entreprise: {len(no_company)}')
print(f'Entreprises OK: {len(good_company)}')
print(f'Entreprises bugguees: {len(buggy_company)}')
print()

if buggy_company:
    print('=== ENTREPRISES BUGGUEES ===')
    for author, company in buggy_company[:15]:
        print(f'Auteur: {author}')
        print(f'Company: {repr(company)}')
        print('---')

print()
print('=== EXEMPLES ENTREPRISES OK ===')
for author, company in good_company[:10]:
    print(f'{author} -> {company}')

conn.close()
