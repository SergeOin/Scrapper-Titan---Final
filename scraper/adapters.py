"""Scraper Adapters - Bridge between existing code and new modules.

This module provides drop-in replacements and adapters that allow
gradual migration from the legacy worker.py and scrape_subprocess.py
to the new modular architecture.

Usage:
    from scraper.adapters import (
        get_next_keywords,        # Replaces _keyword_rotation_index logic
        get_scraping_limits,      # Replaces hardcoded limits
        get_next_interval,        # Replaces fixed autonomous_worker_interval
        should_scrape_now,        # Unified scheduling check
        record_scrape_result,     # Updates all modules after scraping
    )
    
Migration Steps:
    1. Import adapters alongside existing code
    2. Use FeatureFlags to toggle between old/new behavior
    3. Gradually enable new modules
    4. Remove old code once stable

Environment Variables:
    TITAN_USE_KEYWORD_STRATEGY=1   # Enable keyword rotation strategy
    TITAN_USE_PROGRESSIVE_MODE=1   # Enable adaptive limits
    TITAN_USE_SMART_SCHEDULER=1    # Enable smart scheduling
    TITAN_USE_POST_CACHE=1         # Enable deduplication cache
    TITAN_USE_SELECTOR_MANAGER=1   # Enable dynamic selectors
    TITAN_USE_METADATA_EXTRACTOR=1 # Enable robust metadata extraction
    TITAN_USE_UNIFIED_FILTER=1     # Enable unified filtering
    TITAN_USE_ML_INTERFACE=1       # Enable ML classification
    TITAN_ENABLE_PHASE1=1          # Enable Phase 1 (cache + scheduler)
    TITAN_ENABLE_PHASE2=1          # Enable Phase 2 (keywords + progressive)
    TITAN_ENABLE_ALL=1             # Enable all features
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _env_bool(key: str, default: bool = False) -> bool:
    """Read a boolean from environment variable."""
    val = os.environ.get(key, "").lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


# =============================================================================
# Feature Flags - Control which modules are active
# =============================================================================

@dataclass
class FeatureFlags:
    """Feature toggles for gradual module adoption."""
    use_keyword_strategy: bool = False     # Use KeywordStrategy instead of rotation index
    use_progressive_mode: bool = False     # Use ProgressiveModeManager for limits
    use_smart_scheduler: bool = False      # Use SmartScheduler for intervals
    use_post_cache: bool = False           # Use PostCache for deduplication
    use_selector_manager: bool = False     # Use SelectorManager for CSS selectors
    use_metadata_extractor: bool = False   # Use MetadataExtractor for dates/authors
    use_unified_filter: bool = False       # Use unified filter instead of EXCLUSION lists
    use_ml_interface: bool = False         # Use ML classification
    # v2 Micro-session strategy
    use_session_orchestrator: bool = False # Use SessionOrchestrator for micro-sessions
    use_company_whitelist: bool = False    # Use company whitelist instead of keywords
    use_pre_qualifier: bool = False        # Use pre-qualification before full extraction


def _load_flags_from_env() -> FeatureFlags:
    """Load feature flags from environment variables."""
    # Check for phase shortcuts first
    enable_all = _env_bool("TITAN_ENABLE_ALL")
    enable_phase2 = _env_bool("TITAN_ENABLE_PHASE2")
    enable_phase1 = _env_bool("TITAN_ENABLE_PHASE1")
    enable_v2 = _env_bool("TITAN_ENABLE_V2")  # v2: Micro-session strategy

    if enable_all or enable_v2:
        return FeatureFlags(
            use_keyword_strategy=True,
            use_progressive_mode=True,
            use_smart_scheduler=True,
            use_post_cache=True,
            use_selector_manager=True,
            use_metadata_extractor=True,
            use_unified_filter=True,
            use_ml_interface=True,
            # v2 features
            use_session_orchestrator=enable_v2 or enable_all,
            use_company_whitelist=enable_v2 or enable_all,
            use_pre_qualifier=enable_v2 or enable_all,
        )

    if enable_phase2:
        return FeatureFlags(
            use_keyword_strategy=True,
            use_progressive_mode=True,
            use_smart_scheduler=True,
            use_post_cache=True,
            use_selector_manager=False,
            use_metadata_extractor=False,
            use_unified_filter=False,
            use_ml_interface=False,
        )

    if enable_phase1:
        return FeatureFlags(
            use_keyword_strategy=False,
            use_progressive_mode=False,
            use_smart_scheduler=True,
            use_post_cache=True,
            use_selector_manager=False,
            use_metadata_extractor=False,
            use_unified_filter=False,
            use_ml_interface=False,
        )

    # Individual flags
    return FeatureFlags(
        use_keyword_strategy=_env_bool("TITAN_USE_KEYWORD_STRATEGY"),
        use_progressive_mode=_env_bool("TITAN_USE_PROGRESSIVE_MODE"),
        use_smart_scheduler=_env_bool("TITAN_USE_SMART_SCHEDULER"),
        use_post_cache=_env_bool("TITAN_USE_POST_CACHE"),
        use_selector_manager=_env_bool("TITAN_USE_SELECTOR_MANAGER"),
        use_metadata_extractor=_env_bool("TITAN_USE_METADATA_EXTRACTOR"),
        use_unified_filter=_env_bool("TITAN_USE_UNIFIED_FILTER"),
        use_ml_interface=_env_bool("TITAN_USE_ML_INTERFACE"),
        # v2 flags (individual toggle)
        use_session_orchestrator=_env_bool("TITAN_USE_SESSION_ORCHESTRATOR"),
        use_company_whitelist=_env_bool("TITAN_USE_COMPANY_WHITELIST"),
        use_pre_qualifier=_env_bool("TITAN_USE_PRE_QUALIFIER"),
    )


# Global flags instance - loaded from env on import
_feature_flags = _load_flags_from_env()

# Log active features on startup
_active = [k for k, v in _feature_flags.__dict__.items() if v]
if _active:
    logger.info(f"Titan Adapters: Active features: {_active}")
else:
    logger.info("Titan Adapters: All features disabled (legacy mode)")


def get_feature_flags() -> FeatureFlags:
    """Get current feature flags."""
    return _feature_flags


def set_feature_flags(**kwargs) -> None:
    """Update feature flags at runtime."""
    global _feature_flags
    for key, value in kwargs.items():
        if hasattr(_feature_flags, key):
            setattr(_feature_flags, key, value)
            logger.info(f"Feature flag '{key}' set to {value}")
        else:
            logger.warning(f"Unknown feature flag: {key}")


def reload_flags_from_env() -> None:
    """Reload feature flags from environment variables."""
    global _feature_flags
    _feature_flags = _load_flags_from_env()
    _active = [k for k, v in _feature_flags.__dict__.items() if v]
    logger.info(f"Feature flags reloaded. Active: {_active or 'none'}")


def enable_phase1() -> None:
    """Enable Phase 1 features: cache + smart scheduler (low risk)."""
    set_feature_flags(
        use_post_cache=True,
        use_smart_scheduler=True,
    )
    logger.info("Phase 1 enabled: post_cache + smart_scheduler")


def enable_phase2() -> None:
    """Enable Phase 2 features: Phase 1 + keywords + progressive mode."""
    enable_phase1()
    set_feature_flags(
        use_keyword_strategy=True,
        use_progressive_mode=True,
    )
    logger.info("Phase 2 enabled: keyword_strategy + progressive_mode")


def enable_all_features() -> None:
    """Enable all new modules."""
    set_feature_flags(
        use_keyword_strategy=True,
        use_progressive_mode=True,
        use_smart_scheduler=True,
        use_post_cache=True,
        use_selector_manager=True,
        use_metadata_extractor=True,
        use_unified_filter=True,
        use_ml_interface=True,
    )
    logger.info("All features enabled")


# =============================================================================
# Keyword Selection Adapter
# =============================================================================

# Legacy rotation index (fallback)
_legacy_rotation_index: int = 0


def get_next_keywords(
    all_keywords: list[str],
    batch_size: int = 3,
) -> list[str]:
    """Get the next batch of keywords to scrape.
    
    Uses KeywordStrategy if enabled, otherwise falls back to
    legacy rotation index behavior.
    
    Args:
        all_keywords: Complete list of configured keywords
        batch_size: Number of keywords per batch
        
    Returns:
        List of keywords for this scraping cycle
    """
    global _legacy_rotation_index

    if _feature_flags.use_keyword_strategy:
        try:
            from .keyword_strategy import get_keyword_strategy
            strategy = get_keyword_strategy(all_keywords)  # Pass keywords for initialization
            return strategy.get_next_batch(batch_size)
        except Exception as e:
            logger.warning(f"KeywordStrategy failed, using legacy: {e}")

    # Legacy rotation behavior
    total = len(all_keywords)
    if total == 0:
        return []

    start_idx = _legacy_rotation_index % total
    batch = []
    for i in range(batch_size):
        idx = (start_idx + i) % total
        batch.append(all_keywords[idx])

    _legacy_rotation_index = (_legacy_rotation_index + batch_size) % total
    return batch


def record_keyword_result(keyword: str, posts_found: int, had_error: bool = False) -> None:
    """Record the result of scraping a keyword.
    
    Updates KeywordStrategy if enabled.
    """
    if _feature_flags.use_keyword_strategy:
        try:
            from .keyword_strategy import get_keyword_strategy
            strategy = get_keyword_strategy()
            strategy.record_result(
                keyword=keyword,
                posts_found=posts_found,
                had_restriction=had_error,
            )
        except Exception as e:
            logger.warning(f"Failed to record keyword result: {e}")


# =============================================================================
# Scraping Limits Adapter
# =============================================================================

@dataclass
class ScrapingLimits:
    """Current scraping limits."""
    posts_per_run: int
    keywords_per_run: int
    min_interval_seconds: int
    max_posts_per_keyword: int


def get_scraping_limits(
    default_posts_per_run: int = 50,
    default_keywords_per_run: int = 10,
    default_interval: int = 600,
    default_max_per_keyword: int = 10,
) -> ScrapingLimits:
    """Get current scraping limits.
    
    Uses ProgressiveModeManager if enabled, otherwise returns defaults.
    """
    if _feature_flags.use_progressive_mode:
        try:
            from .progressive_mode import get_mode_manager
            manager = get_mode_manager()
            limits = manager.get_limits()
            return ScrapingLimits(
                posts_per_run=limits.posts_per_run,
                keywords_per_run=limits.keywords_per_run,
                min_interval_seconds=limits.min_interval_seconds,
                max_posts_per_keyword=default_max_per_keyword,
            )
        except Exception as e:
            logger.warning(f"ProgressiveModeManager failed, using defaults: {e}")

    return ScrapingLimits(
        posts_per_run=default_posts_per_run,
        keywords_per_run=default_keywords_per_run,
        min_interval_seconds=default_interval,
        max_posts_per_keyword=default_max_per_keyword,
    )


def record_restriction_event(event_type: str = "restriction") -> None:
    """Record a restriction/captcha event.
    
    Updates ProgressiveModeManager if enabled to become more conservative.
    """
    if _feature_flags.use_progressive_mode:
        try:
            from .progressive_mode import get_mode_manager
            manager = get_mode_manager()
            if event_type == "captcha":
                manager.record_captcha()
            else:
                manager.record_restriction()
        except Exception as e:
            logger.warning(f"Failed to record restriction: {e}")


# =============================================================================
# Scheduling Adapter
# =============================================================================

def get_next_interval(
    default_interval: int = 600,
    success: bool = True,
    posts_found: int = 0,
) -> int:
    """Get the next scraping interval in seconds.
    
    Uses SmartScheduler if enabled, otherwise returns default.
    """
    if _feature_flags.use_smart_scheduler:
        try:
            from .smart_scheduler import get_smart_scheduler, SchedulerEvent
            scheduler = get_smart_scheduler()

            # Record the result
            if success:
                scheduler.record_event(SchedulerEvent.SESSION_SUCCESS, {"posts_found": posts_found})
            else:
                scheduler.record_event(SchedulerEvent.SESSION_FAILURE)

            return scheduler.get_next_interval()
        except Exception as e:
            logger.warning(f"SmartScheduler failed, using default: {e}")

    return default_interval


def should_scrape_now() -> tuple[bool, str]:
    """Check if we should start a scraping cycle now.
    
    Returns (should_scrape, reason)
    """
    # v2: Use SessionOrchestrator for micro-session scheduling
    if _feature_flags.use_session_orchestrator:
        try:
            from .session_orchestrator import get_session_orchestrator
            orchestrator = get_session_orchestrator()

            can_scrape, reason = orchestrator.should_scrape_now()
            return can_scrape, reason
        except Exception as e:
            logger.warning(f"SessionOrchestrator check failed: {e}, falling back to SmartScheduler")

    if _feature_flags.use_smart_scheduler:
        try:
            from .smart_scheduler import get_smart_scheduler
            scheduler = get_smart_scheduler()

            status = scheduler.get_status()
            if status.get("paused"):
                return False, "Scheduler is paused"

            if not status.get("in_active_window", True):
                return False, "Outside active hours"

            return True, "OK"
        except Exception as e:
            logger.warning(f"SmartScheduler check failed: {e}")

    return True, "OK (legacy mode)"


def get_session_quota() -> int:
    """Get the post quota for current session.
    
    Returns 0 if no quota (unlimited) or if session orchestrator is disabled.
    """
    if _feature_flags.use_session_orchestrator:
        try:
            from .session_orchestrator import get_session_orchestrator
            orchestrator = get_session_orchestrator()
            return orchestrator.get_session_quota()
        except Exception as e:
            logger.warning(f"SessionOrchestrator quota check failed: {e}")

    return 0  # No quota


def start_scraping_session() -> Optional[dict]:
    """Start a new scraping session with the orchestrator.
    
    Returns session info dict or None if not using orchestrator.
    """
    if _feature_flags.use_session_orchestrator:
        try:
            from .session_orchestrator import get_session_orchestrator
            orchestrator = get_session_orchestrator()
            return orchestrator.start_session()
        except Exception as e:
            logger.warning(f"Failed to start session: {e}")

    return None


def end_scraping_session(posts_collected: int = 0) -> None:
    """End the current scraping session."""
    if _feature_flags.use_session_orchestrator:
        try:
            from .session_orchestrator import get_session_orchestrator
            orchestrator = get_session_orchestrator()
            orchestrator.end_session(posts_collected)
        except Exception as e:
            logger.warning(f"Failed to end session: {e}")


def get_target_companies(max_companies: int = 5) -> list[dict]:
    """Get target companies for this session from whitelist.
    
    Returns list of company dicts with 'name', 'linkedin_url', 'tier'.
    """
    if _feature_flags.use_company_whitelist:
        try:
            from .company_whitelist import get_company_whitelist
            whitelist = get_company_whitelist()
            return whitelist.get_companies_for_session(max_companies)
        except Exception as e:
            logger.warning(f"CompanyWhitelist failed: {e}")

    return []  # Fall back to keyword search


def record_company_visit(company_name: str, posts_found: int = 0) -> None:
    """Record a visit to a company page."""
    if _feature_flags.use_company_whitelist:
        try:
            from .company_whitelist import get_company_whitelist
            whitelist = get_company_whitelist()
            whitelist.record_visit(company_name, posts_found)
        except Exception as e:
            logger.warning(f"Failed to record company visit: {e}")


def pause_scheduler(duration_minutes: int = 60) -> None:
    """Pause scraping for a duration."""
    if _feature_flags.use_smart_scheduler:
        try:
            from .smart_scheduler import get_smart_scheduler
            scheduler = get_smart_scheduler()
            scheduler.pause(duration_minutes)
        except Exception as e:
            logger.warning(f"Failed to pause scheduler: {e}")


def resume_scheduler() -> None:
    """Resume scraping if paused."""
    if _feature_flags.use_smart_scheduler:
        try:
            from .smart_scheduler import get_smart_scheduler
            scheduler = get_smart_scheduler()
            scheduler.resume()
        except Exception as e:
            logger.warning(f"Failed to resume scheduler: {e}")


# =============================================================================
# Deduplication Adapter
# =============================================================================

def is_duplicate_post(
    text: str = "",
    url: str = "",
    post_id: str = "",
    author: str = "",
) -> bool:
    """Check if a post is a duplicate.
    
    Uses PostCache if enabled, otherwise returns False (no dedup).
    """
    if _feature_flags.use_post_cache:
        try:
            from .post_cache import get_post_cache
            cache = get_post_cache()
            return cache.is_duplicate(text=text, url=url, post_id=post_id)
        except Exception as e:
            logger.warning(f"PostCache check failed: {e}")

    return False


def mark_post_seen(
    text: str = "",
    url: str = "",
    post_id: str = "",
    author: str = "",
) -> None:
    """Mark a post as seen for deduplication."""
    if _feature_flags.use_post_cache:
        try:
            from .post_cache import get_post_cache
            cache = get_post_cache()
            cache.mark_processed(text=text, url=url, post_id=post_id, author=author)
        except Exception as e:
            logger.warning(f"Failed to mark post seen: {e}")


# =============================================================================
# Filtering Adapter
# =============================================================================

def should_keep_post(
    text: str,
    author: str = "",
    company: str = "",
    legacy_exclusions: Optional[list[str]] = None,
) -> tuple[bool, str, float]:
    """Determine if a post should be kept.
    
    Uses UnifiedFilter and/or ML if enabled.
    
    Returns:
        (should_keep, category, confidence)
    """
    # Try ML first if enabled
    if _feature_flags.use_ml_interface:
        try:
            from .ml_interface import classify_with_ml, MLCategory
            result = classify_with_ml(text, author, company)
            if result.category == MLCategory.LEGAL_RECRUITMENT and result.confidence > 0.7:
                return True, "legal_recruitment", result.confidence
            elif result.category in (MLCategory.AGENCY_RECRUITMENT, MLCategory.STAGE_ALTERNANCE):
                return False, result.category.value, result.confidence
        except Exception as e:
            logger.warning(f"ML classification failed: {e}")

    # Try unified filter
    if _feature_flags.use_unified_filter:
        try:
            from filters.unified import classify_post, PostCategory
            result = classify_post(text, author, company)
            is_relevant = result.category == PostCategory.RELEVANT
            return is_relevant, result.category.value, result.confidence
        except Exception as e:
            logger.warning(f"UnifiedFilter failed: {e}")

    # Legacy exclusion-based filtering
    if legacy_exclusions:
        text_lower = text.lower()
        for pattern in legacy_exclusions:
            if pattern.lower() in text_lower:
                return False, "excluded_pattern", 1.0

    return True, "no_filter", 0.5


# =============================================================================
# Metadata Extraction Adapter
# =============================================================================

def extract_post_metadata(
    text: str,
    raw_date: str = "",
    raw_author: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Extract structured metadata from post content.
    
    Uses MetadataExtractor if enabled.
    
    Returns dict with: published_at, author, company, etc.
    """
    if _feature_flags.use_metadata_extractor:
        try:
            from .metadata_extractor import get_metadata_extractor
            extractor = get_metadata_extractor()
            metadata = extractor.extract(
                text=text,
                raw_date=raw_date,
                raw_author=raw_author,
                title=title,
            )
            return {
                "published_at": metadata.published_at.isoformat() if metadata.published_at else None,
                "author": metadata.author,
                "company": metadata.company,
                "language": metadata.language,
                "word_count": metadata.word_count,
            }
        except Exception as e:
            logger.warning(f"MetadataExtractor failed: {e}")

    # Basic fallback
    return {
        "published_at": None,
        "author": raw_author,
        "company": None,
        "language": "fr",
        "word_count": len(text.split()),
    }


# =============================================================================
# Selector Adapter
# =============================================================================

def get_selector(name: str, fallback: str = "") -> str:
    """Get a CSS selector by name.
    
    Uses SelectorManager if enabled.
    """
    if _feature_flags.use_selector_manager:
        try:
            from .css_selectors import get_selector_manager
            manager = get_selector_manager()
            return manager.get_selector(name) or fallback
        except Exception as e:
            logger.warning(f"SelectorManager failed: {e}")

    return fallback


def record_selector_success(name: str) -> None:
    """Record a successful selector use."""
    if _feature_flags.use_selector_manager:
        try:
            from .css_selectors import get_selector_manager
            manager = get_selector_manager()
            manager.record_success(name)
        except Exception:
            pass


def record_selector_failure(name: str) -> None:
    """Record a failed selector use."""
    if _feature_flags.use_selector_manager:
        try:
            from .css_selectors import get_selector_manager
            manager = get_selector_manager()
            manager.record_failure(name)
        except Exception:
            pass


# =============================================================================
# Unified Result Recording
# =============================================================================

def record_scrape_result(
    keywords_processed: list[str],
    posts_found: int,
    posts_stored: int,
    had_restriction: bool = False,
    had_captcha: bool = False,
    duration_seconds: float = 0.0,
) -> None:
    """Record the result of a scraping cycle to all enabled modules.
    
    This is the main integration point - call after each scraping cycle.
    """
    # Record keyword results
    if _feature_flags.use_keyword_strategy:
        try:
            from .keyword_strategy import get_keyword_strategy
            strategy = get_keyword_strategy()
            # Record average per keyword
            per_keyword = posts_found // max(1, len(keywords_processed))
            for kw in keywords_processed:
                strategy.record_result(
                    keyword=kw,
                    posts_found=per_keyword,
                    had_restriction=had_restriction,
                )
        except Exception as e:
            logger.warning(f"Failed to record keyword results: {e}")

    # Record progressive mode events
    if _feature_flags.use_progressive_mode:
        try:
            from .progressive_mode import get_mode_manager
            manager = get_mode_manager()
            if had_captcha:
                manager.record_captcha()
            elif had_restriction:
                manager.record_restriction()
            else:
                manager.record_success()
        except Exception as e:
            logger.warning(f"Failed to update progressive mode: {e}")

    # Record scheduler events
    if _feature_flags.use_smart_scheduler:
        try:
            from .smart_scheduler import get_smart_scheduler, SchedulerEvent
            scheduler = get_smart_scheduler()
            if had_restriction or had_captcha:
                event = SchedulerEvent.RESTRICTION_DETECTED if had_restriction else SchedulerEvent.RATE_LIMITED
                scheduler.record_event(event)
            else:
                scheduler.record_event(SchedulerEvent.SESSION_SUCCESS, {"posts_found": posts_stored})
        except Exception as e:
            logger.warning(f"Failed to update scheduler: {e}")

    # FIX BUG-003: Use keywords_count instead of keywords to avoid structlog conflict
    logger.info(
        "scrape_result_recorded",
        keywords_count=len(keywords_processed),
        posts_found=posts_found,
        posts_stored=posts_stored,
        had_restriction=had_restriction,
        had_captcha=had_captcha,
        duration=duration_seconds,
    )


# =============================================================================
# Status and Health
# =============================================================================

def get_adapter_status() -> dict[str, Any]:
    """Get status of all adapter modules."""
    status: dict[str, Any] = {
        "feature_flags": {
            "use_keyword_strategy": _feature_flags.use_keyword_strategy,
            "use_progressive_mode": _feature_flags.use_progressive_mode,
            "use_smart_scheduler": _feature_flags.use_smart_scheduler,
            "use_post_cache": _feature_flags.use_post_cache,
            "use_selector_manager": _feature_flags.use_selector_manager,
            "use_metadata_extractor": _feature_flags.use_metadata_extractor,
            "use_unified_filter": _feature_flags.use_unified_filter,
            "use_ml_interface": _feature_flags.use_ml_interface,
        },
        "modules": {},
    }

    # Check each module
    if _feature_flags.use_keyword_strategy:
        try:
            from .keyword_strategy import get_keyword_strategy
            strategy = get_keyword_strategy()
            status["modules"]["keyword_strategy"] = strategy.get_stats()
        except Exception as e:
            status["modules"]["keyword_strategy"] = {"error": str(e)}

    if _feature_flags.use_progressive_mode:
        try:
            from .progressive_mode import get_mode_manager
            manager = get_mode_manager()
            status["modules"]["progressive_mode"] = manager.get_status()
        except Exception as e:
            status["modules"]["progressive_mode"] = {"error": str(e)}

    if _feature_flags.use_smart_scheduler:
        try:
            from .smart_scheduler import get_smart_scheduler
            scheduler = get_smart_scheduler()
            status["modules"]["smart_scheduler"] = scheduler.get_status()
        except Exception as e:
            status["modules"]["smart_scheduler"] = {"error": str(e)}

    if _feature_flags.use_post_cache:
        try:
            from .post_cache import get_post_cache
            cache = get_post_cache()
            status["modules"]["post_cache"] = cache.get_stats()
        except Exception as e:
            status["modules"]["post_cache"] = {"error": str(e)}

    return status
