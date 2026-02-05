#!/usr/bin/env python3
"""Check posts database and display recent entries."""
import sqlite3
import os
import json
from datetime import datetime

def main():
    base_dir = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'TitanScraper')
    
    # Check fallback.sqlite3 (main posts DB)
    db_path = os.path.join(base_dir, 'fallback.sqlite3')
    print(f"DB Path: {db_path}")
    print(f"Exists: {os.path.exists(db_path)}")
    
    # Also check last_scraper_output.json
    output_path = os.path.join(base_dir, 'last_scraper_output.json')
    if os.path.exists(output_path):
        print(f"\n📄 DERNIÈRE SORTIE SCRAPER:")
        print("=" * 60)
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'posts' in data:
                print(f"Posts dans le dernier scrape: {len(data['posts'])}")
                for i, post in enumerate(data['posts'][:5], 1):
                    print(f"\n  [{i}] {post.get('author', 'N/A')[:40]}")
                    print(f"      {post.get('company', 'N/A')}")
                    print(f"      {(post.get('text', '') or '')[:80]}...")
    
    if not os.path.exists(db_path):
        print("❌ Base de données non trouvée")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Stats générales
    total = conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
    print(f"\n📊 TOTAL POSTS EN BASE: {total}")
    
    # Posts récents (24h)
    recent = conn.execute('''
        SELECT COUNT(*) FROM posts 
        WHERE scraped_at > datetime('now', '-1 day')
    ''').fetchone()[0]
    print(f"📅 Posts dernières 24h: {recent}")
    
    # Posts aujourd'hui
    today = conn.execute('''
        SELECT COUNT(*) FROM posts 
        WHERE date(scraped_at) = date('now')
    ''').fetchone()[0]
    print(f"📅 Posts aujourd'hui: {today}")
    
    # Derniers posts
    print(f"\n📋 10 DERNIERS POSTS ENREGISTRÉS:")
    print("=" * 80)
    
    for row in conn.execute('''
        SELECT id, author, company, title, scraped_at, permalink
        FROM posts 
        ORDER BY scraped_at DESC 
        LIMIT 10
    '''):
        author = (row['author'] or 'N/A')[:35]
        company = row['company'] or 'N/A'
        title = (row['title'] or '')[:65]
        date = row['scraped_at']
        link = (row['permalink'] or '')[:50]
        
        print(f"ID {row['id']:4d} | {date}")
        print(f"  👤 {author}")
        print(f"  🏢 {company}")
        print(f"  📝 {title}...")
        print(f"  🔗 {link}...")
        print("-" * 40)
    
    # Stats par jour
    print("\n📈 POSTS PAR JOUR (7 derniers jours):")
    print("-" * 40)
    for row in conn.execute('''
        SELECT date(scraped_at) as day, COUNT(*) as count
        FROM posts 
        WHERE scraped_at > datetime('now', '-7 days')
        GROUP BY day
        ORDER BY day DESC
    '''):
        print(f"  {row['day']}: {row['count']} posts")
    
    conn.close()
    print("\n✅ Vérification terminée")

if __name__ == "__main__":
    main()
