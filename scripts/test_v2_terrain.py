#!/usr/bin/env python3
"""Test terrain minimal pour Titan Scraper v2.

Ce script effectue un test RÉEL avec LinkedIn mais avec des quotas très bas
pour valider le flux complet v2 sans risquer de sur-extraction.

IMPORTANT: Nécessite une session LinkedIn valide (storage_state.json)

Usage:
    # Mode dry-run (simulation sans vraie requête LinkedIn)
    python scripts/test_v2_terrain.py --dry-run

    # Test réel avec 2 posts max
    python scripts/test_v2_terrain.py --quota 2

    # Test réel avec entreprise spécifique
    python scripts/test_v2_terrain.py --company "Bredin Prat" --quota 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force v2 mode
os.environ["TITAN_ENABLE_V2"] = "1"


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def print_section(title: str):
    """Print a section header."""
    print(f"\n--- {title} ---")


def test_prequal_with_real_samples():
    """Test pre-qualification with realistic LinkedIn post samples."""
    print_section("Test pré-qualification avec échantillons réalistes")
    
    from scraper.pre_qualifier import pre_qualify_post, PreQualificationMetrics
    
    # Realistic test samples
    samples = [
        # Should ACCEPT
        {
            "text": "🚀 Nous recrutons un Juriste M&A (H/F) pour rejoindre notre équipe à Paris. CDI. Expérience 3-5 ans en droit des sociétés. Candidature: recrutement@cabinet.fr",
            "author": "Cabinet Bredin Prat",
            "expected": True,
            "reason": "Recrutement juridique direct",
        },
        {
            "text": "Notre cabinet recherche un avocat collaborateur en droit social. Poste basé à Lyon. Rejoignez une équipe dynamique!",
            "author": "Fidal Lyon",
            "expected": True,
            "reason": "Avocat droit social",
        },
        {
            "text": "Offre d'emploi: Directeur Juridique Groupe. Mission: piloter la stratégie juridique, M&A, compliance. Paris La Défense.",
            "author": "LVMH",
            "expected": True,
            "reason": "Direction juridique corporate",
        },
        # Should REJECT
        {
            "text": "📢 Stage de fin d'études - Juriste droit des affaires. 6 mois à partir de septembre. Gratification légale.",
            "author": "Some Company",
            "expected": False,
            "reason": "Stage (exclusion)",
        },
        {
            "text": "Nous recrutons pour notre client, un grand cabinet d'avocats, un associé corporate M&A.",
            "author": "Michael Page Legal",
            "expected": False,
            "reason": "Agence de recrutement",
        },
        {
            "text": "Alternance droit des contrats - 24 mois. Vous préparez un Master 2 en droit des affaires.",
            "author": "BNP Paribas",
            "expected": False,
            "reason": "Alternance (exclusion)",
        },
        {
            "text": "🎉 Bienvenue à Marie qui rejoint notre équipe juridique! Nous sommes ravis de l'accueillir.",
            "author": "Société Générale",
            "expected": False,
            "reason": "Non-recrutement (welcome post)",
        },
        {
            "text": "Seeking a Senior Legal Counsel for our London office. 7+ years experience in M&A required.",
            "author": "Clifford Chance",
            "expected": False,
            "reason": "Poste à l'étranger (London)",
        },
        {
            "text": "#OpenToWork Je recherche un poste de juriste contrats. 5 ans d'expérience. Disponible immédiatement.",
            "author": "Jean Dupont",
            "expected": False,
            "reason": "Demandeur d'emploi",
        },
    ]
    
    metrics = PreQualificationMetrics()
    passed = 0
    failed = 0
    
    for sample in samples:
        result = pre_qualify_post(
            preview_text=sample["text"][:300],
            author_name=sample["author"],
        )
        metrics.record(result)
        
        correct = result.should_extract == sample["expected"]
        status = "✓" if correct else "✗"
        
        if correct:
            passed += 1
        else:
            failed += 1
        
        expected_str = "ACCEPT" if sample["expected"] else "REJECT"
        actual_str = "ACCEPT" if result.should_extract else "REJECT"
        
        print(f"  {status} [{expected_str}→{actual_str}] {sample['author'][:25]:<25} | {sample['reason']}")
        if not correct:
            print(f"      Détail: {result.reason}")
    
    print(f"\nRésultats: {passed}/{len(samples)} corrects")
    
    stats = metrics.to_dict()
    print(f"\nMétriques pré-qualification:")
    print(f"  - Total vérifié: {stats['total_checked']}")
    print(f"  - Acceptés: {stats['accepted']}")
    print(f"  - Rejetés: {stats['total_checked'] - stats['accepted']}")
    print(f"  - Taux de rejet: {stats['rejection_rate']:.1%}")
    print(f"  - Économie estimée: {stats['savings_estimate']:.1%}")
    
    return passed == len(samples)


def test_whitelist_for_session():
    """Test que la whitelist retourne des entreprises pour une session."""
    print_section("Test whitelist pour session")
    
    from scraper.company_whitelist import get_company_whitelist
    
    whitelist = get_company_whitelist()
    
    # Test différents types de sessions
    session_types = ["tier1_check", "tier2_check", "exploration", "default"]
    
    for session_type in session_types:
        companies = whitelist.get_companies_for_session(session_type, max_companies=3)
        print(f"  {session_type}: {len(companies)} entreprises")
        for c in companies[:2]:
            print(f"    - {c.name} (Tier {c.tier})")
    
    stats = whitelist.get_stats()
    print(f"\nStats whitelist:")
    print(f"  - Total: {stats['total_companies']}")
    print(f"  - À visiter: {stats['due_for_visit']}")
    
    return True


def test_session_orchestrator_status():
    """Test l'état actuel du session orchestrator."""
    print_section("État du Session Orchestrator")
    
    from scraper.session_orchestrator import get_session_orchestrator
    
    orchestrator = get_session_orchestrator()
    
    can_scrape, reason = orchestrator.should_scrape_now()
    print(f"  Peut scraper maintenant: {can_scrape} ({reason})")
    
    stats = orchestrator.get_daily_stats()
    print(f"  Quota journalier: {stats['quota_target']}")
    print(f"  Posts qualifiés aujourd'hui: {stats['posts_qualified']}")
    print(f"  Sessions complétées: {stats['sessions_completed']}")
    
    wait = orchestrator.get_wait_seconds()
    print(f"  Attente prochaine session: {wait}s ({wait // 60}m)")
    
    quota = orchestrator.get_session_quota()
    print(f"  Quota session actuelle: {quota}")
    
    return True


def simulate_scrape_flow(quota: int = 3, dry_run: bool = True):
    """Simulate le flux de scraping complet avec pré-qualification.
    
    Args:
        quota: Nombre max de posts à accepter
        dry_run: Si True, simule sans vraie requête LinkedIn
    """
    print_section(f"Simulation flux scraping (quota={quota}, dry_run={dry_run})")
    
    from scraper.pre_qualifier import pre_qualify_post, PreQualificationMetrics
    from scraper.session_orchestrator import get_session_orchestrator
    from scraper.company_whitelist import get_company_whitelist
    
    # Simulated posts that would come from LinkedIn
    simulated_raw_posts = [
        {"author": "Michael Page Legal", "text": "Notre client, un cabinet leader, recrute...", "preview": "Notre client recrute"},
        {"author": "Bredin Prat", "text": "Nous recherchons un collaborateur corporate M&A pour notre bureau de Paris...", "preview": "Nous recherchons un collaborateur"},
        {"author": "Random Person", "text": "Stage 6 mois en droit bancaire à partir de mars...", "preview": "Stage 6 mois"},
        {"author": "Gide Loyrette", "text": "Offre CDI: Juriste droit des sociétés expérimenté. 5 ans minimum...", "preview": "Offre CDI Juriste"},
        {"author": "Jean Martin", "text": "#OpenToWork Juriste disponible immédiatement...", "preview": "#OpenToWork"},
        {"author": "Clifford Chance Paris", "text": "Recrutement: Avocat fiscaliste senior pour notre équipe M&A à Paris...", "preview": "Recrutement Avocat"},
        {"author": "LVMH Legal", "text": "Direction juridique: poste de Responsable Contrats Groupe...", "preview": "Direction juridique"},
        {"author": "Hays Legal", "text": "Urgent: notre client recherche un directeur juridique...", "preview": "notre client recherche"},
    ]
    
    metrics = PreQualificationMetrics()
    accepted_posts = []
    rejected_posts = []
    
    print(f"\n  Traitement de {len(simulated_raw_posts)} posts simulés...")
    print()
    
    for i, post in enumerate(simulated_raw_posts, 1):
        # Phase 1: Pré-qualification
        result = pre_qualify_post(
            preview_text=post["preview"],
            author_name=post["author"],
        )
        metrics.record(result)
        
        if result.should_extract:
            if len(accepted_posts) < quota:
                accepted_posts.append(post)
                print(f"  [{i}] ✓ ACCEPT: {post['author'][:30]} (conf: {result.confidence:.2f})")
                
                # Early exit si quota atteint
                if len(accepted_posts) >= quota:
                    print(f"\n  ⚡ QUOTA ATTEINT ({quota} posts) - arrêt anticipé")
                    break
            else:
                print(f"  [{i}] ⊘ QUOTA FULL: {post['author'][:30]}")
        else:
            rejected_posts.append((post, result.reason))
            print(f"  [{i}] ✗ REJECT: {post['author'][:30]} → {result.reason}")
    
    print(f"\n  Résumé:")
    print(f"    - Posts traités: {metrics.to_dict()['total_checked']}")
    print(f"    - Acceptés: {len(accepted_posts)}")
    print(f"    - Rejetés par pré-qual: {len(rejected_posts)}")
    print(f"    - Quota utilisé: {len(accepted_posts)}/{quota}")
    
    if rejected_posts:
        print(f"\n  Détail rejets:")
        reasons = {}
        for post, reason in rejected_posts:
            reasons[reason] = reasons.get(reason, 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    - {reason}: {count}")
    
    return len(accepted_posts) <= quota


def run_real_scrape_test(quota: int = 2, keyword: str = "juriste recrutement"):
    """Lance un vrai test de scraping avec quota minimal.
    
    ATTENTION: Ceci fait une vraie requête LinkedIn!
    """
    print_section(f"TEST RÉEL LinkedIn (quota={quota})")
    
    storage_state_path = PROJECT_ROOT / "storage_state.json"
    
    if not storage_state_path.exists():
        print("  ❌ ERREUR: storage_state.json introuvable")
        print("     Vous devez d'abord vous connecter à LinkedIn via l'interface desktop.")
        return False
    
    print(f"  ✓ Session LinkedIn trouvée: {storage_state_path}")
    print(f"  Keyword: {keyword}")
    print(f"  Quota: {quota} posts max")
    
    # Préparer l'input pour scrape_subprocess
    input_data = {
        "keywords": [keyword],
        "storage_state": str(storage_state_path),
        "max_per_keyword": 10,
        "headless": True,
        "session_quota": quota,  # v2: Limite de session
    }
    
    print(f"\n  ⏳ Lancement du scraping (cela peut prendre 1-2 minutes)...")
    
    import subprocess
    import json
    
    # Créer fichiers temporaires pour I/O
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f_in:
        json.dump(input_data, f_in)
        input_file = f_in.name
    
    output_file = tempfile.mktemp(suffix='.json')
    
    try:
        # Lancer le subprocess
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scraper" / "scrape_subprocess.py"),
            "--input-file", input_file,
            "--output-file", output_file,
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,  # 3 minutes max
            cwd=str(PROJECT_ROOT),
        )
        
        if result.returncode != 0:
            print(f"  ❌ Erreur subprocess: {result.stderr[:500]}")
            return False
        
        # Lire les résultats
        with open(output_file, 'r', encoding='utf-8') as f:
            scrape_result = json.load(f)
        
        print(f"\n  Résultats:")
        print(f"    - Succès: {scrape_result.get('success', False)}")
        print(f"    - Posts extraits: {len(scrape_result.get('posts', []))}")
        print(f"    - Quota atteint: {scrape_result.get('session_quota_reached', False)}")
        
        stats = scrape_result.get('stats', {})
        if stats:
            print(f"\n  Statistiques:")
            print(f"    - Total scrapé: {stats.get('total_scraped', 0)}")
            print(f"    - Acceptés: {stats.get('accepted', 0)}")
            print(f"    - Rejetés agence: {stats.get('rejected_agency', 0)}")
            print(f"    - Rejetés externe: {stats.get('rejected_external', 0)}")
            print(f"    - Rejetés stage: {stats.get('rejected_contract_type', 0)}")
            print(f"    - Rejetés non-français: {stats.get('rejected_non_french', 0)}")
            print(f"    - Rejetés duplicate: {stats.get('rejected_duplicate', 0)}")
        
        if scrape_result.get('posts'):
            print(f"\n  Posts acceptés:")
            for i, post in enumerate(scrape_result['posts'][:5], 1):
                author = post.get('author', 'Unknown')[:30]
                text_preview = post.get('text', '')[:60]
                print(f"    {i}. {author}: {text_preview}...")
        
        if scrape_result.get('errors'):
            print(f"\n  Erreurs:")
            for err in scrape_result['errors'][:3]:
                print(f"    - {err[:100]}")
        
        return scrape_result.get('success', False)
        
    except subprocess.TimeoutExpired:
        print("  ❌ Timeout (>3 minutes)")
        return False
    except Exception as e:
        print(f"  ❌ Erreur: {e}")
        return False
    finally:
        # Cleanup
        if os.path.exists(input_file):
            os.unlink(input_file)
        if os.path.exists(output_file):
            os.unlink(output_file)


def main():
    parser = argparse.ArgumentParser(
        description="Test terrain minimal pour Titan Scraper v2"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode simulation sans vraie requête LinkedIn"
    )
    parser.add_argument(
        "--quota",
        type=int,
        default=2,
        help="Nombre max de posts à accepter (défaut: 2)"
    )
    parser.add_argument(
        "--keyword",
        type=str,
        default="juriste recrutement CDI",
        help="Mot-clé de recherche pour test réel"
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Lancer un vrai test LinkedIn (ATTENTION: requête réelle)"
    )
    
    args = parser.parse_args()
    
    print_header("TITAN SCRAPER V2 - TEST TERRAIN MINIMAL")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'DRY-RUN (simulation)' if args.dry_run or not args.real else 'RÉEL'}")
    print(f"Quota: {args.quota} posts max")
    
    all_passed = True
    
    # Test 1: Pré-qualification avec échantillons
    try:
        if not test_prequal_with_real_samples():
            print("\n  ⚠ Certains tests de pré-qualification ont échoué")
            all_passed = False
    except Exception as e:
        print(f"\n  ❌ Erreur test pré-qualification: {e}")
        all_passed = False
    
    # Test 2: Whitelist
    try:
        test_whitelist_for_session()
    except Exception as e:
        print(f"\n  ❌ Erreur test whitelist: {e}")
        all_passed = False
    
    # Test 3: Session orchestrator
    try:
        test_session_orchestrator_status()
    except Exception as e:
        print(f"\n  ❌ Erreur test orchestrator: {e}")
        all_passed = False
    
    # Test 4: Simulation du flux
    try:
        if not simulate_scrape_flow(quota=args.quota, dry_run=True):
            all_passed = False
    except Exception as e:
        print(f"\n  ❌ Erreur simulation flux: {e}")
        all_passed = False
    
    # Test 5: Test réel si demandé
    if args.real and not args.dry_run:
        print("\n" + "!" * 60)
        print(" ATTENTION: Lancement d'un test RÉEL LinkedIn")
        print(" Cela fera une vraie requête avec votre compte.")
        print("!" * 60)
        
        confirm = input("\nConfirmer? (oui/non): ").strip().lower()
        if confirm == "oui":
            try:
                if not run_real_scrape_test(quota=args.quota, keyword=args.keyword):
                    all_passed = False
            except Exception as e:
                print(f"\n  ❌ Erreur test réel: {e}")
                all_passed = False
        else:
            print("  Test réel annulé.")
    
    # Résumé final
    print_header("RÉSUMÉ")
    
    if all_passed:
        print("✅ Tous les tests ont réussi!")
        print("\nProchaines étapes recommandées:")
        print("  1. Lancer un test réel avec: python scripts/test_v2_terrain.py --real --quota 2")
        print("  2. Vérifier les logs dans %LOCALAPPDATA%\\TitanScraper\\scrape_subprocess_debug.txt")
        print("  3. Si OK, lancer une session complète avec TITAN_ENABLE_V2=1")
    else:
        print("⚠ Certains tests ont échoué - vérifiez les erreurs ci-dessus")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
