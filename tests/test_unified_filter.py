"""Tests for filters/unified.py - Unified filtering configuration."""
import pytest


class TestPostCategory:
    """Tests for PostCategory enum."""
    
    def test_category_values(self):
        from filters.unified import PostCategory
        
        assert str(PostCategory.RELEVANT) == "relevant"
        assert str(PostCategory.AGENCY) == "agency"
        assert str(PostCategory.STAGE_ALTERNANCE) == "stage"


class TestClassificationResult:
    """Tests for ClassificationResult dataclass."""
    
    def test_result_creation(self):
        from filters.unified import ClassificationResult, PostCategory
        
        result = ClassificationResult(
            category=PostCategory.RELEVANT,
            is_relevant=True,
            legal_score=0.8,
            recruitment_score=0.7,
            combined_score=0.76,
            exclusion_reason=None,
            matched_patterns=["juriste", "CDI"],
            confidence=0.9,
        )
        
        assert result.is_relevant is True
        assert result.legal_score == 0.8
    
    def test_result_to_dict(self):
        from filters.unified import ClassificationResult, PostCategory
        
        result = ClassificationResult(
            category=PostCategory.RELEVANT,
            is_relevant=True,
            legal_score=0.8,
            recruitment_score=0.7,
            combined_score=0.76,
            exclusion_reason=None,
            matched_patterns=["juriste"],
            confidence=0.9,
        )
        
        d = result.to_dict()
        
        assert "category" in d
        assert "is_relevant" in d
        assert "legal_score" in d


class TestUnifiedFilterConfig:
    """Tests for UnifiedFilterConfig."""
    
    def test_default_config(self):
        from filters.unified import UnifiedFilterConfig
        
        config = UnifiedFilterConfig()
        
        assert config.legal_weight == 0.6
        assert config.recruitment_weight == 0.4
        assert config.exclude_stage_alternance is True
        assert config.exclude_agencies is True
    
    def test_classify_relevant_post(self):
        from filters.unified import UnifiedFilterConfig, PostCategory
        
        config = UnifiedFilterConfig()
        
        text = """
        Nous recrutons un juriste droit des affaires en CDI pour rejoindre 
        notre équipe juridique. Profil recherché : 3 à 5 ans d'expérience.
        Poste basé à Paris. Envoyez votre CV.
        """
        
        result = config.classify_post(text, author="DRH", company="TotalEnergies")
        
        assert result.is_relevant is True
        assert result.category == PostCategory.RELEVANT
        assert result.legal_score > 0.2
        assert result.recruitment_score > 0.15
    
    def test_classify_agency_post(self):
        from filters.unified import UnifiedFilterConfig, PostCategory
        
        config = UnifiedFilterConfig()
        
        text = """
        Notre client, un groupe international, recherche un juriste corporate.
        Cabinet de recrutement spécialisé dans les profils juridiques.
        Mission pour notre client confidentiel.
        """
        
        result = config.classify_post(text)
        
        assert result.is_relevant is False
        assert result.category == PostCategory.AGENCY
    
    def test_classify_stage_post(self):
        from filters.unified import UnifiedFilterConfig, PostCategory
        
        config = UnifiedFilterConfig()
        
        text = """
        Offre de stage juriste droit social 6 mois.
        Stagiaire recherché pour notre direction juridique.
        Stage de fin d'études possible.
        """
        
        result = config.classify_post(text)
        
        assert result.is_relevant is False
        assert result.category == PostCategory.STAGE_ALTERNANCE
    
    def test_classify_non_recruitment_post(self):
        from filters.unified import UnifiedFilterConfig, PostCategory
        
        config = UnifiedFilterConfig()
        
        text = """
        Conférence sur l'actualité juridique du droit des affaires.
        Webinaire gratuit ce jeudi avec témoignage d'experts.
        Formation continue en droit social.
        """
        
        result = config.classify_post(text)
        
        assert result.is_relevant is False
        # Could be NON_RECRUITMENT or LOW_SCORE depending on thresholds
    
    def test_classify_low_score_post(self):
        from filters.unified import UnifiedFilterConfig, PostCategory
        
        config = UnifiedFilterConfig()
        
        text = """
        Bonne journée à tous ! Le soleil brille sur Paris.
        Café du matin, prêt pour une nouvelle semaine.
        """
        
        result = config.classify_post(text)
        
        assert result.is_relevant is False
        assert result.combined_score < 0.25
    
    def test_custom_exclusions(self):
        from filters.unified import UnifiedFilterConfig
        
        config = UnifiedFilterConfig(
            custom_exclusions={"concurrent_company"}
        )
        
        text = "Nous recrutons un juriste. Rejoignez concurrent_company."
        
        result = config.classify_post(text)
        
        assert result.is_relevant is False
        assert "concurrent_company" in result.matched_patterns
    
    def test_custom_inclusions_boost(self):
        from filters.unified import UnifiedFilterConfig
        
        config = UnifiedFilterConfig(
            custom_inclusions={"titan partners"}
        )
        
        text = "Offre d'emploi chez Titan Partners pour un profil juridique"
        
        result = config.classify_post(text)
        
        assert "+titan partners" in result.matched_patterns
    
    def test_config_hash(self):
        from filters.unified import UnifiedFilterConfig
        
        config1 = UnifiedFilterConfig()
        config2 = UnifiedFilterConfig()
        
        assert config1.get_config_hash() == config2.get_config_hash()
        
        config3 = UnifiedFilterConfig(min_legal_score=0.5)
        
        assert config1.get_config_hash() != config3.get_config_hash()
    
    def test_get_stats(self):
        from filters.unified import UnifiedFilterConfig
        
        config = UnifiedFilterConfig()
        stats = config.get_stats()
        
        assert "version" in stats
        assert "counts" in stats
        assert "total_patterns" in stats
        assert stats["counts"]["legal_roles"] > 50


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_classify_post(self):
        from filters.unified import classify_post
        
        result = classify_post(
            text="Juriste en CDI recherché pour notre équipe",
            author="DRH",
            company="Société Générale",
        )
        
        assert hasattr(result, "is_relevant")
        assert hasattr(result, "category")
    
    def test_is_relevant_post(self):
        from filters.unified import is_relevant_post
        
        # Relevant post
        relevant = is_relevant_post(
            "Nous recrutons un juriste confirmé en CDI pour notre direction juridique"
        )
        
        # Not relevant
        not_relevant = is_relevant_post(
            "Belle journée ensoleillée sur Paris"
        )
        
        assert relevant is True
        assert not_relevant is False
    
    def test_singleton_pattern(self):
        from filters.unified import get_filter_config, reset_filter_config
        
        reset_filter_config()
        
        config1 = get_filter_config()
        config2 = get_filter_config()
        
        assert config1 is config2
        
        reset_filter_config()


class TestPatternSets:
    """Tests for pattern sets completeness."""
    
    def test_legal_roles_non_empty(self):
        from filters.unified import LEGAL_ROLES
        
        assert len(LEGAL_ROLES) > 50
        assert "juriste" in LEGAL_ROLES
        assert "avocat" in LEGAL_ROLES
        assert "legal counsel" in LEGAL_ROLES
    
    def test_recruitment_signals_non_empty(self):
        from filters.unified import RECRUITMENT_SIGNALS
        
        assert len(RECRUITMENT_SIGNALS) > 30
        assert "nous recrutons" in RECRUITMENT_SIGNALS
        assert "cdi" in RECRUITMENT_SIGNALS
    
    def test_agency_patterns_non_empty(self):
        from filters.unified import AGENCY_PATTERNS
        
        assert len(AGENCY_PATTERNS) > 50
        assert "cabinet de recrutement" in AGENCY_PATTERNS
        assert "michael page" in AGENCY_PATTERNS
    
    def test_stage_patterns_non_empty(self):
        from filters.unified import STAGE_ALTERNANCE_PATTERNS
        
        assert len(STAGE_ALTERNANCE_PATTERNS) > 20
        assert "stage" in STAGE_ALTERNANCE_PATTERNS
        assert "alternance" in STAGE_ALTERNANCE_PATTERNS
    
    def test_backward_compatibility_aliases(self):
        from filters.unified import (
            LEGAL_ROLE_KEYWORDS,
            RECRUITMENT_SIGNALS_LIST,
            EXCLUSION_AGENCY_PATTERNS,
            EXCLUSION_STAGE_ALTERNANCE,
        )
        
        assert len(LEGAL_ROLE_KEYWORDS) > 0
        assert len(RECRUITMENT_SIGNALS_LIST) > 0
        assert len(EXCLUSION_AGENCY_PATTERNS) > 0
        assert len(EXCLUSION_STAGE_ALTERNANCE) > 0
