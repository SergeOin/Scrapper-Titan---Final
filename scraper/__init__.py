"""Scraper package.

Contiendra la logique d'initialisation (bootstrap), utilitaires, et le worker de scraping.
"""

from . import utils  # noqa: F401 (expose utilitaires de haut niveau si nécessaire)
from . import legal_filter  # noqa: F401 (expose le filtre juridique)

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
