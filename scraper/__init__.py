"""Scraper package for Titan Partners LinkedIn Legal Recruitment Scraper.

Ce package contient la logique d'initialisation (bootstrap), utilitaires, 
worker de scraping et modules de filtrage juridique.

MODULES:
    - bootstrap: Configuration et contexte applicatif
    - worker: Extraction des posts LinkedIn
    - legal_filter: Filtrage des offres d'emploi juridiques
    - legal_classifier: Classification des intentions de recrutement
    - linkedin: Analyse spécifique LinkedIn (type d'auteur, etc.)
    - stats: Statistiques et logging détaillé
    - utils: Fonctions utilitaires

USAGE:
    from scraper import is_legal_job_post, FilterConfig
    from scraper.linkedin import LinkedInPostAnalyzer, is_relevant_for_titan
    from scraper.stats import ScraperStats
"""

from . import utils  # noqa: F401 (expose utilitaires de haut niveau si nécessaire)
from . import legal_filter  # noqa: F401 (expose le filtre juridique)
from . import legal_classifier  # noqa: F401 (expose le classificateur)

# Expose les éléments clés du filtre légal pour faciliter l'import
from .legal_filter import (  # noqa: F401
    is_legal_job_post,
    FilterResult,
    FilterConfig,
    DEFAULT_FILTER_CONFIG,
)

# Expose le helper de configuration depuis bootstrap
from .bootstrap import (  # noqa: F401
    build_filter_config,
    FilterSessionStats,
)

# Expose le classificateur
from .legal_classifier import (  # noqa: F401
    classify_legal_post,
    LegalClassification,
    LEGAL_ROLE_KEYWORDS,
)

# Expose le module LinkedIn
try:
    from .linkedin import (  # noqa: F401
        LinkedInPostAnalyzer,
        PostAnalysisResult,
        AuthorType,
        PostRelevance,
        is_relevant_for_titan,
        get_post_summary,
    )
except ImportError:
    # Fallback si filters n'est pas accessible
    pass

# Expose le module de stats
try:
    from .stats import (  # noqa: F401
        ScraperStats,
        SessionReport,
        log_filtering_decision,
        EXCLUSION_CATEGORIES,
    )
except ImportError:
    pass

__all__ = [
    # Legal filter
    "is_legal_job_post",
    "FilterResult", 
    "FilterConfig",
    "DEFAULT_FILTER_CONFIG",
    # Legal classifier
    "classify_legal_post",
    "LegalClassification",
    "LEGAL_ROLE_KEYWORDS",
    # LinkedIn analyzer
    "LinkedInPostAnalyzer",
    "PostAnalysisResult",
    "AuthorType",
    "PostRelevance",
    "is_relevant_for_titan",
    "get_post_summary",
    # Stats
    "ScraperStats",
    "SessionReport",
    "log_filtering_decision",
    "EXCLUSION_CATEGORIES",
    # Bootstrap
    "build_filter_config",
    "FilterSessionStats",
]
