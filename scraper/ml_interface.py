"""ML Interface for plug-in machine learning classification.

This module provides a clean interface for integrating ML-based post
classification without adding heavy dependencies to the core project.

Design principles:
- Zero mandatory ML dependencies (optional import)
- Fallback to heuristic scoring if ML unavailable
- Easy to plug in different models
- Async-compatible for production use

Supported backends:
1. Local scikit-learn model (pickle)
2. HuggingFace Transformers (optional)
3. External API (OpenAI, Claude, custom)
4. Simple rule-based fallback

Integration:
    - Call classify_with_ml() with post text
    - System automatically uses best available backend

Author: Titan Scraper Team
"""
from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# ML RESULT
# =============================================================================

class MLCategory(str, Enum):
    """ML classification categories."""
    LEGAL_RECRUITMENT = "legal_recruitment"
    AGENCY_RECRUITMENT = "agency_recruitment"
    STAGE_ALTERNANCE = "stage_alternance"
    NON_RECRUITMENT = "non_recruitment"
    IRRELEVANT = "irrelevant"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value


@dataclass
class MLResult:
    """Result from ML classification."""
    category: MLCategory
    confidence: float  # 0-1
    probabilities: Dict[str, float] = field(default_factory=dict)
    model_name: str = "unknown"
    inference_time_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_relevant(self) -> bool:
        """Check if classified as relevant for Titan Partners."""
        return self.category == MLCategory.LEGAL_RECRUITMENT and self.confidence >= 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": str(self.category),
            "confidence": round(self.confidence, 3),
            "is_relevant": self.is_relevant,
            "probabilities": self.probabilities,
            "model_name": self.model_name,
            "inference_time_ms": self.inference_time_ms,
            "metadata": self.metadata,
        }


# =============================================================================
# BASE CLASSIFIER INTERFACE
# =============================================================================

class BaseMLClassifier(ABC):
    """Abstract base class for ML classifiers."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Model name."""
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if classifier is ready to use."""
        pass
    
    @abstractmethod
    def classify(self, text: str, author: str = "", company: str = "") -> MLResult:
        """Classify a post.
        
        Args:
            text: Post content
            author: Author name/title
            company: Company name
            
        Returns:
            MLResult with classification
        """
        pass
    
    def classify_batch(self, posts: List[Dict[str, str]]) -> List[MLResult]:
        """Classify multiple posts. Override for efficiency.
        
        Args:
            posts: List of dicts with 'text', 'author', 'company' keys
            
        Returns:
            List of MLResults
        """
        return [
            self.classify(
                p.get("text", ""),
                p.get("author", ""),
                p.get("company", ""),
            )
            for p in posts
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get classifier statistics."""
        return {
            "name": self.name,
            "is_available": self.is_available,
        }


# =============================================================================
# HEURISTIC FALLBACK CLASSIFIER
# =============================================================================

class HeuristicClassifier(BaseMLClassifier):
    """Rule-based fallback classifier using unified filters.
    
    This is always available and provides consistent results.
    """
    
    def __init__(self):
        self._total_classifications = 0
        self._category_counts: Dict[str, int] = {}
    
    @property
    def name(self) -> str:
        return "heuristic_v1"
    
    @property
    def is_available(self) -> bool:
        return True
    
    def classify(self, text: str, author: str = "", company: str = "") -> MLResult:
        start_time = time.time()
        
        try:
            # Import unified filter
            from filters.unified import classify_post, PostCategory
            
            result = classify_post(text, author, company)
            
            # Map PostCategory to MLCategory
            category_map = {
                PostCategory.RELEVANT: MLCategory.LEGAL_RECRUITMENT,
                PostCategory.AGENCY: MLCategory.AGENCY_RECRUITMENT,
                PostCategory.STAGE_ALTERNANCE: MLCategory.STAGE_ALTERNANCE,
                PostCategory.NON_RECRUITMENT: MLCategory.NON_RECRUITMENT,
                PostCategory.FREELANCE: MLCategory.NON_RECRUITMENT,
                PostCategory.EXTERNAL: MLCategory.AGENCY_RECRUITMENT,
                PostCategory.LOW_SCORE: MLCategory.IRRELEVANT,
                PostCategory.EXCLUDED: MLCategory.IRRELEVANT,
            }
            
            ml_category = category_map.get(result.category, MLCategory.UNKNOWN)
            
            # Build probabilities from scores
            probabilities = {
                "legal_recruitment": result.combined_score,
                "irrelevant": 1.0 - result.combined_score,
            }
            
            inference_time = int((time.time() - start_time) * 1000)
            self._total_classifications += 1
            self._category_counts[str(ml_category)] = self._category_counts.get(str(ml_category), 0) + 1
            
            return MLResult(
                category=ml_category,
                confidence=result.confidence,
                probabilities=probabilities,
                model_name=self.name,
                inference_time_ms=inference_time,
                metadata={
                    "legal_score": result.legal_score,
                    "recruitment_score": result.recruitment_score,
                    "matched_patterns": result.matched_patterns[:5],
                },
            )
            
        except ImportError:
            # Unified filter not available - minimal fallback
            return MLResult(
                category=MLCategory.UNKNOWN,
                confidence=0.0,
                model_name=self.name,
                inference_time_ms=int((time.time() - start_time) * 1000),
            )
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            **super().get_stats(),
            "total_classifications": self._total_classifications,
            "category_distribution": self._category_counts,
        }


# =============================================================================
# SKLEARN CLASSIFIER
# =============================================================================

class SklearnClassifier(BaseMLClassifier):
    """Scikit-learn based classifier with pickle model.
    
    Expects a model trained on post text that outputs:
    - legal_recruitment
    - agency_recruitment
    - stage_alternance
    - non_recruitment
    - irrelevant
    """
    
    def __init__(self, model_path: Optional[str] = None):
        self._model_path = model_path or self._default_path()
        self._model = None
        self._vectorizer = None
        self._is_loaded = False
        self._load_attempt = False
    
    @staticmethod
    def _default_path() -> str:
        if os.name == 'nt':
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            return str(Path(base) / "TitanScraper" / "models" / "classifier.pkl")
        else:
            return str(Path.home() / ".local" / "share" / "TitanScraper" / "models" / "classifier.pkl")
    
    @property
    def name(self) -> str:
        return "sklearn_v1"
    
    @property
    def is_available(self) -> bool:
        if not self._load_attempt:
            self._try_load()
        return self._is_loaded
    
    def _try_load(self) -> None:
        """Try to load the model."""
        self._load_attempt = True
        
        if not Path(self._model_path).exists():
            logger.debug("sklearn_model_not_found", path=self._model_path)
            return
        
        try:
            import pickle
            with open(self._model_path, 'rb') as f:
                data = pickle.load(f)
            
            if isinstance(data, dict):
                self._model = data.get("model")
                self._vectorizer = data.get("vectorizer")
            else:
                self._model = data
            
            self._is_loaded = self._model is not None
            logger.info("sklearn_model_loaded", path=self._model_path)
            
        except Exception as e:
            logger.warning("sklearn_model_load_failed", error=str(e))
    
    def classify(self, text: str, author: str = "", company: str = "") -> MLResult:
        if not self.is_available:
            return MLResult(category=MLCategory.UNKNOWN, confidence=0.0, model_name=self.name)
        
        start_time = time.time()
        
        try:
            # Prepare input
            full_text = f"{text} {author} {company}".strip()
            
            # Vectorize if needed
            if self._vectorizer:
                features = self._vectorizer.transform([full_text])
            else:
                features = [full_text]
            
            # Predict
            prediction = self._model.predict(features)[0]
            
            # Get probabilities if available
            probabilities = {}
            if hasattr(self._model, 'predict_proba'):
                probs = self._model.predict_proba(features)[0]
                classes = self._model.classes_
                probabilities = {str(c): float(p) for c, p in zip(classes, probs)}
            
            # Map to MLCategory
            category = MLCategory(prediction) if prediction in [c.value for c in MLCategory] else MLCategory.UNKNOWN
            confidence = probabilities.get(prediction, 0.5)
            
            return MLResult(
                category=category,
                confidence=confidence,
                probabilities=probabilities,
                model_name=self.name,
                inference_time_ms=int((time.time() - start_time) * 1000),
            )
            
        except Exception as e:
            logger.warning("sklearn_classify_failed", error=str(e))
            return MLResult(
                category=MLCategory.UNKNOWN,
                confidence=0.0,
                model_name=self.name,
                inference_time_ms=int((time.time() - start_time) * 1000),
            )


# =============================================================================
# EXTERNAL API CLASSIFIER
# =============================================================================

@dataclass
class APIConfig:
    """Configuration for external API classifier."""
    endpoint: str = ""
    api_key: str = ""
    timeout_seconds: int = 5
    model_name: str = "gpt-3.5-turbo"
    max_retries: int = 2
    
    @classmethod
    def from_env(cls) -> "APIConfig":
        return cls(
            endpoint=os.environ.get("ML_API_ENDPOINT", ""),
            api_key=os.environ.get("ML_API_KEY", ""),
            model_name=os.environ.get("ML_MODEL_NAME", "gpt-3.5-turbo"),
        )


class APIClassifier(BaseMLClassifier):
    """External API-based classifier (OpenAI, custom, etc.)."""
    
    PROMPT_TEMPLATE = """Classify the following LinkedIn post into one of these categories:
- legal_recruitment: A company is recruiting for a legal/juriste position internally
- agency_recruitment: A recruitment agency is recruiting for a client
- stage_alternance: Stage, internship, or alternance offer
- non_recruitment: Not a job offer (article, event, announcement)
- irrelevant: Not related to legal field

Post text:
{text}

Author: {author}
Company: {company}

Respond with JSON only:
{{"category": "<category>", "confidence": <0.0-1.0>}}"""
    
    def __init__(self, config: Optional[APIConfig] = None):
        self._config = config or APIConfig.from_env()
        self._is_available_cached: Optional[bool] = None
    
    @property
    def name(self) -> str:
        return f"api_{self._config.model_name}"
    
    @property
    def is_available(self) -> bool:
        if self._is_available_cached is not None:
            return self._is_available_cached
        
        self._is_available_cached = bool(
            self._config.endpoint and 
            self._config.api_key
        )
        return self._is_available_cached
    
    def classify(self, text: str, author: str = "", company: str = "") -> MLResult:
        if not self.is_available:
            return MLResult(category=MLCategory.UNKNOWN, confidence=0.0, model_name=self.name)
        
        start_time = time.time()
        
        try:
            import httpx
            
            prompt = self.PROMPT_TEMPLATE.format(
                text=text[:1000],  # Limit text length
                author=author or "Unknown",
                company=company or "Unknown",
            )
            
            # Make API call (simplified - adjust for actual API)
            response = httpx.post(
                self._config.endpoint,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._config.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                },
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
            
            # Parse response
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Parse JSON from response
            parsed = json.loads(content)
            category_str = parsed.get("category", "unknown")
            confidence = float(parsed.get("confidence", 0.5))
            
            category = MLCategory(category_str) if category_str in [c.value for c in MLCategory] else MLCategory.UNKNOWN
            
            return MLResult(
                category=category,
                confidence=confidence,
                model_name=self.name,
                inference_time_ms=int((time.time() - start_time) * 1000),
                metadata={"raw_response": content},
            )
            
        except Exception as e:
            logger.warning("api_classify_failed", error=str(e))
            return MLResult(
                category=MLCategory.UNKNOWN,
                confidence=0.0,
                model_name=self.name,
                inference_time_ms=int((time.time() - start_time) * 1000),
            )


# =============================================================================
# ML INTERFACE (FACADE)
# =============================================================================

class MLInterface:
    """Unified ML interface with automatic backend selection."""
    
    def __init__(self, preferred_backends: Optional[List[str]] = None):
        """Initialize ML interface.
        
        Args:
            preferred_backends: List of backends to try in order.
                Options: "sklearn", "api", "heuristic"
                Default: ["sklearn", "heuristic"]
        """
        self._backends: Dict[str, BaseMLClassifier] = {
            "heuristic": HeuristicClassifier(),
            "sklearn": SklearnClassifier(),
            "api": APIClassifier(),
        }
        
        self._preferred = preferred_backends or ["sklearn", "heuristic"]
        self._active_backend: Optional[BaseMLClassifier] = None
        self._fallback_backend = self._backends["heuristic"]
        
        self._stats = {
            "total_calls": 0,
            "backend_usage": {},
            "fallback_count": 0,
        }
        
        self._select_backend()
    
    def _select_backend(self) -> None:
        """Select best available backend."""
        for name in self._preferred:
            backend = self._backends.get(name)
            if backend and backend.is_available:
                self._active_backend = backend
                logger.info("ml_backend_selected", backend=backend.name)
                return
        
        # Fallback to heuristic
        self._active_backend = self._fallback_backend
        logger.info("ml_using_fallback", backend=self._fallback_backend.name)
    
    def classify(self, text: str, author: str = "", company: str = "") -> MLResult:
        """Classify a post using best available backend.
        
        Args:
            text: Post content
            author: Author name/title
            company: Company name
            
        Returns:
            MLResult with classification
        """
        self._stats["total_calls"] += 1
        
        if self._active_backend:
            try:
                result = self._active_backend.classify(text, author, company)
                
                # Track usage
                backend_name = self._active_backend.name
                self._stats["backend_usage"][backend_name] = \
                    self._stats["backend_usage"].get(backend_name, 0) + 1
                
                return result
                
            except Exception as e:
                logger.warning("ml_classify_failed_using_fallback", error=str(e))
                self._stats["fallback_count"] += 1
        
        # Fallback
        return self._fallback_backend.classify(text, author, company)
    
    def classify_batch(self, posts: List[Dict[str, str]]) -> List[MLResult]:
        """Classify multiple posts.
        
        Args:
            posts: List of dicts with 'text', 'author', 'company' keys
            
        Returns:
            List of MLResults
        """
        if self._active_backend:
            try:
                return self._active_backend.classify_batch(posts)
            except Exception as e:
                logger.warning("ml_batch_failed", error=str(e))
        
        return [
            self.classify(p.get("text", ""), p.get("author", ""), p.get("company", ""))
            for p in posts
        ]
    
    def register_backend(self, name: str, backend: BaseMLClassifier) -> None:
        """Register a custom backend.
        
        Args:
            name: Backend name
            backend: Classifier instance
        """
        self._backends[name] = backend
        logger.info("ml_backend_registered", name=name)
    
    def switch_backend(self, name: str) -> bool:
        """Switch to a specific backend.
        
        Args:
            name: Backend name
            
        Returns:
            True if switch successful
        """
        backend = self._backends.get(name)
        if backend and backend.is_available:
            self._active_backend = backend
            logger.info("ml_backend_switched", backend=name)
            return True
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get ML interface status."""
        available_backends = {
            name: backend.is_available
            for name, backend in self._backends.items()
        }
        
        return {
            "active_backend": self._active_backend.name if self._active_backend else None,
            "available_backends": available_backends,
            "preferred_order": self._preferred,
            "stats": self._stats.copy(),
        }
    
    def get_backend_stats(self) -> Dict[str, Any]:
        """Get detailed stats for all backends."""
        return {
            name: backend.get_stats()
            for name, backend in self._backends.items()
        }


# =============================================================================
# SINGLETON
# =============================================================================

_ml_instance: Optional[MLInterface] = None


def get_ml_interface(preferred_backends: Optional[List[str]] = None) -> MLInterface:
    """Get or create ML interface singleton."""
    global _ml_instance
    if _ml_instance is None:
        _ml_instance = MLInterface(preferred_backends)
    return _ml_instance


def reset_ml_interface() -> None:
    """Reset singleton (for testing)."""
    global _ml_instance
    _ml_instance = None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def classify_with_ml(text: str, author: str = "", company: str = "") -> MLResult:
    """Convenience function for ML classification."""
    return get_ml_interface().classify(text, author, company)


def is_relevant_ml(text: str, author: str = "", company: str = "") -> bool:
    """Convenience function to check relevance with ML."""
    return get_ml_interface().classify(text, author, company).is_relevant


__all__ = [
    # Classes
    "MLInterface",
    "MLResult",
    "MLCategory",
    "BaseMLClassifier",
    "HeuristicClassifier",
    "SklearnClassifier",
    "APIClassifier",
    "APIConfig",
    
    # Functions
    "get_ml_interface",
    "reset_ml_interface",
    "classify_with_ml",
    "is_relevant_ml",
]
