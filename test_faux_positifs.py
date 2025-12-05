"""
Script de test pour valider les nouvelles exclusions de faux positifs.

Ce script teste:
1. Les posts qui DOIVENT être rejetés (faux positifs identifiés)
2. Les posts qui DOIVENT être acceptés (vrais positifs)

Exécuter avec: python test_faux_positifs.py
"""

import sys
sys.path.insert(0, '.')

from scraper.legal_filter import is_legal_job_post, FilterConfig

# Configuration stricte avec les nouveaux flags
config = FilterConfig(
    legal_threshold=0.30,
    recruitment_threshold=0.35,
    exclude_formation_education=True,
    exclude_recrutement_passe=True,
    exclude_candidat_individu=True,
    exclude_contenu_informatif=True,
)

# =============================================================================
# TESTS: REJETER (Faux positifs de l'analyse)
# =============================================================================
reject_cases = [
    # Formation/Education (24% des faux positifs)
    ("Le cabinet a maintenant sa 'toque', et est désormais inscrit dans l'annuaire des avocats", "formation_education"),
    ("Wavestone recrute ses futurs account managers en CDI ! Tu es jeune diplômé(e)", "formation_education"),
    ("Félicitations à nos étudiants qui ont réussi l'examen du barreau", "formation_education"),
    
    # Veille Juridique (22% des faux positifs)
    ("Steering Legal 📍Lyon 2 Avocat(e) collaborateur/trice Droit des affaires - M&A - Article sur les tendances", "veille_juridique"),
    ("Groupe Int. du secteur du luxe - Directeur juridique corporate / M&A - Analyse du marché", "veille_juridique"),
    
    # Candidat cherchant emploi (9% des faux positifs)
    ("Bonjour à tous ! Je recherche un nouveau poste et vous serais reconnaissant(e) de m'aider", "candidat_individu"),
    ("Je suis juriste avec 5 ans d'expérience. Mon CV est disponible sur demande", "candidat_individu"),
    ("#OpenToWork Je cherche un poste de juriste en droit social", "candidat_individu"),
    
    # Recrutement passé (4% des faux positifs)
    ("Je suis heureuse et fière d'annoncer une nouvelle étape dans mon parcours professionnel", "recrutement_passe"),
    ("J'ai le plaisir de vous annoncer que j'occupe désormais le poste de avocate", "recrutement_passe"),
    ("Bienvenue à notre nouveau collaborateur qui a rejoint notre équipe juridique", "recrutement_passe"),
    
    # Contenu informatif (8% des faux positifs)
    ("C'est qui votre notaire ? 👀 Chaque mois, découvrez un de nos notaires associés - Article", "contenu_informatif"),
    ("Webinaire sur le droit fiscal - Inscrivez-vous maintenant !", "contenu_informatif"),
    ("Notre blog : Les tendances du droit des affaires en 2025", "contenu_informatif"),
]

# =============================================================================
# TESTS: ACCEPTER (Vrais positifs)
# =============================================================================
accept_cases = [
    "Cabinet ABC recrute un avocat collaborateur en CDI à Paris. Postulez maintenant !",
    "Nous recherchons un juriste droit social pour notre direction juridique - CDI temps plein",
    "Étude notariale recrute un notaire associé - CDI - Lyon. Envoyez votre CV",
    "Notre cabinet recrute un legal counsel senior. Poste à pourvoir immédiatement.",
    "On recrute ! Directeur juridique H/F - CDI - Paris La Défense",
]

# =============================================================================
# EXÉCUTION DES TESTS
# =============================================================================

print("=" * 80)
print("TESTS DE REJET DES FAUX POSITIFS")
print("=" * 80)
print(f"\nConfiguration utilisée:")
print(f"  - legal_threshold: {config.legal_threshold}")
print(f"  - recruitment_threshold: {config.recruitment_threshold}")
print(f"  - exclude_formation_education: {config.exclude_formation_education}")
print(f"  - exclude_recrutement_passe: {config.exclude_recrutement_passe}")
print(f"  - exclude_candidat_individu: {config.exclude_candidat_individu}")
print(f"  - exclude_contenu_informatif: {config.exclude_contenu_informatif}")

print("\n" + "=" * 80)
print("TESTS: REJETER (Faux positifs)")
print("=" * 80)

reject_success = 0
reject_fail = 0

for text, expected_reason in reject_cases:
    result = is_legal_job_post(text, config=config)
    if not result.is_valid:
        status = "✅"
        reject_success += 1
        reason_match = expected_reason in result.exclusion_reason
        if not reason_match:
            status = "⚠️"  # Rejeté mais pas pour la bonne raison
    else:
        status = "❌"
        reject_fail += 1
    
    print(f"\n{status} {text[:60]}...")
    if not result.is_valid:
        print(f"   Raison: {result.exclusion_reason}")
        print(f"   Termes: {result.exclusion_terms}")
    else:
        print(f"   ❌ ERREUR: Devrait être rejeté pour '{expected_reason}'!")
        print(f"   Scores: legal={result.legal_score:.2f}, recruitment={result.recruitment_score:.2f}")

print("\n" + "=" * 80)
print("TESTS: ACCEPTER (Vrais positifs)")
print("=" * 80)

accept_success = 0
accept_fail = 0

for text in accept_cases:
    result = is_legal_job_post(text, config=config)
    if result.is_valid:
        status = "✅"
        accept_success += 1
    else:
        status = "❌"
        accept_fail += 1
    
    print(f"\n{status} {text[:60]}...")
    if result.is_valid:
        print(f"   Métiers: {result.target_jobs}")
        print(f"   Scores: legal={result.legal_score:.2f}, recruitment={result.recruitment_score:.2f}")
    else:
        print(f"   ❌ ERREUR: Devrait être accepté!")
        print(f"   Raison rejet: {result.exclusion_reason}")
        print(f"   Termes: {result.exclusion_terms}")

# =============================================================================
# RÉSUMÉ
# =============================================================================
print("\n" + "=" * 80)
print("RÉSUMÉ DES TESTS")
print("=" * 80)
print(f"\nTests de REJET (faux positifs):")
print(f"  ✅ Réussis: {reject_success}/{len(reject_cases)}")
print(f"  ❌ Échoués: {reject_fail}/{len(reject_cases)}")

print(f"\nTests d'ACCEPTATION (vrais positifs):")
print(f"  ✅ Réussis: {accept_success}/{len(accept_cases)}")
print(f"  ❌ Échoués: {accept_fail}/{len(accept_cases)}")

total_success = reject_success + accept_success
total_tests = len(reject_cases) + len(accept_cases)
print(f"\nTOTAL: {total_success}/{total_tests} ({100*total_success//total_tests}%)")

if reject_fail > 0 or accept_fail > 0:
    print("\n⚠️ ATTENTION: Certains tests ont échoué. Vérifiez les configurations.")
    sys.exit(1)
else:
    print("\n✅ Tous les tests ont réussi!")
    sys.exit(0)
