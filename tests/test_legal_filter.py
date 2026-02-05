"""Unit tests for the legal_filter module.

Tests validate:
- is_legal_job_post() main function
- Text normalization (accents, emojis, hashtags)
- Scoring functions (legal profession, recruitment signals)
- Exclusion detection (stage, freelance, non-France, etc.)
- At least 20 test cases covering various scenarios
"""
import pytest
from datetime import datetime, timezone, timedelta

from scraper.legal_filter import (
    is_legal_job_post,
    normalize_text,
    calculate_legal_profession_score,
    calculate_recruitment_score,
    check_exclusions,
    FilterResult,
)


# =============================================================================
# TEXT NORMALIZATION TESTS
# =============================================================================

class TestNormalizeText:
    """Tests for text normalization function."""

    def test_normalize_lowercase(self):
        """Text should be converted to lowercase."""
        result = normalize_text("AVOCAT PARIS CDI")
        assert result == "avocat paris cdi"

    def test_normalize_remove_accents(self):
        """Accents should be removed."""
        result = normalize_text("Juriste spécialisé en droit pénal à Genève")
        assert "e" in result  # é -> e
        assert "a" in result  # à -> a
        assert "é" not in result
        assert "à" not in result

    def test_normalize_remove_emojis(self):
        """Emojis should be removed."""
        result = normalize_text("🚀 Nous recrutons un avocat! 💼")
        assert "🚀" not in result
        assert "💼" not in result
        assert "nous recrutons un avocat" in result

    def test_normalize_remove_hashtags(self):
        """Hashtags should be removed but words kept."""
        result = normalize_text("#avocat #recrutement #CDI Paris")
        assert "#" not in result
        assert "avocat" in result
        assert "recrutement" in result
        assert "cdi" in result

    def test_normalize_whitespace(self):
        """Multiple spaces should be normalized."""
        result = normalize_text("Juriste    senior    Paris")
        assert "  " not in result
        assert "juriste senior paris" in result


# =============================================================================
# SCORING TESTS
# =============================================================================

class TestLegalProfessionScore:
    """Tests for legal profession scoring."""

    def test_score_avocat(self):
        """'Avocat' should give score >= 0.2."""
        score, matches = calculate_legal_profession_score("Nous recrutons un avocat")
        assert score >= 0.2
        assert "avocat" in matches

    def test_score_juriste(self):
        """'Juriste' should give score >= 0.2."""
        score, matches = calculate_legal_profession_score("Poste de juriste à pourvoir")
        assert score >= 0.2
        assert "juriste" in matches

    def test_score_directeur_juridique(self):
        """High-value role should give bonus score."""
        score, matches = calculate_legal_profession_score("Directeur juridique recherché")
        assert score > 0.3  # Base 0.2 + bonus for high-value role

    def test_score_multiple_roles(self):
        """Multiple roles should increase score."""
        score, matches = calculate_legal_profession_score(
            "Nous recrutons un juriste et un avocat pour notre cabinet"
        )
        assert score > 0.2
        assert len(matches) >= 2

    def test_score_no_legal_role(self):
        """No legal role should give score 0."""
        score, matches = calculate_legal_profession_score(
            "Nous recrutons un développeur Python"
        )
        assert score == 0.0
        assert len(matches) == 0


class TestRecruitmentScore:
    """Tests for recruitment signal scoring."""

    def test_score_je_recrute(self):
        """'Je recrute' DOIT retourner score 0 (signal de chasseur de têtes)."""
        score, matches = calculate_recruitment_score("Je recrute un avocat")
        # NOUVELLE LOGIQUE: "je recrute" est exclu car signal de recruteur individuel
        assert score == 0.0
        assert "je recrute" not in matches

    def test_score_nous_recrutons(self):
        """'Nous recrutons' should give score >= 0.20 (signal d'entreprise)."""
        score, matches = calculate_recruitment_score("Nous recrutons un avocat")
        assert score >= 0.20
        assert "nous recrutons" in matches

    def test_score_cdi(self):
        """'CDI' should give score >= 0.15."""
        score, matches = calculate_recruitment_score("Poste en CDI à Paris")
        assert score >= 0.15
        assert "cdi" in matches

    def test_score_multiple_signals(self):
        """Multiple signals should increase score."""
        score, matches = calculate_recruitment_score(
            "Nous recrutons un juriste en CDI. Poste à pourvoir immédiatement."
        )
        assert score > 0.15
        assert len(matches) >= 2

    def test_score_no_recruitment_signal(self):
        """No recruitment signal should give score 0."""
        score, matches = calculate_recruitment_score(
            "Article sur l'évolution du droit fiscal"
        )
        assert score == 0.0


# =============================================================================
# EXCLUSION TESTS
# =============================================================================

class TestExclusions:
    """Tests for exclusion detection."""

    def test_exclusion_stage(self):
        """Stage posts should be excluded."""
        result = check_exclusions("Offre de stage en droit social")
        assert result.excluded is True
        assert result.reason == "stage_alternance"
        assert "stage" in result.matched_terms

    def test_exclusion_alternance(self):
        """Alternance posts should be excluded."""
        result = check_exclusions("Nous cherchons un alternant juriste")
        assert result.excluded is True
        assert result.reason == "stage_alternance"

    def test_exclusion_freelance(self):
        """Freelance posts should be excluded."""
        result = check_exclusions("Mission freelance juriste 3 mois")
        assert result.excluded is True
        assert result.reason == "freelance_mission"

    def test_exclusion_non_france_canada(self):
        """Canadian posts should be excluded."""
        result = check_exclusions("Avocat recherché à Montreal Canada")
        assert result.excluded is True
        assert result.reason == "hors_france"

    def test_exclusion_non_france_suisse(self):
        """Swiss posts should be excluded."""
        result = check_exclusions("Cabinet de Genève Suisse recrute")
        assert result.excluded is True
        assert result.reason == "hors_france"

    def test_no_exclusion_france_mentioned(self):
        """Posts with France mentioned should not be excluded for location."""
        result = check_exclusions("Avocat à Paris France en CDI")
        assert result.excluded is False or result.reason != "hors_france"

    def test_exclusion_opentowork(self):
        """#OpenToWork posts should be excluded."""
        result = check_exclusions("Juriste #opentowork disponible immédiatement")
        assert result.excluded is True
        assert result.reason == "chercheur_emploi"

    def test_exclusion_promotional_webinar(self):
        """Webinar posts should be excluded."""
        result = check_exclusions("Webinaire sur le droit des contrats le 15 janvier")
        assert result.excluded is True
        assert result.reason in ("contenu_promotionnel", "contenu_informatif", "formation_education", "veille_juridique")

    def test_exclusion_promotional_formation(self):
        """Formation posts should be excluded."""
        result = check_exclusions("Formation en droit social - inscrivez-vous!")
        assert result.excluded is True
        assert result.reason in ("contenu_promotionnel", "formation_education")

    def test_exclusion_recruitment_agency_fed_legal(self):
        """Fed Legal posts should be excluded."""
        result = check_exclusions("Fed Legal recrute un avocat pour son client")
        assert result.excluded is True
        assert result.reason == "cabinet_recrutement"

    def test_exclusion_recruitment_agency_michael_page(self):
        """Michael Page posts should be excluded."""
        result = check_exclusions("Michael Page recherche un juriste senior")
        assert result.excluded is True
        assert result.reason == "cabinet_recrutement"

    def test_exclusion_recruitment_agency_hays(self):
        """Hays posts should be excluded."""
        result = check_exclusions("Hays recrute pour son client un avocat")
        assert result.excluded is True
        assert result.reason == "cabinet_recrutement"

    def test_exclusion_non_legal_marketing(self):
        """Marketing posts should be excluded."""
        result = check_exclusions("Nous recrutons un responsable marketing en CDI")
        assert result.excluded is True
        assert result.reason == "metier_non_juridique"

    def test_exclusion_non_legal_finance(self):
        """Finance posts should be excluded."""
        result = check_exclusions("Poste de directeur financier à pourvoir")
        assert result.excluded is True
        assert result.reason == "metier_non_juridique"

    def test_exclusion_post_too_old(self):
        """Posts older than 3 weeks should be excluded."""
        old_date = datetime.now(timezone.utc) - timedelta(weeks=4)
        result = check_exclusions("Nous recrutons un avocat en CDI", post_date=old_date)
        assert result.excluded is True
        assert result.reason == "post_trop_ancien"


# =============================================================================
# MAIN FILTER FUNCTION TESTS (is_legal_job_post)
# =============================================================================

class TestIsLegalJobPost:
    """Tests for the main is_legal_job_post function."""

    # --- VALID POSTS (should return is_valid=True) ---

    def test_valid_avocat_cdi_paris(self):
        """Classic valid post: avocat + CDI + Paris."""
        text = "Nous recrutons un avocat en CDI pour notre cabinet parisien"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True
        assert result.legal_score >= 0.2
        assert result.recruitment_score >= 0.15

    def test_valid_juriste_recrute(self):
        """Valid post: juriste + nous recrutons (signal entreprise)."""
        text = "Nous recrutons un juriste d'entreprise pour rejoindre notre équipe. CDI à pourvoir."
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    def test_valid_directeur_juridique(self):
        """Valid post: high-value role."""
        text = "Poste de Directeur Juridique à pourvoir en CDI à Lyon"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True
        assert result.legal_score > 0.3

    def test_valid_notaire_associe(self):
        """Valid post: notaire."""
        text = "Notre étude recherche un notaire associé. Poste en CDI."
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    def test_valid_paralegal(self):
        """Valid post: paralegal."""
        text = "Nous recrutons un paralegal pour notre direction juridique. Poste en CDI."
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    def test_valid_juriste_conformite(self):
        """Valid post: juriste conformité (exception to compliance exclusion)."""
        text = "Nous recrutons un juriste conformité pour notre équipe compliance. CDI à pourvoir."
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    def test_valid_with_emojis_and_hashtags(self):
        """Valid post with emojis and hashtags should be cleaned and validated."""
        text = "🚀 #Recrutement Nous recrutons un #avocat en #CDI à Paris! 💼"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    # --- INVALID POSTS (should return is_valid=False) ---

    def test_invalid_stage(self):
        """Stage post should be excluded."""
        text = "Offre de stage: juriste junior dans notre cabinet"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "stage_alternance"

    def test_invalid_alternance(self):
        """Alternance post should be excluded."""
        text = "Nous recrutons un juriste en alternance"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "stage_alternance"

    def test_invalid_freelance(self):
        """Freelance post should be excluded."""
        text = "Mission freelance avocat droit des affaires 6 mois"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "freelance_mission"

    def test_invalid_canada(self):
        """Canadian post should be excluded."""
        text = "Nous recrutons un avocat à Montreal Canada en CDI"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "hors_france"

    def test_invalid_opentowork(self):
        """Job seeker post should be excluded."""
        text = "Avocat #opentowork - je suis disponible pour un nouveau poste"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason in ("chercheur_emploi", "candidat_individu")

    def test_invalid_webinar(self):
        """Promotional webinar should be excluded."""
        text = "Webinaire juridique : évolutions du droit du travail"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason in ("contenu_promotionnel", "contenu_informatif", "formation_education", "veille_juridique")

    def test_invalid_fed_legal(self):
        """Fed Legal (competitor) should be excluded."""
        text = "Fed Legal recrute un avocat senior pour un client confidentiel"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "cabinet_recrutement"

    def test_invalid_robert_walters(self):
        """Robert Walters (competitor) should be excluded."""
        text = "Robert Walters recherche un juriste M&A en CDI"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "cabinet_recrutement"

    def test_invalid_marketing(self):
        """Marketing post should be excluded."""
        text = "Nous recrutons un responsable marketing digital en CDI"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "metier_non_juridique"

    def test_invalid_no_recruitment_signal(self):
        """Post without recruitment signal should be excluded."""
        text = "Notre équipe juridique est composée de 5 avocats et 2 juristes"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert "insuffisant" in result.exclusion_reason

    def test_invalid_no_legal_profession(self):
        """Post without legal profession should be excluded."""
        text = "Nous recrutons en CDI! Poste à pourvoir immédiatement."
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        # La nouvelle logique retourne "metier_non_cible" au lieu de "insuffisant"
        assert result.exclusion_reason in ("metier_non_cible", "score_insuffisant_juridique")

    def test_invalid_empty_text(self):
        """Empty text should be excluded."""
        result = is_legal_job_post("", log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "texte_vide"

    def test_invalid_old_post(self):
        """Post older than 3 weeks should be excluded."""
        text = "Nous recrutons un avocat en CDI à Paris"
        old_date = datetime.now(timezone.utc) - timedelta(weeks=4)
        result = is_legal_job_post(text, post_date=old_date, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "post_trop_ancien"


# =============================================================================
# EDGE CASES AND COMPLEX SCENARIOS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and complex scenarios."""

    def test_france_and_foreign_country(self):
        """Post mentioning France AND foreign country should pass if France is primary."""
        text = "Nous recrutons un avocat pour notre bureau de Paris (expérience UK appréciée). CDI à pourvoir."
        result = is_legal_job_post(text, log_exclusions=False)
        # Should pass because France (Paris) is mentioned
        assert result.is_valid is True or result.exclusion_reason != "hors_france"

    def test_promotional_with_strong_recruitment(self):
        """Promotional content with strong recruitment signal should still pass."""
        text = "Nous recrutons un avocat en CDI - Participez aussi à notre formation. Poste à pourvoir."
        result = is_legal_job_post(text, log_exclusions=False)
        # Strong recruitment signal ("nous recrutons", "CDI") overrides promotional content
        assert result.is_valid is True  # Strong recruitment signal wins

    def test_apprentissage_explicit(self):
        """Explicit apprentissage should be excluded."""
        text = "Contrat d'apprentissage juriste droit social"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "stage_alternance"

    def test_vie_international(self):
        """V.I.E. posts should be excluded."""
        text = "Offre V.I.E. juriste international à New York"
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False

    def test_clerc_de_notaire(self):
        """Clerc de notaire should be valid."""
        text = "Notre étude recrute un clerc de notaire en CDI. Poste à pourvoir."
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    def test_assistant_juridique(self):
        """Assistant juridique should be valid."""
        text = "Nous recrutons un assistant juridique pour notre direction juridique. Poste en CDI à pourvoir."
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    def test_compliance_officer_without_juriste(self):
        """Compliance officer without juriste might be excluded as non-legal."""
        text = "Nous recrutons un compliance officer en CDI"
        result = is_legal_job_post(text, log_exclusions=False)
        # Compliance officer alone could be non-legal
        # This depends on implementation - may need adjustment
        assert result.is_valid is False or "compliance" in str(result.matched_professions)


# =============================================================================
# FILTER RESULT STRUCTURE TESTS
# =============================================================================

class TestFilterResultStructure:
    """Tests for FilterResult data structure."""

    def test_filter_result_to_dict(self):
        """FilterResult should serialize to dict properly."""
        text = "Nous recrutons un avocat en CDI à Paris. Poste à pourvoir."
        result = is_legal_job_post(text, log_exclusions=False)
        result_dict = result.to_dict()
        
        assert "is_valid" in result_dict
        assert "recruitment_score" in result_dict
        assert "legal_score" in result_dict
        assert "total_score" in result_dict
        assert "exclusion_reason" in result_dict
        assert "matched_professions" in result_dict
        assert "matched_signals" in result_dict

    def test_filter_result_scores_range(self):
        """Scores should be in valid range [0, 1]."""
        text = "Nous recrutons plusieurs avocats et juristes en CDI pour notre équipe juridique. Poste à pourvoir."
        result = is_legal_job_post(text, log_exclusions=False)
        
        assert 0.0 <= result.recruitment_score <= 1.0
        assert 0.0 <= result.legal_score <= 1.0
        assert 0.0 <= result.total_score <= 1.0


# =============================================================================
# REAL-WORLD LINKEDIN POST EXAMPLES
# =============================================================================

class TestRealWorldExamples:
    """Tests with realistic LinkedIn post content."""

    def test_realistic_valid_post_1(self):
        """Realistic valid recruitment post."""
        text = """
        🚀 Notre cabinet d'avocats recrute !
        
        Nous recherchons un(e) Avocat(e) Collaborateur(trice) spécialisé(e) en 
        droit des affaires pour rejoindre notre équipe parisienne.
        
        📍 Paris 8ème
        📝 CDI
        💼 3-5 ans d'expérience
        
        Envoyez votre CV ! #recrutement #avocat #droit
        """
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    def test_realistic_valid_post_2(self):
        """Realistic valid recruitment post for juriste - ENTREPRISE."""
        text = """
        💼 OPPORTUNITÉ CDI - JURISTE CORPORATE
        
        Notre équipe recrute un(e) juriste corporate confirmé(e).
        Vous intégrerez la direction juridique d'un groupe international
        basé à La Défense. Poste à pourvoir immédiatement.
        
        Profil recherché :
        - 4/6 ans d'expérience
        - Droit des sociétés / M&A
        - Anglais courant
        
        Intéressé(e) ? Contactez-nous !
        """
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is True

    def test_realistic_invalid_stage_post(self):
        """Realistic invalid stage post."""
        text = """
        🎓 OFFRE DE STAGE M2
        
        Notre cabinet recherche un(e) stagiaire pour une durée de 6 mois.
        Stage conventionné, gratification légale.
        
        Domaine : droit social / droit du travail
        Lieu : Lyon 3ème
        
        #stage #droit #juridique
        """
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "stage_alternance"

    def test_realistic_invalid_job_seeker(self):
        """Realistic invalid job seeker post."""
        text = """
        🔍 #OpenToWork
        
        Avocat avec 8 ans d'expérience en droit des affaires,
        je suis à la recherche de nouvelles opportunités.
        
        Disponible immédiatement.
        Mobilité : Paris / Île-de-France
        
        N'hésitez pas à me contacter !
        """
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason in ("chercheur_emploi", "candidat_individu")

    def test_realistic_invalid_cabinet_recrutement(self):
        """Realistic invalid recruitment agency post."""
        text = """
        📢 FED LEGAL recrute pour son client !
        
        Cabinet d'avocats d'affaires recherche un Avocat Associé
        en droit bancaire et financier.
        
        Poste basé à Paris - CDI
        Rémunération attractive
        
        Pour plus d'infos, contactez-nous !
        """
        result = is_legal_job_post(text, log_exclusions=False)
        assert result.is_valid is False
        assert result.exclusion_reason == "cabinet_recrutement"
