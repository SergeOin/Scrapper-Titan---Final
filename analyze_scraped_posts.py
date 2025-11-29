"""Script pour analyser tous les posts scrapés avec le nouveau filtre legal_filter."""
import sqlite3
import json
from collections import Counter
from scraper.legal_filter import is_legal_job_post

def analyze_posts():
    # Connexion à la base SQLite
    conn = sqlite3.connect('fallback.sqlite3')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Lister les tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tables disponibles: {tables}")
    
    if 'posts' not in tables:
        print("Pas de table 'posts' trouvée")
        return
    
    # Récupérer tous les posts
    cur.execute("SELECT * FROM posts")
    posts = cur.fetchall()
    print(f"\nNombre total de posts: {len(posts)}")
    
    if len(posts) == 0:
        print("Aucun post à analyser")
        return
    
    # Analyser chaque post
    results = {
        'valid': [],
        'invalid': []
    }
    exclusion_reasons = Counter()
    
    for post in posts:
        post_dict = dict(post)
        text = post_dict.get('text', '') or ''
        
        result = is_legal_job_post(text, log_exclusions=False)
        
        post_info = {
            'id': post_dict.get('id', 'N/A'),
            'author': post_dict.get('author', 'N/A'),
            'text_preview': text[:150] + '...' if len(text) > 150 else text,
            'is_valid': result.is_valid,
            'legal_score': result.legal_score,
            'recruitment_score': result.recruitment_score,
            'exclusion_reason': result.exclusion_reason,
            'matched_professions': result.matched_professions,
            'matched_signals': result.matched_signals
        }
        
        if result.is_valid:
            results['valid'].append(post_info)
        else:
            results['invalid'].append(post_info)
            if result.exclusion_reason:
                exclusion_reasons[result.exclusion_reason] += 1
    
    # Afficher les résultats
    print("\n" + "="*80)
    print("RÉSULTATS DE L'ANALYSE")
    print("="*80)
    
    print(f"\n✅ Posts VALIDES: {len(results['valid'])}")
    print(f"❌ Posts INVALIDES: {len(results['invalid'])}")
    
    if len(posts) > 0:
        print(f"\n📊 Taux de pertinence: {len(results['valid'])/len(posts)*100:.1f}%")
    
    print("\n" + "-"*40)
    print("RAISONS D'EXCLUSION:")
    print("-"*40)
    for reason, count in exclusion_reasons.most_common():
        print(f"  {reason}: {count}")
    
    # Afficher quelques exemples de posts valides
    print("\n" + "-"*40)
    print("EXEMPLES DE POSTS VALIDES:")
    print("-"*40)
    for post in results['valid'][:5]:
        print(f"\n📝 {post['author']}")
        print(f"   Texte: {post['text_preview']}")
        print(f"   Scores: legal={post['legal_score']:.2f}, recruit={post['recruitment_score']:.2f}")
        print(f"   Professions: {post['matched_professions']}")
        print(f"   Signaux: {post['matched_signals']}")
    
    # Afficher quelques exemples de posts invalides
    print("\n" + "-"*40)
    print("EXEMPLES DE POSTS INVALIDES:")
    print("-"*40)
    for post in results['invalid'][:5]:
        print(f"\n❌ {post['author']}")
        print(f"   Texte: {post['text_preview']}")
        print(f"   Raison: {post['exclusion_reason']}")
        if post['legal_score'] > 0 or post['recruitment_score'] > 0:
            print(f"   Scores: legal={post['legal_score']:.2f}, recruit={post['recruitment_score']:.2f}")
    
    conn.close()
    return results

if __name__ == "__main__":
    analyze_posts()
