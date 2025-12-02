"""
Filters package for Titan Partners LinkedIn Scraper.

This package contains all filtering modules for legal recruitment posts.
"""
from .juridique import (
    JuridiqueConfig,
    get_default_config,
    LEGAL_ROLE_KEYWORDS,
    RECRUITMENT_SIGNALS,
    INTERNAL_RECRUITMENT_PATTERNS,
    EXCLUSION_AGENCY_PATTERNS,
    EXCLUSION_EXTERNAL_RECRUITMENT,
    EXCLUSION_NON_RECRUITMENT_CONTENT,
    EXCLUSION_AUTHOR_TYPES,
)

__all__ = [
    "JuridiqueConfig",
    "get_default_config",
    "LEGAL_ROLE_KEYWORDS",
    "RECRUITMENT_SIGNALS",
    "INTERNAL_RECRUITMENT_PATTERNS",
    "EXCLUSION_AGENCY_PATTERNS",
    "EXCLUSION_EXTERNAL_RECRUITMENT",
    "EXCLUSION_NON_RECRUITMENT_CONTENT",
    "EXCLUSION_AUTHOR_TYPES",
]
