#!/usr/bin/env python3
"""Test script for real LinkedIn scraping with debug."""
import asyncio
import os
import sys

# Set environment
os.environ["PLAYWRIGHT_MOCK_MODE"] = "0"
os.environ["DISABLE_REDIS"] = "1"
os.environ["TITAN_ENABLE_ALL"] = "1"  # Enable all new modules

sys.path.insert(0, ".")

from scraper.scrape_subprocess import scrape_keywords, is_french_post, filter_post_titan_partners

def test_filters_directly():
    """Test the filters directly on sample posts."""
    print("\n=== TESTING FILTERS DIRECTLY ===")
    
    test_posts = [
        {
            "author": "Karen Pichon",
            "text": "Cher réseau, Le Mans Métropole Habitat recrute un(e) juriste immobilier en CDI. Intéressé(e) ou connaissez quelqu'un ?",
            "published_at": "2026-01-15T10:00:00",
        },
        {
            "author": "Cerfrance Aveyron",
            "text": "Cerfrance Aveyron recrute ! 1 JURISTE EN DROIT DES AFFAIRES (h/f) 1 CONSEILLER SPECIALISE EN GESTION",
            "published_at": "2026-01-10T10:00:00",
        },
        {
            "author": "Law Profiler",
            "text": "Candidat(e)s – Vous êtes en recherche active ou à l'écoute d'une nouvelle opportunité ? CDD, CDI",
            "published_at": "2026-01-18T10:00:00",
        },
    ]
    
    for i, post in enumerate(test_posts):
        print(f"\n--- Test Post {i+1}: {post['author']} ---")
        print(f"  Text: {post['text'][:80]}...")
        
        # Test French
        is_fr = is_french_post(post['text'])
        print(f"  is_french_post: {is_fr}")
        
        # Test Titan filter
        is_valid, reason = filter_post_titan_partners(post)
        print(f"  filter_post_titan_partners: valid={is_valid}, reason={reason}")


async def test_real_scrape():
    """Test real scraping with French keywords."""
    storage_state_path = os.path.join(
        os.environ.get("LOCALAPPDATA", "."), 
        "TitanScraper", 
        "storage_state.json"
    )
    
    if not os.path.exists(storage_state_path):
        print(f"ERROR: storage_state.json not found at {storage_state_path}")
        return
    
    print(f"Using storage_state: {storage_state_path}")
    print("Starting real scrape test with French keywords...")
    
    result = await scrape_keywords(
        keywords=["recrute juriste CDI"],
        storage_state=storage_state_path,
        max_per_keyword=10,
        headless=True,
        apply_titan_filter=True
    )
    
    print(f"\n=== RESULTS ===")
    print(f"Success: {result.get('success', False)}")
    print(f"Posts accepted: {len(result.get('posts', []))}")
    print(f"Stats: {result.get('stats', {})}")
    
    for i, post in enumerate(result.get("posts", [])[:3]):
        author = post.get('author', 'N/A')
        text = post.get('text', 'N/A')
        print(f"\n--- Post {i+1} ---")
        print(f"  Author: {author[:50] if author else 'N/A'}")
        print(f"  Text: {text[:100] if text else 'N/A'}...")
    
    return result

if __name__ == "__main__":
    # First test filters directly
    test_filters_directly()
    
    # Then test real scraping
    print("\n" + "="*60)
    result = asyncio.run(test_real_scrape())
