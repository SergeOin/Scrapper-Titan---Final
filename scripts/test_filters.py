#!/usr/bin/env python3
"""
Script de test automatisé des filtres du scraper.

Ce script vérifie :
1. Le filtre de date (< 3 semaines)
2. Le filtre stage/alternance
3. Le filtre France uniquement
4. La détection de recrutement

Usage:
    python scripts/test_filters.py
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import utils
from scraper.legal_classifier import classify_legal_post, STAGE_ALTERNANCE_EXCLUSION

# =============================================================================
# DONNÉES DE TEST
# =============================================================================

# Posts de test pour le filtre de date
DATE_TEST_CASES = [
    ("2025-11-25T10:00:00+00:00", False, "Post d'hier - doit être accepté"),
    ("2025-11-10T10:00:00+00:00", False, "Post de 16 jours - doit être accepté"),
    ("2025-10-30T10:00:00+00:00", True, "Post de 27 jours - doit être rejeté"),
    ("2025-09-01T10:00:00+00:00", True, "Post de 3 mois - doit être rejeté"),
    (None, True, "Date inconnue - doit être REJETÉ (sécurité)"),
    # Tests pour formats LinkedIn relatifs
    ("2 sem", False, "2 semaines (14j) - doit être accepté"),  # 14 jours < 21
    ("3 sem", False, "3 semaines (21j) - doit être accepté"),  # 21 jours = limite
    ("4 sem", True, "4 semaines (28j) - doit être rejeté"),   # 28 jours > 21
    ("4 w", True, "4 weeks - doit être rejeté"),
    ("1 w", False, "1 week - doit être accepté"),
    ("5 j", False, "5 jours - doit être accepté"),
    ("1 mo", True, "1 mois (30j) - doit être rejeté"),
    ("2 mois", True, "2 mois - doit être rejeté"),
]

# Posts de test pour le filtre stage/alternance
STAGE_TEST_CASES = [
    ("Nous recrutons un juriste en CDI", False, "CDI pur - doit être accepté"),
    ("Offre de stage juridique 6 mois", True, "Stage - doit être rejeté"),
    ("Recherche alternant droit des affaires", True, "Alternance - doit être rejeté"),
    ("Contrat d'apprentissage notaire", True, "Apprentissage - doit être rejeté"),
    ("Poste stagiaire avocat", True, "Stagiaire - doit être rejeté"),
    ("Internship legal department", True, "Internship - doit être rejeté"),
    ("CDI juriste contentieux Paris", False, "CDI contentieux - doit être accepté"),
    ("Nous recherchons un avocat collaborateur", False, "Avocat collab - doit être accepté"),
    ("V.I.E mission juridique", True, "VIE - doit être rejeté"),
]

# Posts de test pour le filtre France
FRANCE_TEST_CASES = [
    ("Poste juriste CDI Paris La Défense", True, "Paris - doit être accepté"),
    ("Avocat collaborateur Lyon", True, "Lyon - doit être accepté"),
    ("Legal counsel position London", False, "London - doit être rejeté"),
    ("Juriste Brussels Belgium", False, "Belgium - doit être rejeté"),
    ("CDI juriste", True, "Pas de localisation - accepté par défaut"),
    ("Poste Genève Suisse", False, "Suisse - doit être rejeté"),
    ("Offre Luxembourg", False, "Luxembourg - doit être rejeté"),
    ("Marseille Aix-en-Provence", True, "Marseille - doit être accepté"),
    ("Cabinet avocat Bordeaux", True, "Bordeaux - doit être accepté"),
]

# Posts de test pour la détection recrutement
RECRUITMENT_TEST_CASES = [
    ("Nous recrutons un juriste CDI pour notre direction juridique à Paris", "recherche_profil", "Recrutement clair"),
    ("Article sur le droit des affaires en France", "autre", "Article informatif"),
    ("Je recrute un avocat collaborateur pour mon cabinet", "recherche_profil", "Recrutement direct"),
    ("Offre d'emploi juriste contentieux CDI Lyon", "recherche_profil", "Offre emploi"),
    ("Réflexion sur la compliance en entreprise", "autre", "Article réflexion"),
    ("Poste à pourvoir directeur juridique Paris", "recherche_profil", "Poste à pourvoir"),
    ("Formation continue droit fiscal", "autre", "Formation - pas recrutement"),
]

# =============================================================================
# FONCTIONS DE TEST
# =============================================================================

def test_date_filter():
    """Teste le filtre de date (3 semaines max)."""
    print("\n" + "="*60)
    print("🕐 TEST FILTRE DATE (< 3 semaines)")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for date_str, should_reject, description in DATE_TEST_CASES:
        result = utils.is_post_too_old(date_str, max_age_days=21)
        status = "✅" if result == should_reject else "❌"
        
        if result == should_reject:
            passed += 1
        else:
            failed += 1
            
        print(f"{status} {description}")
        print(f"   Date: {date_str} | Rejeté: {result} | Attendu: {should_reject}")
    
    return passed, failed


def test_stage_alternance_filter():
    """Teste le filtre stage/alternance."""
    print("\n" + "="*60)
    print("🎓 TEST FILTRE STAGE/ALTERNANCE")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for text, should_reject, description in STAGE_TEST_CASES:
        result = utils.is_stage_or_alternance(text)
        status = "✅" if result == should_reject else "❌"
        
        if result == should_reject:
            passed += 1
        else:
            failed += 1
            
        print(f"{status} {description}")
        print(f"   Texte: '{text[:50]}...' | Rejeté: {result} | Attendu: {should_reject}")
    
    return passed, failed


def test_france_filter():
    """Teste le filtre France uniquement."""
    print("\n" + "="*60)
    print("🇫🇷 TEST FILTRE FRANCE UNIQUEMENT")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for text, should_accept, description in FRANCE_TEST_CASES:
        result = utils.is_location_france(text, strict=True)
        status = "✅" if result == should_accept else "❌"
        
        if result == should_accept:
            passed += 1
        else:
            failed += 1
            
        print(f"{status} {description}")
        print(f"   Texte: '{text[:50]}...' | Accepté: {result} | Attendu: {should_accept}")
    
    return passed, failed


def test_recruitment_detection():
    """Teste la détection de recrutement."""
    print("\n" + "="*60)
    print("💼 TEST DÉTECTION RECRUTEMENT")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for text, expected_intent, description in RECRUITMENT_TEST_CASES:
        result = classify_legal_post(text, language="fr", intent_threshold=0.15)
        status = "✅" if result.intent == expected_intent else "❌"
        
        if result.intent == expected_intent:
            passed += 1
        else:
            failed += 1
            
        print(f"{status} {description}")
        print(f"   Intent: {result.intent} | Attendu: {expected_intent} | Score: {result.relevance_score:.2f}")
    
    return passed, failed


def test_combined_scenario():
    """Teste un scénario combiné réaliste."""
    print("\n" + "="*60)
    print("🔄 TEST SCÉNARIO COMBINÉ")
    print("="*60)
    
    # Simulation de posts réels
    test_posts = [
        {
            "text": "Notre cabinet d'avocats à Paris recherche un juriste CDI spécialisé en droit des affaires. Rejoignez notre équipe !",
            "date": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            "expected": "ACCEPT",
            "reason": "CDI Paris récent"
        },
        {
            "text": "Stage avocat 6 mois droit social Paris",
            "date": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            "expected": "REJECT",
            "reason": "Stage"
        },
        {
            "text": "Legal counsel position London headquarters",
            "date": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
            "expected": "REJECT",
            "reason": "London (hors France)"
        },
        {
            "text": "Nous recrutons un directeur juridique pour notre siège à Lyon. CDI temps plein.",
            "date": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            "expected": "REJECT",
            "reason": "Trop ancien (30 jours)"
        },
        {
            "text": "Alternance juriste compliance Bordeaux",
            "date": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "expected": "REJECT",
            "reason": "Alternance"
        },
    ]
    
    passed = 0
    failed = 0
    
    for post in test_posts:
        # Appliquer tous les filtres
        is_too_old = utils.is_post_too_old(post["date"], max_age_days=21)
        is_stage = utils.is_stage_or_alternance(post["text"])
        is_france = utils.is_location_france(post["text"], strict=True)
        
        # Décision finale
        if is_too_old or is_stage or not is_france:
            result = "REJECT"
        else:
            result = "ACCEPT"
        
        status = "✅" if result == post["expected"] else "❌"
        if result == post["expected"]:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} {post['reason']}")
        print(f"   Résultat: {result} | Attendu: {post['expected']}")
        print(f"   (TooOld={is_too_old}, Stage={is_stage}, France={is_france})")
    
    return passed, failed


def main():
    """Exécute tous les tests."""
    print("\n" + "="*60)
    print("🧪 TESTS AUTOMATISÉS DES FILTRES SCRAPER TITAN")
    print("="*60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    total_passed = 0
    total_failed = 0
    
    # Exécuter tous les tests
    tests = [
        ("Date", test_date_filter),
        ("Stage/Alternance", test_stage_alternance_filter),
        ("France", test_france_filter),
        ("Recrutement", test_recruitment_detection),
        ("Combiné", test_combined_scenario),
    ]
    
    results = {}
    for name, test_func in tests:
        passed, failed = test_func()
        results[name] = (passed, failed)
        total_passed += passed
        total_failed += failed
    
    # Résumé final
    print("\n" + "="*60)
    print("📊 RÉSUMÉ DES TESTS")
    print("="*60)
    
    for name, (passed, failed) in results.items():
        total = passed + failed
        pct = (passed / total * 100) if total > 0 else 0
        status = "✅" if failed == 0 else "⚠️"
        print(f"{status} {name}: {passed}/{total} ({pct:.0f}%)")
    
    print("-" * 40)
    total = total_passed + total_failed
    pct = (total_passed / total * 100) if total > 0 else 0
    final_status = "✅ TOUS LES TESTS PASSENT" if total_failed == 0 else f"❌ {total_failed} TESTS ÉCHOUÉS"
    print(f"TOTAL: {total_passed}/{total} ({pct:.0f}%)")
    print(final_status)
    
    # Retourner le code de sortie approprié
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
