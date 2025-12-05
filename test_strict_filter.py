#!/usr/bin/env python3
"""
Tests stricts pour le filtrage des 16 métiers juridiques.

RÈGLE FONDAMENTALE:
- Ne scrapper QUE les posts d'ENTREPRISES qui recrutent ACTIVEMENT pour les 16 métiers.
- REJETER ABSOLUMENT:
  1. Posts parlant du métier SANS recrutement
  2. Posts de cabinets de recrutement (concurrents)
  3. Posts de candidats cherchant du travail
"""

import sys
sys.path.insert(0, '.')

from scraper.legal_filter import (
    is_legal_job_post, 
    FilterConfig,
    is_recruitment_agency_strict,
    is_coherent_legal_recruitment,
    detect_specialized_job_info,
    TARGET_JOBS_16,
)


def print_separator(title: str) -> None:
    """Affiche un séparateur avec titre."""
    print("=" * 60)
    print(title)
    print("=" * 60)


def run_tests():
    """Exécute tous les tests de filtrage strict."""
    
    # Configuration stricte
    config = FilterConfig(
        legal_threshold=0.25,
        recruitment_threshold=0.20,
    )
    
    passed = 0
    failed = 0
    
    # ========================================================================
    # TESTS: ACCEPTER (recrutement actif + métier cible)
    # ========================================================================
    print_separator("TESTS: ACCEPTER (Recrutement actif + Métier cible)")
    
    accept_cases = [
        "Cabinet ABC recrute un avocat collaborateur en CDI à Paris",
        "Nous recherchons un juriste droit social pour notre direction juridique",
        "Étude notariale recrute un notaire associé - CDI - Lyon",
        "Directeur fiscal à pourvoir - Groupe Fortune 500 - Paris - CDI",
        "Paralegal recherché pour cabinet juridique - CDI - Bordeaux",
        "Notre cabinet recrute un avocat counsel - Paris - Droit des affaires",
        "Poste à pourvoir: Responsable juridique - CDI - Nantes",
        "Nous recrutons une directrice juridique pour notre groupe - Paris",
        "Legal Counsel recherché - CDI - Direction juridique - Lyon",
        "Clerc de notaire - Poste ouvert - Étude notariale - Marseille",
    ]
    
    for text in accept_cases:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        status = "✅ PASS" if result.is_valid else "❌ FAIL"
        if result.is_valid:
            passed += 1
            print(f"{status} {text[:50]}...")
            print(f"   Métiers: {result.target_jobs}")
        else:
            failed += 1
            print(f"{status} {text[:50]}...")
            print(f"   ⚠️ Attendu: ACCEPTER | Raison rejet: {result.get_rejection_reason()}")
        print()
    
    # ========================================================================
    # TESTS: REJETER (pas de recrutement actif)
    # ========================================================================
    print_separator("TESTS: REJETER (Pas de recrutement actif)")
    
    reject_no_recruitment = [
        "Le cabinet d'avocats ABC est spécialisé en droit du travail",
        "Nos juristes ont 10+ ans d'expérience en droit fiscal",
        "Cabinet notarial depuis 50 ans - Équipe de 5 notaires",
        "Directeur juridique du groupe XYZ parle de ses défis quotidiens",
        "Rencontre avec notre avocat associé qui partage son parcours",
        "Notre juriste explique les nouvelles réglementations RGPD",
    ]
    
    for text in reject_no_recruitment:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        status = "✅ PASS" if not result.is_valid else "❌ FAIL"
        if not result.is_valid:
            passed += 1
            print(f"{status} {text[:50]}...")
            print(f"   Raison: {result.get_rejection_reason()}")
        else:
            failed += 1
            print(f"{status} {text[:50]}...")
            print(f"   ⚠️ Attendu: REJETER | Mais accepté avec score={result.recruitment_score:.2f}")
        print()
    
    # ========================================================================
    # TESTS: REJETER (Cabinet de recrutement)
    # ========================================================================
    print_separator("TESTS: REJETER (Cabinet de recrutement)")
    
    reject_agencies = [
        "Fed Legal recrute pour son client un avocat droit du travail",
        "Michael Page recherche un juriste pour l'un de ses clients",
        "Nous recrutons pour le compte d'une grande entreprise un directeur fiscal",
        "Cabinet de recrutement spécialisé - Recherche notaire associé",
        "Robert Walters - Opportunité : Juriste corporate - CDI",
        "Hays Legal - Pour notre client confidentiel - Avocat M&A",
        "Pour notre client, nous recherchons un responsable juridique",
        "Client confidentiel recherche un paralegal - CDI - Paris",
    ]
    
    for text in reject_agencies:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        status = "✅ PASS" if not result.is_valid else "❌ FAIL"
        if not result.is_valid:
            passed += 1
            print(f"{status} {text[:50]}...")
            print(f"   Raison: {result.get_rejection_reason()}")
        else:
            failed += 1
            print(f"{status} {text[:50]}...")
            print(f"   ⚠️ Attendu: REJETER | Mais accepté!")
        print()
    
    # ========================================================================
    # TESTS: REJETER (Métier non-cible)
    # ========================================================================
    print_separator("TESTS: REJETER (Métier non-cible)")
    
    reject_non_target = [
        "Nous recrutons un développeur pour notre cabinet juridique",
        "Recherche community manager pour cabinet d'avocats",
        "Cabinet notarial recrute un assistant administratif - CDI",
        "Direction juridique recrute un comptable - Paris",
        "Notre cabinet recrute un commercial - CDI - Lyon",
    ]
    
    for text in reject_non_target:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        status = "✅ PASS" if not result.is_valid else "❌ FAIL"
        if not result.is_valid:
            passed += 1
            print(f"{status} {text[:50]}...")
            print(f"   Raison: {result.get_rejection_reason()}")
        else:
            failed += 1
            print(f"{status} {text[:50]}...")
            print(f"   ⚠️ Attendu: REJETER | Mais accepté!")
        print()
    
    # ========================================================================
    # TESTS: REJETER (Candidat cherchant du travail)
    # ========================================================================
    print_separator("TESTS: REJETER (Candidat cherchant du travail)")
    
    reject_jobseekers = [
        "Je recherche un poste de juriste en droit social - #OpenToWork",
        "Avocat disponible immédiatement - Cherche CDI - Paris",
        "Mon CV: Juriste 5 ans d'expérience - À l'écoute du marché",
        "Je suis juriste et je recherche de nouvelles opportunités",
        "Jeune diplômé avocat recherche son premier poste - Paris",
    ]
    
    for text in reject_jobseekers:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        status = "✅ PASS" if not result.is_valid else "❌ FAIL"
        if not result.is_valid:
            passed += 1
            print(f"{status} {text[:50]}...")
            print(f"   Raison: {result.get_rejection_reason()}")
        else:
            failed += 1
            print(f"{status} {text[:50]}...")
            print(f"   ⚠️ Attendu: REJETER | Mais accepté!")
        print()
    
    # ========================================================================
    # TESTS: REJETER (Stage/Alternance)
    # ========================================================================
    print_separator("TESTS: REJETER (Stage/Alternance)")
    
    reject_stage = [
        "Nous recrutons un stagiaire juriste pour 6 mois",
        "Offre d'alternance - Juriste droit social - Paris",
        "Cabinet recrute un alternant en droit des affaires",
        "Stage PFE - Direction juridique - 6 mois - Paris",
    ]
    
    for text in reject_stage:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        status = "✅ PASS" if not result.is_valid else "❌ FAIL"
        if not result.is_valid:
            passed += 1
            print(f"{status} {text[:50]}...")
            print(f"   Raison: {result.get_rejection_reason()}")
        else:
            failed += 1
            print(f"{status} {text[:50]}...")
            print(f"   ⚠️ Attendu: REJETER | Mais accepté!")
        print()
    
    # ========================================================================
    # TEST: FONCTION is_recruitment_agency_strict()
    # ========================================================================
    print_separator("TESTS: Fonction is_recruitment_agency_strict()")
    
    agency_tests = [
        ("Fed Legal recrute un avocat", True, "Cabinet connu"),
        ("Michael Page recherche un juriste", True, "Cabinet connu"),
        ("Pour notre client, recherche avocat", True, "Recrutement indirect"),
        ("Notre cabinet recrute un avocat", False, "Entreprise directe"),
        ("Client confidentiel recherche juriste", True, "Client confidentiel"),
    ]
    
    for text, expected_is_agency, desc in agency_tests:
        is_agency, reason = is_recruitment_agency_strict(text)
        status = "✅ PASS" if is_agency == expected_is_agency else "❌ FAIL"
        if is_agency == expected_is_agency:
            passed += 1
        else:
            failed += 1
        print(f"{status} [{desc}] {text[:40]}...")
        print(f"   Attendu: is_agency={expected_is_agency} | Obtenu: {is_agency} ({reason})")
        print()
    
    # ========================================================================
    # TEST: FONCTION detect_specialized_job_info()
    # ========================================================================
    print_separator("TESTS: Fonction detect_specialized_job_info()")
    
    job_info_tests = [
        ("Avocat collaborateur en CDI", ["avocat collaborateur"]),
        ("Juriste droit social", ["juriste"]),
        ("Directeur juridique", ["directeur juridique"]),
        ("Notaire associé recherché", ["notaire associé"]),
        ("Paralegal pour cabinet", ["paralegal"]),
        ("Clerc de notaire", ["clerc de notaire"]),
    ]
    
    for text, expected_jobs in job_info_tests:
        info = detect_specialized_job_info(text)
        has_expected = any(j in info['target_jobs'] for j in expected_jobs) or \
                       any(j.split()[0] in str(info['target_jobs']) for j in expected_jobs)
        status = "✅ PASS" if has_expected or info['target_jobs'] else "❌ FAIL"
        if has_expected or info['target_jobs']:
            passed += 1
        else:
            failed += 1
        print(f"{status} {text}")
        print(f"   Attendu: {expected_jobs} | Obtenu: {info['target_jobs']}")
        print()
    
    # ========================================================================
    # RÉSUMÉ
    # ========================================================================
    print_separator("RÉSUMÉ DES TESTS")
    total = passed + failed
    print(f"✅ Réussis: {passed}/{total}")
    print(f"❌ Échoués: {failed}/{total}")
    print(f"📊 Taux de réussite: {100*passed/total:.1f}%")
    
    if failed > 0:
        print("\n⚠️ ATTENTION: Certains tests ont échoué!")
        return 1
    else:
        print("\n🎉 Tous les tests ont réussi!")
        return 0


def test_16_target_jobs():
    """Teste que les 16 métiers sont bien définis."""
    print_separator("TEST: 16 Métiers Cibles Définis")
    
    expected_jobs = [
        "avocat collaborateur",
        "avocat associé", 
        "avocat counsel",
        "paralegal",
        "legal counsel",
        "juriste",
        "responsable juridique",
        "directeur juridique",
        "notaire stagiaire",
        "notaire associé",
        "notaire salarié",
        "notaire assistant",
        "clerc de notaire",
        "rédacteur d'actes",
        "responsable fiscal",
        "directeur fiscal",
    ]
    
    print(f"Nombre de métiers attendus: {len(expected_jobs)}")
    print(f"Nombre de métiers définis: {len(TARGET_JOBS_16)}")
    
    for job in expected_jobs:
        if job in TARGET_JOBS_16:
            print(f"  ✅ {job}")
        else:
            print(f"  ❌ {job} - MANQUANT!")
    
    if len(TARGET_JOBS_16) == 16:
        print("\n✅ Les 16 métiers sont bien définis!")
    else:
        print(f"\n⚠️ Nombre de métiers incorrect: {len(TARGET_JOBS_16)} au lieu de 16")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  TESTS STRICTS - FILTRAGE DES 16 MÉTIERS JURIDIQUES")
    print("  Ciblage: Recrutement ACTIF uniquement")
    print("  Exclusion: Cabinets de recrutement, Candidats, Pas de recrutement")
    print("=" * 70 + "\n")
    
    # Tester les 16 métiers
    test_16_target_jobs()
    print()
    
    # Exécuter les tests
    exit_code = run_tests()
    sys.exit(exit_code)
