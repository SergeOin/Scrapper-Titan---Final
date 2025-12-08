"""
AUDIT COMPLET DES POSTS SCRAPPÉS - Critères Titan Partners
===========================================================
"""
import asyncio
import json
import sys
import os
from datetime import datetime, timezone, timedelta

# Add project to path
sys.path.insert(0, r'C:\Users\plogr\Desktop\Scrapper-Titan---Final')

from scraper.scrape_subprocess import (
    scrape_keywords, 
    filter_post_titan_partners, 
    classify_author_type,
    is_post_too_old,
    has_legal_keywords,
    is_external_recruitment,
    is_jobseeker_post,
    EXCLUSION_AGENCIES,
    LEGAL_KEYWORDS,
    MAX_POST_AGE_DAYS
)

# Configuration
STORAGE_STATE = os.path.join(os.environ.get('LOCALAPPDATA', '.'), 'TitanScraper', 'storage_state.json')
BROWSERS_PATH = os.path.join(os.environ.get('LOCALAPPDATA', '.'), 'ms-playwright')

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = BROWSERS_PATH

async def run_audit():
    print("=" * 70)
    print("AUDIT COMPLET DES POSTS - CRITÈRES TITAN PARTNERS")
    print("=" * 70)
    print()
    
    # Keywords to test
    keywords = [
        "recrutement juriste",
        "avocat CDI", 
        "legal counsel France",
        "compliance officer recrutement",
    ]
    
    print(f"Mots-clés testés: {keywords}")
    print(f"Storage state: {STORAGE_STATE}")
    print()
    print("Scraping en cours...")
    
    # Run scraping WITHOUT filter to get all raw posts
    result = await scrape_keywords(
        keywords=keywords,
        storage_state=STORAGE_STATE,
        max_per_keyword=10,
        headless=True,
        apply_titan_filter=False  # Get ALL posts first
    )
    
    if not result.get('success'):
        print(f"ERREUR: {result.get('errors')}")
        return
    
    raw_posts = result.get('posts', [])
    print(f"\nPosts bruts collectés: {len(raw_posts)}")
    print()
    
    # Audit each post
    audit_results = {
        'total': len(raw_posts),
        'passed': 0,
        'failed': {
            'agency': [],
            'external_recruitment': [],
            'jobseeker': [],
            'no_legal_keywords': [],
            'too_old': [],
            'invalid_url': [],
        }
    }
    
    passed_posts = []
    
    print("=" * 70)
    print("ANALYSE DÉTAILLÉE DE CHAQUE POST")
    print("=" * 70)
    
    for i, post in enumerate(raw_posts, 1):
        author = post.get('author', 'Unknown')
        company = post.get('company', '')
        text = post.get('text', '')[:200]
        published_at = post.get('published_at', '')
        permalink = post.get('permalink', '')
        author_profile = post.get('author_profile', '')
        
        print(f"\n--- POST {i} ---")
        print(f"Auteur: {author}")
        print(f"Entreprise: {company or 'N/A'}")
        print(f"Date: {published_at[:10] if published_at else 'N/A'}")
        print(f"Lien: {permalink or 'N/A'}")
        print(f"Texte: {text[:100]}...")
        
        # Run all checks
        author_type = classify_author_type(author, author_profile, company)
        is_agency = author_type == 'agency'
        is_external = is_external_recruitment(post.get('text', ''))
        is_seeker = is_jobseeker_post(post.get('text', ''))
        has_legal = has_legal_keywords(post.get('text', ''))
        is_old = is_post_too_old(published_at)
        has_valid_url = permalink and 'linkedin.com' in permalink
        
        # Print checks
        print(f"\n  VÉRIFICATIONS:")
        print(f"  [{'✅' if author_type in ('company', 'unknown') else '❌'}] Type auteur: {author_type}")
        print(f"  [{'❌' if is_agency else '✅'}] Pas une agence: {'NON' if is_agency else 'OUI'}")
        print(f"  [{'❌' if is_external else '✅'}] Recrutement interne: {'NON (externe)' if is_external else 'OUI'}")
        print(f"  [{'❌' if is_seeker else '✅'}] Pas chercheur emploi: {'NON' if is_seeker else 'OUI'}")
        print(f"  [{'✅' if has_legal else '❌'}] Mots-clés juridiques: {'OUI' if has_legal else 'NON'}")
        print(f"  [{'❌' if is_old else '✅'}] Date < 3 semaines: {'NON' if is_old else 'OUI'}")
        print(f"  [{'✅' if has_valid_url else '❌'}] URL valide: {'OUI' if has_valid_url else 'NON'}")
        
        # Apply filter
        is_valid, reason = filter_post_titan_partners(post)
        
        if is_valid:
            audit_results['passed'] += 1
            passed_posts.append(post)
            print(f"\n  ✅ RÉSULTAT: ACCEPTÉ")
        else:
            print(f"\n  ❌ RÉSULTAT: REJETÉ - {reason}")
            if 'AGENCY' in reason:
                audit_results['failed']['agency'].append(author)
            elif 'EXTERNAL' in reason:
                audit_results['failed']['external_recruitment'].append(author)
            elif 'JOBSEEKER' in reason:
                audit_results['failed']['jobseeker'].append(author)
            elif 'NO_LEGAL' in reason:
                audit_results['failed']['no_legal_keywords'].append(author)
            elif 'TOO_OLD' in reason:
                audit_results['failed']['too_old'].append(author)
        
        if not has_valid_url:
            audit_results['failed']['invalid_url'].append(author)
    
    # Summary
    print()
    print("=" * 70)
    print("RÉSUMÉ DE L'AUDIT")
    print("=" * 70)
    print(f"\nTotal posts analysés: {audit_results['total']}")
    print(f"✅ Posts ACCEPTÉS: {audit_results['passed']} ({audit_results['passed']/max(audit_results['total'],1)*100:.1f}%)")
    print()
    print("❌ Posts REJETÉS par catégorie:")
    print(f"   - Agences/Job boards: {len(audit_results['failed']['agency'])}")
    print(f"   - Recrutement externe: {len(audit_results['failed']['external_recruitment'])}")
    print(f"   - Chercheurs d'emploi: {len(audit_results['failed']['jobseeker'])}")
    print(f"   - Sans mots-clés juridiques: {len(audit_results['failed']['no_legal_keywords'])}")
    print(f"   - Trop vieux (>{MAX_POST_AGE_DAYS}j): {len(audit_results['failed']['too_old'])}")
    print(f"   - URL invalide: {len(audit_results['failed']['invalid_url'])}")
    
    print()
    print("=" * 70)
    print("POSTS CONFORMES TITAN PARTNERS")
    print("=" * 70)
    for post in passed_posts[:10]:
        print(f"\n• {post.get('author')}")
        print(f"  Entreprise: {post.get('company') or 'N/A'}")
        print(f"  Date: {post.get('published_at', '')[:10]}")
        print(f"  Lien: {post.get('permalink', 'N/A')}")
        print(f"  Texte: {post.get('text', '')[:80]}...")
    
    print()
    print("=" * 70)
    print("CONFIGURATION ACTUELLE")
    print("=" * 70)
    print(f"\nAgences exclues: {EXCLUSION_AGENCIES[:10]}...")
    print(f"\nMots-clés juridiques: {LEGAL_KEYWORDS}")
    print(f"\nDurée max posts: {MAX_POST_AGE_DAYS} jours")

if __name__ == "__main__":
    asyncio.run(run_audit())
