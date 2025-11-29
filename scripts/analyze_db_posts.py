#!/usr/bin/env python3
"""
Analyse les posts dans la base SQLite et applique le filtre legal_filter.
Affiche les statistiques avant/après filtrage.

Usage:
    python scripts/analyze_db_posts.py
"""
from __future__ import annotations

import os
import sys
import sqlite3
from pathlib import Path

# Ajoute le répertoire racine au path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.legal_filter import is_legal_job_post
from datetime import datetime


def parse_date(date_str):
    """Parse une date ISO string en datetime ou None."""
    if not date_str:
        return None
    try:
        # Essaie plusieurs formats
        for fmt in ["%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
            try:
                return datetime.strptime(date_str.replace("Z", "+00:00"), fmt)
            except ValueError:
                continue
        return None
    except Exception:
        return None


def main():
    # Cherche la base SQLite
    db_path = Path(PROJECT_ROOT) / "fallback.sqlite3"
    
    if not db_path.exists():
        print(f"Base de données non trouvée: {db_path}")
        print("Exécutez d'abord le scraper pour collecter des posts.")
        return
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    # Récupère tous les posts
    cursor = conn.execute("SELECT * FROM posts ORDER BY collected_at DESC")
    posts = cursor.fetchall()
    
    if not posts:
        print("Aucun post trouvé dans la base de données.")
        return
    
    print("=" * 70)
    print(f"ANALYSE DES {len(posts)} POSTS AVEC LE FILTRE legal_filter")
    print("=" * 70)
    
    valid_posts = []
    invalid_posts = []
    exclusion_reasons = {}
    
    for post in posts:
        text = post['text'] or ""
        published_at = parse_date(post['published_at'])
        
        result = is_legal_job_post(text, published_at, log_exclusions=False)
        
        post_data = {
            'id': post['id'],
            'author': post['author'],
            'keyword': post['keyword'],
            'text': text[:100] + "..." if len(text) > 100 else text,
            'result': result
        }
        
        if result.is_valid:
            valid_posts.append(post_data)
        else:
            invalid_posts.append(post_data)
            reason = result.exclusion_reason or "score_insuffisant"
            exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1
    
    # Statistiques
    total = len(posts)
    valid_count = len(valid_posts)
    invalid_count = len(invalid_posts)
    filter_rate = (invalid_count / total * 100) if total > 0 else 0
    
    print(f"\n### RÉSUMÉ ###")
    print(f"Total posts analysés: {total}")
    print(f"Posts VALIDES (à conserver): {valid_count}")
    print(f"Posts INVALIDES (à exclure): {invalid_count}")
    print(f"Taux de filtrage: {filter_rate:.1f}%")
    
    print(f"\n### RAISONS D'EXCLUSION ###")
    for reason, count in sorted(exclusion_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")
    
    # Affiche les posts valides
    print("\n" + "=" * 70)
    print(f"### POSTS VALIDES ({valid_count}) - À CONSERVER ###")
    print("=" * 70)
    
    for i, post in enumerate(valid_posts[:20], 1):  # Limite à 20
        r = post['result']
        print(f"\n[{i}] {post['author']}")
        print(f"    Keyword: {post['keyword']}")
        print(f"    Scores: legal={r.legal_score:.2f}, recruit={r.recruitment_score:.2f}")
        print(f"    Professions: {r.matched_professions}")
        print(f"    Signaux: {r.matched_signals}")
        print(f"    Texte: {post['text']}")
    
    if len(valid_posts) > 20:
        print(f"\n... et {len(valid_posts) - 20} autres posts valides")
    
    # Affiche quelques posts invalides
    print("\n" + "=" * 70)
    print(f"### EXEMPLES DE POSTS INVALIDES ({invalid_count}) ###")
    print("=" * 70)
    
    for i, post in enumerate(invalid_posts[:10], 1):  # Limite à 10
        r = post['result']
        print(f"\n[{i}] {post['author']}")
        print(f"    Keyword: {post['keyword']}")
        print(f"    Raison: {r.exclusion_reason}")
        if r.exclusion_terms:
            print(f"    Termes: {r.exclusion_terms}")
        print(f"    Texte: {post['text']}")
    
    conn.close()


if __name__ == "__main__":
    main()
