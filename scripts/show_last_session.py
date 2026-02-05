#!/usr/bin/env python3
"""Display last scraper session results."""
import json
import os

def main():
    output_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'TitanScraper', 'last_scraper_output.json')
    print(f"Fichier: {output_path}")
    
    with open(output_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"Clés: {list(data.keys())}")
    print()
    
    if 'posts' in data:
        posts = data['posts']
        print(f"📊 POSTS COLLECTÉS CETTE SESSION: {len(posts)}")
        print("=" * 80)
        
        for i, post in enumerate(posts, 1):
            author = post.get('author', 'N/A')
            company = post.get('company', 'N/A')
            text = (post.get('text', '') or '')[:100]
            lang = post.get('language', 'N/A')
            link = (post.get('permalink', '') or '')[:60]
            
            print(f"[{i}] {author}")
            print(f"    Entreprise: {company}")
            print(f"    Texte: {text}...")
            print(f"    Langue: {lang}")
            print(f"    Permalink: {link}...")
            print("-" * 40)
    
    if 'stats' in data:
        print()
        print("📈 STATISTIQUES DE LA SESSION:")
        for k, v in data['stats'].items():
            print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
