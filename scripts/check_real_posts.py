#!/usr/bin/env python3
"""Check real posts in database."""
import sqlite3
import os

def main():
    db_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'TitanScraper', 'fallback.sqlite3')
    conn = sqlite3.connect(db_path)
    
    print("📊 STATS BASE DE DONNÉES")
    print("=" * 80)
    total = conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
    print(f"Total posts: {total}")
    
    # Posts réels (pas demo_recruteur)
    real = conn.execute("SELECT COUNT(*) FROM posts WHERE author != 'demo_recruteur'").fetchone()[0]
    print(f"Posts réels (hors démo): {real}")
    
    print()
    print("📋 10 DERNIERS POSTS RÉELS:")
    print("=" * 80)
    
    for row in conn.execute('''
        SELECT id, author, company, text, collected_at, permalink, keyword
        FROM posts 
        WHERE author != 'demo_recruteur'
        ORDER BY collected_at DESC 
        LIMIT 10
    '''):
        post_id = row[0][:16] if row[0] else 'N/A'
        author = (row[1] or 'N/A')[:40]
        company = row[2] or 'N/A'
        text = (row[3] or '')[:70]
        collected = row[4] or 'N/A'
        keyword = row[6] or 'N/A'
        
        print(f"ID: {post_id}")
        print(f"  👤 Auteur: {author}")
        print(f"  🏢 Entreprise: {company}")
        print(f"  📝 Texte: {text}...")
        print(f"  📅 Collecté: {collected}")
        print(f"  🔑 Mot-clé: {keyword}")
        print("-" * 40)
    
    # Stats par mot-clé
    print()
    print("📈 POSTS PAR MOT-CLÉ:")
    print("-" * 40)
    for row in conn.execute('''
        SELECT keyword, COUNT(*) as count
        FROM posts 
        WHERE author != 'demo_recruteur'
        GROUP BY keyword
        ORDER BY count DESC
        LIMIT 10
    '''):
        print(f"  {row[0]}: {row[1]} posts")
    
    conn.close()
    print("\n✅ Vérification terminée")

if __name__ == "__main__":
    main()
