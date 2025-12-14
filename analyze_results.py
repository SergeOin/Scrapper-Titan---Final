#!/usr/bin/env python3
"""Analyse des résultats du scraping."""
import sqlite3
from pathlib import Path
from datetime import datetime

# Chemins possibles pour la base de données
DB_PATHS = [
    Path(r'C:\Users\plogr\AppData\Local\TitanScraper\fallback.sqlite3'),
    Path('fallback.sqlite3'),
    Path('dev_test.sqlite3'),
]

def find_db():
    for p in DB_PATHS:
        if p.exists():
            return p
    return None

def main():
    db_path = find_db()
    if not db_path:
        print("❌ Aucune base de données trouvée")
        print("Chemins vérifiés:", [str(p) for p in DB_PATHS])
        return
    
    print(f"📁 Base de données: {db_path}")
    print(f"📊 Taille: {db_path.stat().st_size / 1024:.1f} KB")
    print()
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    # Lister les tables
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r['name'] for r in cursor.fetchall()]
    print(f"📋 Tables: {tables}")
    print()
    
    if 'posts' not in tables:
        print("⚠️ Table 'posts' non trouvée")
        conn.close()
        return
    
    # Compter les posts
    cursor = conn.execute('SELECT COUNT(*) as count FROM posts')
    count = cursor.fetchone()['count']
    print(f"✅ TOTAL POSTS COLLECTÉS: {count}")
    print()
    
    # Stats par auteur/entreprise
    cursor = conn.execute('''
        SELECT company, COUNT(*) as cnt 
        FROM posts 
        WHERE company IS NOT NULL AND company != ''
        GROUP BY company 
        ORDER BY cnt DESC 
        LIMIT 10
    ''')
    print("🏢 TOP 10 ENTREPRISES:")
    for row in cursor:
        print(f"   - {row['company']}: {row['cnt']} posts")
    print()
    
    # 5 derniers posts
    cursor = conn.execute('''
        SELECT post_id, author, company, text, collected_at 
        FROM posts 
        ORDER BY collected_at DESC 
        LIMIT 5
    ''')
    print("📝 5 DERNIERS POSTS:")
    print("-" * 60)
    for row in cursor:
        text = (row['text'] or '')[:150]
        if row['text'] and len(row['text']) > 150:
            text += '...'
        print(f"Auteur: {row['author'] or 'N/A'}")
        print(f"Entreprise: {row['company'] or 'N/A'}")
        print(f"Texte: {text}")
        print(f"Collecté: {row['collected_at']}")
        print("-" * 60)
    
    conn.close()
    print("\n✅ Analyse terminée")

if __name__ == "__main__":
    main()
