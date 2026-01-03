"""Tests for scraper/ml_interface.py - ML classification plug-in."""
import pytest


class TestMLCategory:
    """Tests for MLCategory enum."""
    
    def test_category_values(self):
        from scraper.ml_interface import MLCategory
        
        assert str(MLCategory.LEGAL_RECRUITMENT) == "legal_recruitment"
        assert str(MLCategory.AGENCY_RECRUITMENT) == "agency_recruitment"
        assert str(MLCategory.STAGE_ALTERNANCE) == "stage_alternance"


class TestMLResult:
    """Tests for MLResult dataclass."""
    
    def test_result_creation(self):
        from scraper.ml_interface import MLResult, MLCategory
        
        result = MLResult(
            category=MLCategory.LEGAL_RECRUITMENT,
            confidence=0.85,
            model_name="test_model",
        )
        
        assert result.category == MLCategory.LEGAL_RECRUITMENT
        assert result.confidence == 0.85
    
    def test_is_relevant_property(self):
        from scraper.ml_interface import MLResult, MLCategory
        
        relevant = MLResult(
            category=MLCategory.LEGAL_RECRUITMENT,
            confidence=0.7,
        )
        assert relevant.is_relevant is True
        
        low_confidence = MLResult(
            category=MLCategory.LEGAL_RECRUITMENT,
            confidence=0.3,
        )
        assert low_confidence.is_relevant is False
        
        wrong_category = MLResult(
            category=MLCategory.AGENCY_RECRUITMENT,
            confidence=0.9,
        )
        assert wrong_category.is_relevant is False
    
    def test_to_dict(self):
        from scraper.ml_interface import MLResult, MLCategory
        
        result = MLResult(
            category=MLCategory.LEGAL_RECRUITMENT,
            confidence=0.85,
            probabilities={"legal": 0.85, "other": 0.15},
            model_name="test",
            inference_time_ms=50,
        )
        
        d = result.to_dict()
        
        assert "category" in d
        assert "confidence" in d
        assert "is_relevant" in d
        assert "model_name" in d
        assert "inference_time_ms" in d


class TestHeuristicClassifier:
    """Tests for HeuristicClassifier."""
    
    def test_classifier_availability(self):
        from scraper.ml_interface import HeuristicClassifier
        
        classifier = HeuristicClassifier()
        
        assert classifier.is_available is True
        assert classifier.name == "heuristic_v1"
    
    def test_classify_legal_recruitment(self):
        from scraper.ml_interface import HeuristicClassifier, MLCategory
        
        classifier = HeuristicClassifier()
        
        text = """
        Nous recrutons un juriste droit des affaires en CDI.
        Rejoignez notre équipe juridique. Profil recherché: 5 ans.
        """
        
        result = classifier.classify(text)
        
        assert result.category == MLCategory.LEGAL_RECRUITMENT
        assert result.confidence > 0.5
    
    def test_classify_agency(self):
        from scraper.ml_interface import HeuristicClassifier, MLCategory
        
        classifier = HeuristicClassifier()
        
        text = """
        Notre client, un grand groupe, recherche un juriste.
        Cabinet de recrutement spécialisé. Client confidentiel.
        """
        
        result = classifier.classify(text)
        
        assert result.category == MLCategory.AGENCY_RECRUITMENT
    
    def test_classify_stage(self):
        from scraper.ml_interface import HeuristicClassifier, MLCategory
        
        classifier = HeuristicClassifier()
        
        text = """
        Stage juriste droit social 6 mois.
        Offre de stage pour étudiant en droit.
        """
        
        result = classifier.classify(text)
        
        assert result.category == MLCategory.STAGE_ALTERNANCE
    
    def test_inference_time_tracked(self):
        from scraper.ml_interface import HeuristicClassifier
        
        classifier = HeuristicClassifier()
        
        result = classifier.classify("Test text")
        
        assert result.inference_time_ms >= 0
    
    def test_stats_tracking(self):
        from scraper.ml_interface import HeuristicClassifier
        
        classifier = HeuristicClassifier()
        
        classifier.classify("Text 1")
        classifier.classify("Text 2")
        classifier.classify("Text 3")
        
        stats = classifier.get_stats()
        
        assert stats["total_classifications"] == 3


class TestSklearnClassifier:
    """Tests for SklearnClassifier."""
    
    def test_classifier_not_available_without_model(self):
        from scraper.ml_interface import SklearnClassifier
        
        classifier = SklearnClassifier(model_path="/nonexistent/path.pkl")
        
        assert classifier.is_available is False
    
    def test_classify_returns_unknown_when_unavailable(self):
        from scraper.ml_interface import SklearnClassifier, MLCategory
        
        classifier = SklearnClassifier(model_path="/nonexistent/path.pkl")
        
        result = classifier.classify("Some text")
        
        assert result.category == MLCategory.UNKNOWN
        assert result.confidence == 0.0


class TestAPIClassifier:
    """Tests for APIClassifier."""
    
    def test_classifier_not_available_without_config(self):
        from scraper.ml_interface import APIClassifier, APIConfig
        
        config = APIConfig(endpoint="", api_key="")
        classifier = APIClassifier(config=config)
        
        assert classifier.is_available is False
    
    def test_classify_returns_unknown_when_unavailable(self):
        from scraper.ml_interface import APIClassifier, APIConfig, MLCategory
        
        config = APIConfig(endpoint="", api_key="")
        classifier = APIClassifier(config=config)
        
        result = classifier.classify("Some text")
        
        assert result.category == MLCategory.UNKNOWN


class TestMLInterface:
    """Tests for unified MLInterface."""
    
    def test_interface_creation(self):
        from scraper.ml_interface import MLInterface
        
        interface = MLInterface()
        
        assert interface._active_backend is not None
    
    def test_default_backend_is_heuristic(self):
        from scraper.ml_interface import MLInterface
        
        # Without sklearn model, should fallback to heuristic
        interface = MLInterface(preferred_backends=["sklearn", "heuristic"])
        
        assert "heuristic" in interface._active_backend.name
    
    def test_classify_uses_active_backend(self):
        from scraper.ml_interface import MLInterface
        
        interface = MLInterface()
        
        result = interface.classify("Nous recrutons un juriste en CDI")
        
        assert result.model_name is not None
        assert result.category is not None
    
    def test_classify_batch(self):
        from scraper.ml_interface import MLInterface
        
        interface = MLInterface()
        
        posts = [
            {"text": "Post 1 juriste CDI", "author": "A1"},
            {"text": "Post 2 avocat recrutement", "author": "A2"},
            {"text": "Post 3 stage droit", "author": "A3"},
        ]
        
        results = interface.classify_batch(posts)
        
        assert len(results) == 3
        assert all(r.model_name is not None for r in results)
    
    def test_switch_backend(self):
        from scraper.ml_interface import MLInterface
        
        interface = MLInterface()
        
        # Switch to heuristic (should always work)
        success = interface.switch_backend("heuristic")
        
        assert success is True
        assert "heuristic" in interface._active_backend.name
    
    def test_switch_backend_unavailable(self):
        from scraper.ml_interface import MLInterface
        
        interface = MLInterface()
        
        # Try to switch to sklearn (no model available)
        success = interface.switch_backend("sklearn")
        
        assert success is False
    
    def test_get_status(self):
        from scraper.ml_interface import MLInterface
        
        interface = MLInterface()
        
        status = interface.get_status()
        
        assert "active_backend" in status
        assert "available_backends" in status
        assert "stats" in status
    
    def test_get_backend_stats(self):
        from scraper.ml_interface import MLInterface
        
        interface = MLInterface()
        
        stats = interface.get_backend_stats()
        
        assert "heuristic" in stats
        assert "sklearn" in stats
        assert "api" in stats
    
    def test_stats_tracking(self):
        from scraper.ml_interface import MLInterface
        
        interface = MLInterface()
        
        interface.classify("Text 1")
        interface.classify("Text 2")
        
        status = interface.get_status()
        
        assert status["stats"]["total_calls"] == 2


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_classify_with_ml(self):
        from scraper.ml_interface import classify_with_ml, reset_ml_interface
        
        reset_ml_interface()
        
        result = classify_with_ml(
            text="Juriste CDI recherché",
            author="DRH",
            company="Total",
        )
        
        assert result is not None
        assert hasattr(result, "category")
        assert hasattr(result, "confidence")
    
    def test_is_relevant_ml(self):
        from scraper.ml_interface import is_relevant_ml, reset_ml_interface
        
        reset_ml_interface()
        
        relevant = is_relevant_ml(
            "Nous recrutons un juriste confirmé en CDI pour notre direction juridique"
        )
        
        not_relevant = is_relevant_ml(
            "Belle journée ensoleillée"
        )
        
        assert relevant is True
        assert not_relevant is False
    
    def test_singleton_pattern(self):
        from scraper.ml_interface import get_ml_interface, reset_ml_interface
        
        reset_ml_interface()
        
        ml1 = get_ml_interface()
        ml2 = get_ml_interface()
        
        assert ml1 is ml2
        
        reset_ml_interface()


class TestCustomBackend:
    """Tests for custom backend registration."""
    
    def test_register_custom_backend(self):
        from scraper.ml_interface import (
            MLInterface, BaseMLClassifier, MLResult, MLCategory,
            reset_ml_interface
        )
        
        class CustomClassifier(BaseMLClassifier):
            @property
            def name(self) -> str:
                return "custom_test"
            
            @property
            def is_available(self) -> bool:
                return True
            
            def classify(self, text, author="", company=""):
                return MLResult(
                    category=MLCategory.LEGAL_RECRUITMENT,
                    confidence=0.99,
                    model_name=self.name,
                )
        
        reset_ml_interface()
        interface = MLInterface()
        
        interface.register_backend("custom", CustomClassifier())
        success = interface.switch_backend("custom")
        
        assert success is True
        
        result = interface.classify("Any text")
        
        assert result.model_name == "custom_test"
        assert result.confidence == 0.99
