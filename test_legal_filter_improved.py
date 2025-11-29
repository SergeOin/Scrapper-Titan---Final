#!/usr/bin/env python3
"""
Test amélioré du filtre is_legal_job_post avec configuration bootstrap.

Ce script valide que le filtre fonctionne correctement avec les paramètres
configurables définis dans bootstrap.py.
"""

import sys
sys.path.insert(0, '.')

from scraper.legal_filter import is_legal_job_post, FilterConfig, FilterResult

# =============================================================================
# SAMPLE POSTS FOR TESTING
# =============================================================================

VALID_POSTS = [
    # CDI Juriste classique
    ("🔔 RECRUTEMENT - Juriste en droit social (H/F) - CDI - Paris. "
     "Notre cabinet recherche un(e) juriste spécialisé(e) en droit social. "
     "Expérience : 3-5 ans. Contact : recrutement@cabinet.fr #emploi #juridique",
     "CDI juriste Paris - score élevé attendu"),
    
    # Direction juridique recrute
    ("Direction juridique - Nous recrutons ! Poste de Juriste Contrats H/F en CDI à Lyon. "
     "Rattaché au Directeur Juridique, vous gérez les contrats commerciaux. Postulez !",
     "Direction juridique Lyon - signal fort"),
    
    # Avocat droit des affaires
    ("🚀 Offre d'emploi : Avocat droit des affaires (H/F) CDI Paris. "
     "Cabinet international recherche avocat 5-7 ans d'expérience M&A.",
     "Avocat Paris CDI - offre explicite"),
    
    # Notaire recrute
    ("Notre étude notariale recrute un notaire salarié pour son office de Bordeaux. "
     "CDI temps plein, rémunération attractive. Expérience 2 ans minimum.",
     "Notaire Bordeaux CDI"),
    
    # Responsable juridique
    ("Le groupe X renforce sa direction juridique et recrute un Responsable Juridique M&A. "
     "CDI basé à Paris La Défense. Package 80-100K€.",
     "Responsable juridique Paris - poste senior"),
]

INVALID_POSTS = [
    # Stage
    ("Stage juriste droit social 6 mois - Paris. Notre cabinet recherche un stagiaire. "
     "Début janvier 2024. Gratification légale.",
     "stage_alternance", "Stage = exclu automatiquement"),
    
    # Alternance
    ("Alternance juriste contrats - Lyon. Master 2 droit des affaires ? "
     "Rejoignez-nous en alternance ! Rythme 3j/2j.",
     "stage_alternance", "Alternance = exclu"),
    
    # Freelance
    ("Freelance disponible : Consultant juridique RGPD, j'accompagne les PME. "
     "Tarif journalier : 600€. Devis sur demande.",
     "freelance_mission", "Freelance = exclu"),
    
    # #OpenToWork
    ("#OpenToWork Juriste en recherche d'emploi, 5 ans d'expérience droit des affaires. "
     "Disponible immédiatement. Contactez-moi !",
     "chercheur_emploi", "Job seeker = exclu"),
    
    # Séminaire (promo)
    ("Séminaire juridique : Découvrez les évolutions du droit du travail. "
     "Webinar gratuit le 15 novembre ! Inscription : lien.fr #formation",
     "contenu_promotionnel", "Promo/événement = exclu"),
    
    # Formation
    ("📚 Formation continue pour juristes : Maîtrisez le RGPD en 2 jours ! "
     "Inscription sur notre site. Tarif early bird disponible.",
     "contenu_promotionnel", "Formation = exclu"),
    
    # Cabinet de recrutement
    ("Michael Page recrute pour son client un Juriste Corporate H/F. "
     "CDI Paris. Salaire 50-60K€. Postulez vite !",
     "cabinet_recrutement", "Agence de recrutement = exclu"),
    
    # Poste hors France
    ("Juriste Corporate CDI Genève. Notre client suisse recherche un juriste. "
     "Package attractif + relocation. Français natif requis.",
     "hors_france", "Suisse = hors France = exclu"),
    
    # Métier non juridique
    ("Notre cabinet d'avocats recrute un Développeur Python confirmé (H/F) CDI. "
     "Stack : Django, PostgreSQL. 5+ ans d'expérience.",
     "metier_non_juridique", "Dev dans cabinet = non juridique = exclu"),
    
    # RH (non juridique)
    ("Direction juridique recherche un Chargé de recrutement H/F en CDI à Bordeaux. "
     "Expérience 3 ans RH minimum. Package 45K.",
     "metier_non_juridique", "RH = non juridique = exclu"),
    
    # Score insuffisant (pas de recrutement clair)
    ("Après 3 ans chez nous, notre juriste quitte l'équipe pour de nouvelles aventures. "
     "Bonne continuation Marine ! #depart #equipe",
     "score_insuffisant_recrutement", "Pas de signal de recrutement"),
]

# =============================================================================
# TEST FUNCTIONS
# =============================================================================

def test_with_default_config():
    """Test avec la configuration par défaut."""
    print("=" * 80)
    print("TEST AVEC CONFIGURATION PAR DÉFAUT")
    print("=" * 80)
    
    config = FilterConfig()  # Défauts
    print(f"\nSeuils: recruitment >= {config.recruitment_threshold}, legal >= {config.legal_threshold}")
    print(f"Exclusions actives: stage={config.exclude_stage}, freelance={config.exclude_freelance}, "
          f"opentowork={config.exclude_opentowork}, promo={config.exclude_promo}, "
          f"agencies={config.exclude_agencies}, foreign={config.exclude_foreign}, "
          f"non_legal={config.exclude_non_legal}\n")
    
    # Test valid posts
    print("-" * 40)
    print("POSTS VALIDES ATTENDUS:")
    print("-" * 40)
    valid_ok = 0
    for text, desc in VALID_POSTS:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        status = "✅" if result.is_valid else "❌"
        if result.is_valid:
            valid_ok += 1
        print(f"{status} {desc}")
        print(f"   → recruit={result.recruitment_score:.2f}, legal={result.legal_score:.2f}")
        if not result.is_valid:
            print(f"   ⚠️  Raison: {result.exclusion_reason}")
    
    # Test invalid posts
    print("\n" + "-" * 40)
    print("POSTS À EXCLURE:")
    print("-" * 40)
    invalid_ok = 0
    for text, expected_reason, desc in INVALID_POSTS:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        if not result.is_valid and expected_reason in result.exclusion_reason:
            status = "✅"
            invalid_ok += 1
        elif not result.is_valid:
            status = "⚠️"  # Exclu mais pas pour la bonne raison
        else:
            status = "❌"
        print(f"{status} {desc}")
        print(f"   → Attendu: {expected_reason}, Obtenu: {result.exclusion_reason or 'ACCEPTÉ'}")
    
    print("\n" + "=" * 80)
    print(f"RÉSULTAT: {valid_ok}/{len(VALID_POSTS)} posts valides OK, "
          f"{invalid_ok}/{len(INVALID_POSTS)} exclusions OK")
    print("=" * 80)
    
    return valid_ok == len(VALID_POSTS) and invalid_ok == len(INVALID_POSTS)


def test_with_custom_config():
    """Test avec une configuration personnalisée (seuils plus stricts)."""
    print("\n" + "=" * 80)
    print("TEST AVEC CONFIGURATION PERSONNALISÉE (SEUILS STRICTS)")
    print("=" * 80)
    
    # Config stricte: seuils plus élevés
    config = FilterConfig(
        recruitment_threshold=0.25,  # Plus strict
        legal_threshold=0.30,        # Plus strict
        exclude_stage=True,
        exclude_freelance=True,
        exclude_opentowork=True,
        exclude_promo=True,
        exclude_agencies=True,
        exclude_foreign=True,
        exclude_non_legal=True,
        verbose=False,
    )
    
    print(f"\nSeuils stricts: recruitment >= {config.recruitment_threshold}, legal >= {config.legal_threshold}\n")
    
    # Avec seuils plus stricts, certains posts valides peuvent être rejetés
    accepted = 0
    for text, desc in VALID_POSTS:
        result = is_legal_job_post(text, config=config, log_exclusions=False)
        if result.is_valid:
            accepted += 1
            print(f"✅ {desc} (recruit={result.recruitment_score:.2f}, legal={result.legal_score:.2f})")
        else:
            print(f"⚠️  {desc} - exclu: {result.exclusion_reason}")
    
    print(f"\n→ {accepted}/{len(VALID_POSTS)} posts acceptés avec config stricte")
    print("  (Normal d'avoir moins de posts acceptés avec des seuils plus élevés)")


def test_selective_exclusions():
    """Test avec exclusions sélectives désactivées."""
    print("\n" + "=" * 80)
    print("TEST AVEC EXCLUSIONS SÉLECTIVES DÉSACTIVÉES")
    print("=" * 80)
    
    # Config qui accepte les stages mais pas le reste
    config = FilterConfig(
        recruitment_threshold=0.15,
        legal_threshold=0.20,
        exclude_stage=False,  # ← Désactivé
        exclude_freelance=True,
        exclude_opentowork=True,
        exclude_promo=True,
        exclude_agencies=True,
        exclude_foreign=True,
        exclude_non_legal=True,
        verbose=False,
    )
    
    print("\nConfiguration: stages ACCEPTÉS, autres exclusions actives\n")
    
    # Le post de stage devrait maintenant passer les exclusions
    stage_post = ("Stage juriste droit social 6 mois - Paris. Notre cabinet recherche un stagiaire. "
                  "Début janvier 2024. Gratification légale.")
    
    result = is_legal_job_post(stage_post, config=config, log_exclusions=False)
    
    if result.exclusion_reason == "stage_alternance":
        print("❌ Stage toujours exclu (bug?)")
    elif result.is_valid:
        print("✅ Stage accepté (exclusion désactivée + scores OK)")
    else:
        print(f"⚠️  Stage non exclu mais scores insuffisants: {result.exclusion_reason}")
        print(f"   (recruit={result.recruitment_score:.2f}, legal={result.legal_score:.2f})")


def main():
    """Exécuter tous les tests."""
    print("\n" + "🔍" * 40)
    print(" TEST DU FILTRE LEGAL AMÉLIORÉ")
    print("🔍" * 40 + "\n")
    
    success = test_with_default_config()
    test_with_custom_config()
    test_selective_exclusions()
    
    print("\n" + "=" * 80)
    if success:
        print("🎉 TOUS LES TESTS PASSENT - Le filtre est prêt pour la production")
    else:
        print("⚠️  CERTAINS TESTS ONT ÉCHOUÉ - Vérifier les configurations")
    print("=" * 80)


if __name__ == "__main__":
    main()
