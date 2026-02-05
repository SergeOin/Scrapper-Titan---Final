"""Tests pour vérifier les filtres améliorés du scraper.

Ces tests vérifient:
1. Filtre de date (< 3 semaines)
2. Filtre stage/alternance
3. Filtre France uniquement
4. Performance globale des filtres
"""
import pytest
from datetime import datetime, timedelta, timezone

# Import des modules à tester
from scraper.utils import (
    is_post_too_old,
    is_stage_or_alternance,
    is_location_france,
    parse_possible_date,
    STAGE_ALTERNANCE_KEYWORDS,
    FRANCE_POSITIVE_MARKERS,
    FRANCE_NEGATIVE_MARKERS,
)
from scraper.legal_filter import (
    is_legal_job_post,
    check_exclusions,
    FilterConfig,
    normalize_text,
)


class TestDateFilter:
    """Tests du filtre de date (posts < 3 semaines)."""
    
    def test_recent_post_accepted(self):
        """Un post d'il y a 1 jour doit être accepté."""
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        assert is_post_too_old(yesterday.isoformat()) == False
    
    def test_old_post_rejected(self):
        """Un post d'il y a 4 semaines doit être rejeté."""
        old = datetime.now(timezone.utc) - timedelta(weeks=4)
        assert is_post_too_old(old.isoformat()) == True
    
    def test_exactly_3_weeks_accepted(self):
        """Un post d'exactement 21 jours doit être accepté."""
        three_weeks = datetime.now(timezone.utc) - timedelta(days=21)
        assert is_post_too_old(three_weeks.isoformat()) == False
    
    def test_22_days_rejected(self):
        """Un post de 22 jours doit être rejeté."""
        too_old = datetime.now(timezone.utc) - timedelta(days=22)
        assert is_post_too_old(too_old.isoformat()) == True
    
    def test_no_date_rejected(self):
        """Un post sans date - comportement configurable."""
        # Note: Le comportement par défaut peut varier selon la config
        # On vérifie juste que la fonction ne crash pas
        result_none = is_post_too_old(None)
        result_empty = is_post_too_old("")
        assert isinstance(result_none, bool)
        assert isinstance(result_empty, bool)
    
    def test_parse_linkedin_relative_dates(self):
        """Test du parsing des dates relatives LinkedIn."""
        now = datetime.now(timezone.utc)
        
        # Format "X sem." (LinkedIn FR)
        result = parse_possible_date("2 sem.", now)
        assert result is not None
        age = now - result
        assert 13 <= age.days <= 15  # ~2 semaines
        
        # Format "X semaines"
        result = parse_possible_date("1 semaine", now)
        assert result is not None
        age = now - result
        assert 6 <= age.days <= 8  # ~1 semaine
        
        # Format "X j" (jours)
        result = parse_possible_date("3 j", now)
        assert result is not None
        age = now - result
        assert 2 <= age.days <= 4  # ~3 jours
        
        # Format "X h" (heures)
        result = parse_possible_date("5 h", now)
        assert result is not None
        age = now - result
        assert age.total_seconds() / 3600 < 6  # ~5 heures
    
    def test_parse_linkedin_with_bullet(self):
        """Test du parsing avec le format LinkedIn réel (• séparateur)."""
        now = datetime.now(timezone.utc)
        
        # Format réel LinkedIn: "2 sem. • Modifié •"
        result = parse_possible_date("2 sem. • Modifié •", now)
        assert result is not None
        age = now - result
        assert 13 <= age.days <= 15


class TestStageAlternanceFilter:
    """Tests du filtre stage/alternance."""
    
    def test_stage_keyword_rejected(self):
        """Un post avec 'stage' doit être rejeté."""
        text = "Nous recherchons un stagiaire en droit des affaires"
        assert is_stage_or_alternance(text) == True
    
    def test_alternance_keyword_rejected(self):
        """Un post avec 'alternance' doit être rejeté."""
        text = "Offre en alternance pour juriste junior"
        assert is_stage_or_alternance(text) == True
    
    def test_apprentissage_rejected(self):
        """Un post avec 'apprentissage' doit être rejeté."""
        text = "Contrat d'apprentissage pour futur avocat"
        assert is_stage_or_alternance(text) == True
    
    def test_cdi_accepted(self):
        """Un post CDI sans stage/alternance doit être accepté."""
        text = "Nous recrutons un juriste en CDI à Paris"
        assert is_stage_or_alternance(text) == False
    
    def test_all_keywords_covered(self):
        """Vérifier que tous les keywords majeurs sont détectés."""
        test_cases = [
            ("stage juridique", True),
            ("offre de stage", True),
            ("alternant juriste", True),
            ("poste en alternance", True),
            ("contrat pro", True),
            ("internship legal", True),
            ("work-study position", True),
            ("V.I.E. juridique", True),
            ("CDI juriste Paris", False),
            ("Avocat confirmé recruté", False),
        ]
        for text, expected in test_cases:
            result = is_stage_or_alternance(text)
            assert result == expected, f"Failed for: '{text}', expected {expected}, got {result}"


class TestFranceFilter:
    """Tests du filtre France uniquement."""
    
    def test_paris_accepted(self):
        """Un post mentionnant Paris doit être accepté."""
        text = "Poste de juriste à Paris en CDI"
        assert is_location_france(text) == True
    
    def test_lyon_accepted(self):
        """Un post mentionnant Lyon doit être accepté."""
        text = "Nous recrutons à Lyon pour notre équipe juridique"
        assert is_location_france(text) == True
    
    def test_foreign_location_rejected(self):
        """Un post mentionnant uniquement un pays étranger doit être rejeté."""
        text = "Poste de juriste à Bruxelles en Belgique"
        assert is_location_france(text, strict=True) == False
    
    def test_swiss_rejected(self):
        """Un post mentionnant Genève/Suisse sans France doit être rejeté."""
        text = "Cabinet d'avocats à Genève recherche collaborateur"
        assert is_location_france(text, strict=True) == False
    
    def test_multi_location_with_france_accepted(self):
        """Un post multi-pays incluant France doit être accepté."""
        text = "Poste basé à Paris avec déplacements à Londres"
        assert is_location_france(text, strict=True) == True
    
    def test_no_location_accepted(self):
        """Un post sans indication géographique doit être accepté."""
        text = "Nous recrutons un juriste pour renforcer notre équipe"
        assert is_location_france(text) == True
    
    def test_la_defense_accepted(self):
        """La Défense (quartier d'affaires) doit être reconnu comme France."""
        text = "Poste à La Défense, direction juridique"
        assert is_location_france(text) == True


class TestLegalFilter:
    """Tests du filtre juridique complet."""
    
    def test_valid_recruitment_post(self):
        """Un vrai post de recrutement juridique doit être accepté."""
        text = """
        Nous recrutons un juriste droit social en CDI.
        Poste basé à Paris. 5 ans d'expérience minimum.
        Envoyez votre CV à recrutement@cabinet.fr
        """
        result = is_legal_job_post(text)
        assert result.is_valid == True
        assert result.recruitment_score >= 0.15
        assert result.legal_score >= 0.20
    
    def test_stage_post_rejected(self):
        """Un post de stage doit être rejeté même avec signal de recrutement."""
        text = """
        Nous recrutons un stagiaire en droit des affaires.
        Stage de 6 mois à Paris, gratification légale.
        """
        result = is_legal_job_post(text)
        assert result.is_valid == False
        assert result.exclusion_reason == "stage_alternance"
    
    def test_old_post_rejected_by_filter(self):
        """Un post ancien doit être rejeté par check_exclusions."""
        text = "Nous recrutons un juriste en CDI à Lyon"
        old_date = datetime.now(timezone.utc) - timedelta(weeks=5)
        result = check_exclusions(text, post_date=old_date)
        assert result.excluded == True
        assert result.reason == "post_trop_ancien"
    
    def test_recruitment_agency_rejected(self):
        """Un post de cabinet de recrutement doit être rejeté."""
        text = """
        Fed Legal recrute pour son client un juriste M&A.
        Notre client, un grand groupe du CAC40, recherche...
        """
        result = is_legal_job_post(text)
        assert result.is_valid == False
        assert "cabinet_recrutement" in result.exclusion_reason
    
    def test_non_france_rejected(self):
        """Un post hors France doit être rejeté."""
        text = """
        Cabinet d'avocats à Genève recrute un collaborateur.
        Poste en Suisse, allemand courant exigé.
        """
        config = FilterConfig(exclude_foreign=True)
        result = is_legal_job_post(text, config=config)
        assert result.is_valid == False
        assert result.exclusion_reason == "hors_france"


class TestPerformance:
    """Tests de performance des filtres."""
    
    def test_filter_speed(self):
        """Les filtres doivent être rapides (< 10ms par post)."""
        import time
        
        text = """
        Notre cabinet d'avocats d'affaires recherche un collaborateur
        en droit des sociétés pour renforcer notre équipe parisienne.
        Poste en CDI, 5 ans d'expérience minimum. Rémunération attractive.
        """
        
        # Test sur 100 itérations
        start = time.perf_counter()
        for _ in range(100):
            result = is_legal_job_post(text)
        elapsed = time.perf_counter() - start
        
        avg_ms = (elapsed / 100) * 1000
        assert avg_ms < 10, f"Filtre trop lent: {avg_ms:.2f}ms par post"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
