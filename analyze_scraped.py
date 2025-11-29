#!/usr/bin/env python3
"""Analyse des posts scrappés avec le filtre légal."""

import sqlite3
import json

from scraper import is_legal_job_post, FilterSessionStats

def main():
    conn = sqlite3.connect('fallback.sqlite3')
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, author, company, text, keyword, collected_at FROM posts ORDER BY collected_at DESC')
    posts = cursor.fetchall()
    
    print(f"\n📊 ANALYSE DES {len(posts)} POSTS SCRAPPÉS")
    print("=" * 80)
    
    stats = FilterSessionStats()
    valid_posts = []
    invalid_posts = []
    
    for i, (post_id, author, company, text, keyword, collected_at) in enumerate(posts, 1):
        result = is_legal_job_post(text or '', log_exclusions=False)
        stats.record_result(result)
        
        post_info = {
            'num': i,
            'author': author or '?',
            'company': company or '-',
            'keyword': keyword or '-',
            'text_preview': (text or '')[:200].replace('\n', ' '),
            'recruitment_score': result.recruitment_score,
            'legal_score': result.legal_score,
            'exclusion_reason': result.exclusion_reason,
        }
        
        if result.is_valid:
            valid_posts.append(post_info)
        else:
            invalid_posts.append(post_info)
    
    # Afficher les posts VALIDES
    print(f"\n✅ POSTS VALIDES ({len(valid_posts)}/{len(posts)})")
    print("-" * 80)
    for p in valid_posts:
        print(f"\n#{p['num']} | {p['author'][:40]}")
        print(f"   Entreprise: {p['company'][:50]}")
        print(f"   Mot-clé: {p['keyword']}")
        print(f"   Scores: recrutement={p['recruitment_score']:.2f}, juridique={p['legal_score']:.2f}")
        print(f"   Texte: {p['text_preview'][:150]}...")
    
    # Afficher les posts INVALIDES
    if invalid_posts:
        print(f"\n\n❌ POSTS INVALIDES ({len(invalid_posts)}/{len(posts)})")
        print("-" * 80)
        for p in invalid_posts:
            print(f"\n#{p['num']} | {p['author'][:40]}")
            print(f"   Entreprise: {p['company'][:50]}")
            print(f"   Raison: {p['exclusion_reason']}")
            print(f"   Scores: recrutement={p['recruitment_score']:.2f}, juridique={p['legal_score']:.2f}")
            print(f"   Texte: {p['text_preview'][:100]}...")
    
    # Résumé
    print("\n\n" + "=" * 80)
    print(stats.summary())
    
    # Statistiques détaillées
    print("\n\n📈 STATISTIQUES DÉTAILLÉES")
    print("-" * 40)
    details = stats.to_dict()
    print(f"Taux d'acceptation: {details['acceptance_rate_percent']}%")
    print(f"Score moyen recrutement: {details['avg_recruitment_score']:.3f}")
    print(f"Score moyen juridique: {details['avg_legal_score']:.3f}")
    
    print("\nRejets par catégorie:")
    for reason, count in details['rejections'].items():
        if count > 0:
            print(f"  - {reason}: {count}")
    
    conn.close()

if __name__ == '__main__':
    main()
