"""Quick audit of posts in database."""
import sqlite3
import sys
sys.path.insert(0, r'C:\Users\plogr\Desktop\Scrapper-Titan---Final')

from scraper.scrape_subprocess import (
    filter_post_titan_partners, 
    classify_author_type,
    MAX_POST_AGE_DAYS
)

db_path = r'C:\Users\plogr\AppData\Local\TitanScraper\fallback.sqlite3'

try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM posts')
    count = c.fetchone()[0]
    print(f'Posts en BDD: {count}')
    
    if count == 0:
        print("Aucun post - attendez que le scraper collecte des donnees")
        conn.close()
        exit()
    
    # Get all posts
    c.execute('SELECT author, author_profile, company, text, published_at, permalink FROM posts')
    posts = c.fetchall()
    
    print()
    print("=" * 70)
    print("AUDIT DES POSTS - CRITERES TITAN PARTNERS (RENFORCE)")
    print("=" * 70)
    
    stats = {
        'total': len(posts),
        'passed': 0,
        'agency': 0,
        'external': 0,
        'jobseeker': 0,
        'non_recruitment': 0,
        'no_legal': 0,
        'no_signal': 0,
        'too_old': 0,
        'other': 0,
    }
    
    passed_posts = []
    failed_examples = {}
    
    for author, author_profile, company, text, published_at, permalink in posts:
        post = {
            'author': author,
            'author_profile': author_profile,
            'company': company,
            'text': text,
            'published_at': published_at,
            'permalink': permalink
        }
        
        is_valid, reason = filter_post_titan_partners(post)
        
        if is_valid:
            stats['passed'] += 1
            passed_posts.append(post)
        else:
            # Categorize rejection
            if 'AGENCY' in reason:
                stats['agency'] += 1
                cat = 'agency'
            elif 'EXTERNAL' in reason:
                stats['external'] += 1
                cat = 'external'
            elif 'JOBSEEKER' in reason:
                stats['jobseeker'] += 1
                cat = 'jobseeker'
            elif 'NON_RECRUITMENT' in reason:
                stats['non_recruitment'] += 1
                cat = 'non_recruitment'
            elif 'NO_LEGAL' in reason:
                stats['no_legal'] += 1
                cat = 'no_legal'
            elif 'NO_RECRUITMENT_SIGNAL' in reason:
                stats['no_signal'] += 1
                cat = 'no_signal'
            elif 'TOO_OLD' in reason:
                stats['too_old'] += 1
                cat = 'too_old'
            else:
                stats['other'] += 1
                cat = 'other'
            
            if cat not in failed_examples:
                failed_examples[cat] = []
            if len(failed_examples[cat]) < 2:
                failed_examples[cat].append((author, text[:60] if text else ''))
    
    print()
    print(f"Total posts: {stats['total']}")
    print(f"Passes (conformes Titan): {stats['passed']} ({stats['passed']/max(stats['total'],1)*100:.1f}%)")
    print()
    print("Rejetes par categorie:")
    print(f"  - Agences/Job boards: {stats['agency']}")
    print(f"  - Recrutement externe/tiers: {stats['external']}")
    print(f"  - Chercheurs emploi: {stats['jobseeker']}")
    print(f"  - Contenu non-recrutement: {stats['non_recruitment']}")
    print(f"  - Sans mots-cles juridiques: {stats['no_legal']}")
    print(f"  - Sans signal recrutement: {stats['no_signal']}")
    print(f"  - Trop vieux (>{MAX_POST_AGE_DAYS}j): {stats['too_old']}")
    
    print()
    print("=" * 70)
    print("EXEMPLES DE REJETS")
    print("=" * 70)
    for cat, examples in failed_examples.items():
        print(f"\n{cat.upper()}:")
        for author, text in examples:
            print(f"  - {author}: {text}...")
    
    print()
    print("=" * 70)
    print("POSTS CONFORMES TITAN PARTNERS")
    print("=" * 70)
    
    if not passed_posts:
        print("\nAucun post conforme aux criteres stricts.")
    else:
        for i, post in enumerate(passed_posts[:10], 1):
            author_type = classify_author_type(post['author'], post.get('author_profile'), post.get('company'))
            date_str = post['published_at'][:10] if post.get('published_at') else 'N/A'
            url_ok = 'linkedin.com' in (post.get('permalink') or '')
            
            print(f"\n{i}. {post['author']}")
            print(f"   Type: {author_type}")
            print(f"   Entreprise: {post.get('company') or 'N/A'}")
            print(f"   Date: {date_str}")
            print(f"   URL valide: {'OUI' if url_ok else 'NON'}")
            print(f"   Texte: {post.get('text', '')[:80]}...")
    
    conn.close()

except Exception as e:
    import traceback
    print(f"Erreur: {e}")
    traceback.print_exc()
