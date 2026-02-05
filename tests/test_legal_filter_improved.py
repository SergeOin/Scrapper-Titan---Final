"""
Tests unitaires pour le module legal_filter.py amélioré.

Ces tests vérifient que le filtre :
1. Accepte les offres d'emploi juridiques CDI/CDD en France
2. Rejette les stages, alternances, freelances
3. Rejette les postes hors France
4. Rejette les contenus non-pertinents (pub, job seekers, etc.)
"""

import pytest
from scraper.legal_filter import (
    is_legal_job_post,
    normalize_text,
    calculate_legal_profession_score,
    calculate_recruitment_score,
    check_exclusions,
    FilterConfig,
    FilterResult,
)


# =============================================================================
# TESTS DE NORMALISATION
# =============================================================================

class TestNormalization:
    """Tests pour la fonction normalize_text."""

    def test_normalize_lowercase(self):
        assert normalize_text("AVOCAT") == "avocat"

    def test_normalize_accents(self):
        assert normalize_text("Étude Notariale") == "etude notariale"
        assert "juriste confirme" in normalize_text("Juriste Confirmé")

    def test_normalize_hashtags(self):
        """Les hashtags sont conservés comme mots simples."""
        result = normalize_text("#avocat #recrutement")
        assert "avocat" in result
        assert "recrutement" in result
        assert "#" not in result

    def test_normalize_emojis(self):
        result = normalize_text("🚀 Nous recrutons un juriste! 🎉")
        assert "nous recrutons un juriste" in result


# =============================================================================
# TESTS DE SCORE JURIDIQUE
# =============================================================================

class TestLegalProfessionScore:
    """Tests pour calculate_legal_profession_score."""

    def test_avocat_detected(self):
        score, matches = calculate_legal_profession_score("Nous recrutons un avocat en CDI")
        assert score > 0.2
        assert any("avocat" in m for m in matches)

    def test_juriste_detected(self):
        score, matches = calculate_legal_profession_score("Offre de Juriste d'entreprise")
        assert score > 0.2
        assert any("juriste" in m for m in matches)

    def test_paralegal_detected(self):
        score, matches = calculate_legal_profession_score("Poste de Paralegal à pourvoir")
        assert score > 0.2
        assert any("paralegal" in m for m in matches)

    def test_notaire_detected(self):
        score, matches = calculate_legal_profession_score("Étude notariale recrute notaire")
        assert score > 0.2
        assert any("notaire" in m for m in matches)

    def test_responsable_juridique(self):
        score, matches = calculate_legal_profession_score("Responsable Juridique H/F")
        assert score > 0.2
        assert any("responsable juridique" in m or "juridique" in m for m in matches)

    def test_directeur_juridique(self):
        score, matches = calculate_legal_profession_score("Directeur Juridique recherché")
        assert score > 0.2

    def test_no_legal_term(self):
        score, matches = calculate_legal_profession_score("Nous recrutons un commercial")
        assert score == 0.0
        assert len(matches) == 0


# =============================================================================
# TESTS DE SCORE RECRUTEMENT
# =============================================================================

class TestRecruitmentScore:
    """Tests pour calculate_recruitment_score."""

    def test_recrute_detected(self):
        """NOUVELLE LOGIQUE: 'nous recrutons' est le signal valide, pas 'je recrute'."""
        score, matches = calculate_recruitment_score("Nous recrutons un juriste. CDI à pourvoir.")
        assert score >= 0.15
        assert "nous recrutons" in matches

    def test_je_recrute_rejected(self):
        """'Je recrute' doit retourner score 0 (chasseur de têtes)."""
        score, matches = calculate_recruitment_score("Je recrute un juriste")
        assert score == 0.0

    def test_cdi_detected(self):
        score, matches = calculate_recruitment_score("CDI temps plein Paris")
        assert score >= 0.15
        assert "cdi" in matches

    def test_cdd_detected(self):
        score, matches = calculate_recruitment_score("CDD 12 mois remplacement")
        assert score >= 0.15
        assert "cdd" in matches

    def test_poste_a_pourvoir(self):
        score, matches = calculate_recruitment_score("Poste à pourvoir immédiatement")
        assert score >= 0.15

    def test_no_recruitment_signal(self):
        score, matches = calculate_recruitment_score("Article sur le droit du travail")
        assert score < 0.15


# =============================================================================
# TESTS D'EXCLUSION
# =============================================================================

class TestExclusions:
    """Tests pour check_exclusions."""

    def test_exclude_stage(self):
        result = check_exclusions("Stage juriste droit des affaires")
        assert result.excluded
        assert result.reason == "stage_alternance"

    def test_exclude_alternance(self):
        result = check_exclusions("Alternance Juriste 12 mois")
        assert result.excluded
        assert result.reason == "stage_alternance"

    def test_exclude_freelance(self):
        result = check_exclusions("Mission freelance juriste 3 mois")
        assert result.excluded
        assert result.reason == "freelance_mission"

    def test_exclude_canada(self):
        result = check_exclusions("Avocat recherché à Montréal, Canada")
        assert result.excluded
        assert result.reason == "hors_france"

    def test_exclude_suisse(self):
        result = check_exclusions("Juriste CDI Genève Suisse")
        assert result.excluded
        assert result.reason == "hors_france"

    def test_accept_france_with_foreign_mention(self):
        """Si France est mentionnée avec un pays étranger, on accepte."""
        result = check_exclusions("Cabinet Paris recrute juriste droit international - missions Europe")
        # Paris = France indicator, donc pas exclu même si "Europe" est vague
        assert not result.excluded

    def test_exclude_opentowork_jobseeker(self):
        result = check_exclusions("#OpenToWork Juriste recherche emploi")
        assert result.excluded
        assert result.reason in ("chercheur_emploi", "candidat_individu")

    def test_exclude_cabinet_recrutement(self):
        result = check_exclusions("Fed Legal recherche pour son client un juriste")
        assert result.excluded
        assert result.reason == "cabinet_recrutement"


# =============================================================================
# TESTS DU FILTRE PRINCIPAL
# =============================================================================

class TestIsLegalJobPost:
    """Tests pour la fonction principale is_legal_job_post."""

    # --- POSTS QUI DOIVENT ÊTRE ACCEPTÉS ---

    def test_accept_cdi_avocat_paris(self):
        """CDI Avocat à Paris = valide."""
        text = """
        Notre cabinet d'avocats recherche un Avocat Collaborateur (H/F) 
        en CDI pour son département Droit des Affaires.
        Poste basé à Paris 8ème.
        """
        result = is_legal_job_post(text)
        assert result.is_valid, f"Devrait accepter CDI Avocat Paris: {result.exclusion_reason}"

    def test_accept_cdd_juriste_lyon(self):
        """CDD Juriste à Lyon = valide."""
        text = """
        CDD 18 mois - Juriste droit social
        Nous recherchons un juriste confirmé pour rejoindre notre équipe à Lyon.
        Contrat à durée déterminée, remplacement congé maternité.
        """
        result = is_legal_job_post(text)
        assert result.is_valid, f"Devrait accepter CDD Juriste Lyon: {result.exclusion_reason}"

    def test_accept_paralegal_cdi(self):
        """CDI Paralegal = valide."""
        text = """
        Cabinet recrute un Paralegal en CDI 
        pour son équipe Corporate M&A.
        Profil junior accepté.
        """
        result = is_legal_job_post(text)
        assert result.is_valid, f"Devrait accepter CDI Paralegal: {result.exclusion_reason}"

    def test_accept_notaire_associe(self):
        """Notaire associé = valide."""
        text = """
        Étude notariale à Bordeaux recherche un Notaire Associé 
        pour renforcer notre équipe.
        CDI - Rémunération attractive.
        """
        result = is_legal_job_post(text)
        assert result.is_valid, f"Devrait accepter Notaire Associé: {result.exclusion_reason}"

    def test_accept_directeur_juridique(self):
        """Directeur Juridique = valide."""
        text = """
        Nous recrutons notre futur Directeur Juridique H/F
        en CDI pour piloter notre direction juridique groupe.
        Poste basé à La Défense.
        """
        result = is_legal_job_post(text)
        assert result.is_valid, f"Devrait accepter Directeur Juridique: {result.exclusion_reason}"

    def test_accept_responsable_juridique(self):
        """Responsable Juridique = valide."""
        text = """
        CDI - Responsable Juridique (H/F)
        Notre entreprise recherche un responsable juridique
        pour notre siège de Nantes.
        """
        result = is_legal_job_post(text)
        assert result.is_valid, f"Devrait accepter Responsable Juridique: {result.exclusion_reason}"

    def test_accept_recrute_pattern(self):
        """Pattern "[Entreprise] recrute" = valide."""
        text = """
        DataCorp recrute un juriste RGPD / DPO en CDI.
        Rejoignez notre équipe Legal à Paris!
        """
        result = is_legal_job_post(text)
        assert result.is_valid, f"Devrait accepter pattern recrute: {result.exclusion_reason}"

    # --- POSTS QUI DOIVENT ÊTRE REJETÉS ---

    def test_reject_stage_juriste(self):
        """Stage = rejeté."""
        text = """
        Stage Juriste Droit des Affaires (6 mois)
        Notre cabinet recherche un stagiaire pour son département M&A.
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason == "stage_alternance"

    def test_reject_alternance(self):
        """Alternance = rejeté."""
        text = """
        Alternance Juriste - 12 mois
        Formation en droit des contrats, poste basé à Lyon.
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason == "stage_alternance"

    def test_reject_freelance_juriste(self):
        """Freelance = rejeté."""
        text = """
        Mission freelance - Juriste contrats 3 mois
        Besoin urgent d'un consultant juridique externe.
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason == "freelance_mission"

    def test_reject_suisse(self):
        """Poste en Suisse = rejeté."""
        text = """
        CDI Avocat Droit Bancaire - Genève
        Cabinet suisse recherche avocat pour son bureau de Genève.
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason == "hors_france"

    def test_reject_canada(self):
        """Poste au Canada = rejeté."""
        text = """
        Juriste CDI - Montréal, Québec
        Cabinet canadien recrute juriste droit des affaires.
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason == "hors_france"

    def test_reject_opentowork(self):
        """#OpenToWork = rejeté (chercheur d'emploi, pas recruteur)."""
        text = """
        #OpenToWork
        Juriste 5 ans d'expérience recherche un nouveau challenge.
        Disponible immédiatement.
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason in ("chercheur_emploi", "candidat_individu")

    def test_reject_cabinet_recrutement(self):
        """Cabinet de recrutement = rejeté."""
        text = """
        Fed Legal recrute pour son client un Juriste Social H/F
        Notre client, groupe international, recherche...
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason == "cabinet_recrutement"

    def test_reject_non_legal_job(self):
        """Métier non juridique = rejeté."""
        text = """
        Nous recrutons un Directeur Marketing en CDI
        Poste basé à Paris - rejoignez notre équipe!
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        # Soit exclu par non_legal, soit par score insuffisant juridique
        assert "non_juridique" in result.exclusion_reason or "juridique" in result.exclusion_reason

    def test_reject_no_recruitment_signal(self):
        """Article sans signal de recrutement = rejeté."""
        text = """
        Les juristes d'entreprise face aux défis du RGPD.
        Article sur l'évolution du métier de juriste.
        """
        result = is_legal_job_post(text)
        assert not result.is_valid
        # La nouvelle logique retourne "veille_juridique" pour les articles
        assert any(r in result.exclusion_reason for r in ("recrutement", "veille"))


# =============================================================================
# TESTS CAS LIMITES
# =============================================================================

class TestEdgeCases:
    """Tests pour les cas limites et ambigus."""

    def test_mixed_france_etranger(self):
        """Poste mentionnant France ET étranger - accept si France explicite."""
        text = """
        CDI Juriste Droit International - Paris
        Notre cabinet recherche un juriste pour gérer nos clients européens.
        Déplacements ponctuels en Allemagne et Belgique.
        """
        result = is_legal_job_post(text)
        # Paris est une indication France, donc devrait accepter
        assert result.is_valid, f"Devrait accepter (Paris = France): {result.exclusion_reason}"

    def test_empty_text(self):
        """Texte vide = rejeté."""
        result = is_legal_job_post("")
        assert not result.is_valid
        assert result.exclusion_reason == "texte_vide"

    def test_short_text(self):
        """Texte très court sans info = rejeté."""
        result = is_legal_job_post("ok")
        assert not result.is_valid

    def test_special_characters(self):
        """Caractères spéciaux ne cassent pas le filtre."""
        text = """
        🚀 Nous recrutons! 🎉
        Juriste CDI ➜ Paris
        #hiring #avocat #legal
        """
        result = is_legal_job_post(text)
        assert result.is_valid, f"Emojis ne devraient pas bloquer: {result.exclusion_reason}"


# =============================================================================
# TESTS DE CONFIGURATION
# =============================================================================

class TestFilterConfig:
    """Tests pour FilterConfig personnalisé."""

    def test_disable_stage_exclusion(self):
        """Désactiver l'exclusion des stages."""
        config = FilterConfig(exclude_stage=False)
        text = "Stage Juriste - 6 mois - Paris"
        result = is_legal_job_post(text, config=config)
        # Ne devrait pas être exclu pour stage (mais peut l'être pour score)
        assert result.exclusion_reason != "stage_alternance"

    def test_disable_foreign_exclusion(self):
        """Désactiver l'exclusion des postes étrangers."""
        config = FilterConfig(exclude_foreign=False)
        text = "CDI Juriste - Genève, Suisse"
        result = is_legal_job_post(text, config=config)
        # Ne devrait pas être exclu pour hors_france
        assert result.exclusion_reason != "hors_france"

    def test_strict_thresholds(self):
        """Seuils plus stricts."""
        config = FilterConfig(recruitment_threshold=0.5, legal_threshold=0.5)
        text = "Juriste CDI Paris"  # Signal faible
        result = is_legal_job_post(text, config=config)
        # Avec des seuils élevés, devrait être rejeté
        assert not result.is_valid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# TESTS NOUVELLES FONCTIONNALITÉS
# =============================================================================

class TestSponsoredExclusion:
    """Tests pour l'exclusion des contenus sponsorisés."""

    def test_sponsored_without_recruitment(self):
        """Post sponsorisé sans recrutement = rejeté."""
        text = "[Sponsorisé] Formation avocat en 2024"
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason in ("contenu_sponsorise", "formation_education", "contenu_promotionnel")

    def test_sponsored_with_recruitment(self):
        """Post sponsorisé AVEC recrutement = accepté."""
        text = "[Sponsorisé] CDI Juriste Paris - Nous recrutons!"
        result = is_legal_job_post(text)
        assert result.is_valid


class TestEmotionalExclusion:
    """Tests pour l'exclusion des posts émotionnels."""

    def test_emotional_post_fier(self):
        """Post 'fier de' sans recrutement = rejeté."""
        text = "Fier de notre équipe juridique! Bravo à tous! 🎉"
        result = is_legal_job_post(text)
        assert not result.is_valid
        assert result.exclusion_reason in ("post_emotionnel", "recrutement_passe", "recrutement_termine")

    def test_emotional_post_felicitations(self):
        """Post félicitations = détecté comme recrutement terminé (annonce arrivée)."""
        text = "Félicitations à notre nouvelle avocate associée!"
        result = is_legal_job_post(text)
        assert not result.is_valid
        # La nouvelle logique détecte "nouvelle avocate" comme annonce d'arrivée (recrutement terminé)
        assert result.exclusion_reason in ("post_emotionnel", "recrutement_termine")

    def test_emotional_with_recruitment(self):
        """Post émotionnel AVEC recrutement = accepté."""
        text = "Fier de notre cabinet qui recrute un avocat en CDI! Poste à pourvoir immédiatement."
        result = is_legal_job_post(text)
        assert result.is_valid


class TestFrenchCitiesExtended:
    """Tests pour les villes françaises supplémentaires."""

    def test_angers(self):
        text = "CDI Juriste Angers - nous recrutons"
        result = is_legal_job_post(text)
        assert result.is_valid

    def test_versailles(self):
        text = "Cabinet Versailles recrute avocat CDI"
        result = is_legal_job_post(text)
        assert result.is_valid

    def test_aix_en_provence(self):
        text = "Juriste CDI Aix-en-Provence recrute"
        result = is_legal_job_post(text)
        assert result.is_valid

    def test_dijon(self):
        text = "Avocat CDI Dijon - Cabinet recrute"
        result = is_legal_job_post(text)
        assert result.is_valid

    def test_orleans(self):
        text = "Nous recrutons un juriste CDI à Orléans"
        result = is_legal_job_post(text)
        assert result.is_valid
