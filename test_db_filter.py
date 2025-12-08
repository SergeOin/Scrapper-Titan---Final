"""Test Titan Partners filtering on real database."""
import sqlite3
from scraper.scrape_subprocess import filter_post_titan_partners, classify_author_type, MAX_POST_AGE_DAYS

db_path = r'C:\Users\plogr\AppData\Local\TitanScraper\fallback.sqlite3'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute('SELECT author, author_profile, company, text, published_at FROM posts')
posts = cursor.fetchall()

stats = {
    'total': len(posts),
    'accepted': 0,
    'rejected_agency': 0,
    'rejected_external': 0,
    'rejected_jobseeker': 0,
    'rejected_no_legal': 0,
    'rejected_too_old': 0,
    'rejected_other': 0,
}

accepted_posts = []
rejected_examples = {'agency': [], 'external': [], 'jobseeker': [], 'no_legal': [], 'too_old': []}

for author, author_profile, company, text, published_at in posts:
    post = {'author': author, 'author_profile': author_profile, 'company': company, 'text': text, 'published_at': published_at}
    is_valid, reason = filter_post_titan_partners(post)
    
    if is_valid:
        stats['accepted'] += 1
        accepted_posts.append((author, text[:80] if text else '', published_at))
    elif 'AGENCY' in reason:
        stats['rejected_agency'] += 1
        if len(rejected_examples['agency']) < 3:
            rejected_examples['agency'].append(author)
    elif 'EXTERNAL' in reason:
        stats['rejected_external'] += 1
        if len(rejected_examples['external']) < 3:
            rejected_examples['external'].append(author)
    elif 'JOBSEEKER' in reason:
        stats['rejected_jobseeker'] += 1
        if len(rejected_examples['jobseeker']) < 3:
            rejected_examples['jobseeker'].append(author)
    elif 'NO_LEGAL' in reason:
        stats['rejected_no_legal'] += 1
        if len(rejected_examples['no_legal']) < 3:
            rejected_examples['no_legal'].append(author)
    elif 'TOO_OLD' in reason:
        stats['rejected_too_old'] += 1
        if len(rejected_examples['too_old']) < 3:
            rejected_examples['too_old'].append((author, published_at))
    else:
        stats['rejected_other'] += 1

print('=' * 60)
print('RAPPORT FILTRAGE TITAN PARTNERS')
print(f'(Posts de moins de {MAX_POST_AGE_DAYS} jours / 3 semaines)')
print('=' * 60)
print(f"Total posts analyses: {stats['total']}")
print()
print(f"✅ ACCEPTES: {stats['accepted']} ({stats['accepted']/stats['total']*100:.1f}%)")
print(f"❌ Rejetes AGENCE: {stats['rejected_agency']}")
print(f"❌ Rejetes EXTERNE: {stats['rejected_external']}")
print(f"❌ Rejetes JOBSEEKER: {stats['rejected_jobseeker']}")
print(f"❌ Rejetes NO_LEGAL: {stats['rejected_no_legal']}")
print(f"❌ Rejetes TOO_OLD (>{MAX_POST_AGE_DAYS}j): {stats['rejected_too_old']}")
print(f"❌ Rejetes AUTRES: {stats['rejected_other']}")

if rejected_examples['too_old']:
    print()
    print('Exemples posts trop vieux:')
    for author, pub_date in rejected_examples['too_old']:
        print(f"  - {author}: {pub_date}")

print()
print('=' * 60)
print('EXEMPLES POSTS ACCEPTES (conformes Titan Partners)')
print('=' * 60)
for author, text, pub_date in accepted_posts[:10]:
    date_str = pub_date[:10] if pub_date else 'N/A'
    print(f"- [{date_str}] {author}: {text[:50]}...")

conn.close()
