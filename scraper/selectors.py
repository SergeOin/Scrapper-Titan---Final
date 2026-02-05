"""Dynamic selector management with fallback and success tracking.

This module provides resilient CSS selector handling for LinkedIn scraping:
- Primary + fallback selectors for each element type
- Success rate tracking per selector
- Dynamic ordering based on recent reliability
- Automatic alerting when all selectors fail

Architecture:
    SelectorManager is a singleton initialized at worker startup.
    It tracks success/failure for each selector and reorders them dynamically.
    Stats are persisted to SQLite for continuity across restarts.

Usage:
    from scraper.selectors import get_selector_manager
    
    manager = get_selector_manager()
    posts = await manager.find_posts(page)
    author = await manager.find_author(post_element)

Integration:
    - Initialize in scraper/bootstrap.py during context creation
    - Use in scraper/worker.py and scraper/scrape_subprocess.py
    - Expose via /api/selector_health endpoint

Author: Titan Scraper Team
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Callable
import os

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# SELECTOR DEFINITIONS - Editable configuration
# =============================================================================

@dataclass
class SelectorConfig:
    """Configuration for a single selector with metadata."""
    css: str
    name: str
    priority: int = 0  # Lower = higher priority (used as tiebreaker)
    min_expected: int = 0  # Minimum expected matches (0 = any)
    is_fallback: bool = False


# Post containers (article/div wrapping each post)
# 2025-01: LinkedIn utilise maintenant div[role="listitem"] pour les résultats de recherche
POST_CONTAINER_SELECTORS: list[SelectorConfig] = [
    SelectorConfig('div[role="listitem"]', "listitem_role", priority=0),  # NEW 2025: Search results
    SelectorConfig("article[data-urn*='urn:li:activity']", "article_data_urn", priority=1),
    SelectorConfig("div[data-urn*='urn:li:activity:']", "div_data_urn", priority=2),
    SelectorConfig("div.feed-shared-update-v2", "feed_shared_update", priority=3),
    SelectorConfig("div.update-components-feed-update", "update_components", priority=4, is_fallback=True),
    SelectorConfig("div.occludable-update", "occludable_update", priority=5, is_fallback=True),
]

# Author name within a post
AUTHOR_SELECTORS: list[SelectorConfig] = [
    SelectorConfig("span.update-components-actor__title span[dir='ltr'] span[aria-hidden='true']", "actor_title_hidden", priority=0),
    SelectorConfig("span.update-components-actor__title span[dir='ltr']", "actor_title_ltr", priority=1),
    SelectorConfig("span.feed-shared-actor__name span[dir='ltr']", "feed_actor_name", priority=2),
    SelectorConfig("span.update-components-actor__name span[dir='ltr']", "actor_name_ltr", priority=3),
    SelectorConfig("span.update-components-actor__title", "actor_title_generic", priority=4, is_fallback=True),
    SelectorConfig("span.feed-shared-actor__name", "feed_actor_generic", priority=5, is_fallback=True),
]

# Post text content
TEXT_SELECTORS: list[SelectorConfig] = [
    SelectorConfig("div.update-components-text", "update_components_text", priority=0),
    SelectorConfig("div.feed-shared-update-v2__description-wrapper", "description_wrapper", priority=1),
    SelectorConfig("span.break-words", "break_words", priority=2),
    SelectorConfig("div[dir='ltr']", "div_ltr", priority=3, is_fallback=True),
]

# Date/timestamp
DATE_SELECTORS: list[SelectorConfig] = [
    SelectorConfig("time[datetime]", "time_datetime", priority=0),
    SelectorConfig("time", "time_generic", priority=1),
    SelectorConfig("span.update-components-actor__sub-description", "sub_description", priority=2),
    SelectorConfig("span.feed-shared-actor__sub-description", "feed_sub_description", priority=3),
    SelectorConfig("a.update-components-actor__sub-description-link", "sub_description_link", priority=4),
    SelectorConfig("span[class*='sub-description']", "any_sub_description", priority=5, is_fallback=True),
    SelectorConfig("span[class*='timestamp']", "timestamp_class", priority=6, is_fallback=True),
]

# Permalink (link to full post)
PERMALINK_SELECTORS: list[SelectorConfig] = [
    SelectorConfig("a[href*='/feed/update/']", "feed_update_link", priority=0),
    SelectorConfig("a.app-aware-link[href*='activity']", "app_aware_activity", priority=1),
    SelectorConfig("a[href*='/posts/']", "posts_link", priority=2),
    SelectorConfig("a[href*='activity']", "activity_link", priority=3, is_fallback=True),
]

# Company/organization
COMPANY_SELECTORS: list[SelectorConfig] = [
    SelectorConfig("span.update-components-actor__company", "actor_company", priority=0),
    SelectorConfig("span.update-components-actor__supplementary-info", "supplementary_info", priority=1),
    SelectorConfig("span.update-components-actor__description span[aria-hidden='true']", "actor_desc_hidden", priority=2),
    SelectorConfig("span.update-components-actor__description", "actor_description", priority=3),
    SelectorConfig("div.update-components-actor__meta span", "actor_meta_span", priority=4, is_fallback=True),
    SelectorConfig("span.feed-shared-actor__description", "feed_actor_desc", priority=5, is_fallback=True),
]


# =============================================================================
# SELECTOR STATS TRACKING
# =============================================================================

@dataclass
class SelectorStats:
    """Statistics for a single selector."""
    name: str
    css: str
    successes: int = 0
    failures: int = 0
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    avg_match_count: float = 0.0
    
    @property
    def total_attempts(self) -> int:
        return self.successes + self.failures
    
    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.5  # Neutral for untested selectors
        return self.successes / self.total_attempts
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "css": self.css,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 3),
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "avg_match_count": round(self.avg_match_count, 2),
        }


# =============================================================================
# SELECTOR MANAGER
# =============================================================================

class SelectorManager:
    """Manages CSS selectors with dynamic fallback and success tracking.
    
    Thread-safe singleton that:
    - Tries selectors in order of success rate
    - Tracks success/failure per selector
    - Persists stats to SQLite
    - Alerts when all selectors fail
    """
    
    _instance: Optional['SelectorManager'] = None
    _lock: Optional['asyncio.Lock'] = None  # Lazy init to avoid circular import with socket/selectors
    
    @classmethod
    def _get_lock(cls) -> 'asyncio.Lock':
        """Get or create the asyncio lock (lazy initialization)."""
        if cls._lock is None:
            import asyncio as _asyncio
            cls._lock = _asyncio.Lock()
        return cls._lock
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize with optional custom DB path."""
        self.db_path = db_path or self._default_db_path()
        self._stats: dict[str, SelectorStats] = {}
        self._alert_callbacks: list[Callable] = []
        self._initialized = False
        
    @staticmethod
    def _default_db_path() -> str:
        """Get default path for selector stats DB."""
        if os.name == 'nt':  # Windows
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            return str(Path(base) / "TitanScraper" / "selector_stats.sqlite3")
        else:
            return str(Path.home() / ".local" / "share" / "TitanScraper" / "selector_stats.sqlite3")
    
    async def initialize(self) -> None:
        """Initialize manager and load persisted stats."""
        if self._initialized:
            return
        
        async with self._get_lock():
            if self._initialized:
                return
            
            # Ensure directory exists
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Initialize all selector configs
            all_selectors = (
                POST_CONTAINER_SELECTORS + AUTHOR_SELECTORS + TEXT_SELECTORS +
                DATE_SELECTORS + PERMALINK_SELECTORS + COMPANY_SELECTORS
            )
            for config in all_selectors:
                self._stats[config.name] = SelectorStats(name=config.name, css=config.css)
            
            # Load persisted stats
            self._load_stats()
            self._initialized = True
            logger.info("selector_manager_initialized", selectors_count=len(self._stats))
    
    def _load_stats(self) -> None:
        """Load stats from SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS selector_stats (
                    name TEXT PRIMARY KEY,
                    css TEXT,
                    successes INTEGER DEFAULT 0,
                    failures INTEGER DEFAULT 0,
                    last_success TEXT,
                    last_failure TEXT,
                    avg_match_count REAL DEFAULT 0
                )
            """)
            
            cursor = conn.execute("SELECT * FROM selector_stats")
            for row in cursor.fetchall():
                name = row[0]
                if name in self._stats:
                    self._stats[name].successes = row[2] or 0
                    self._stats[name].failures = row[3] or 0
                    self._stats[name].last_success = row[4]
                    self._stats[name].last_failure = row[5]
                    self._stats[name].avg_match_count = row[6] or 0.0
            
            conn.close()
        except Exception as e:
            logger.warning("selector_stats_load_failed", error=str(e))
    
    def _save_stats(self) -> None:
        """Persist stats to SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            for stat in self._stats.values():
                conn.execute("""
                    INSERT OR REPLACE INTO selector_stats 
                    (name, css, successes, failures, last_success, last_failure, avg_match_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (stat.name, stat.css, stat.successes, stat.failures,
                      stat.last_success, stat.last_failure, stat.avg_match_count))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("selector_stats_save_failed", error=str(e))
    
    def _get_ordered_selectors(self, configs: list[SelectorConfig]) -> list[SelectorConfig]:
        """Return selectors ordered by success rate (highest first)."""
        def sort_key(config: SelectorConfig) -> tuple:
            stat = self._stats.get(config.name)
            rate = stat.success_rate if stat else 0.5
            # Sort by: success_rate DESC, priority ASC, is_fallback ASC
            return (-rate, config.priority, config.is_fallback)
        
        return sorted(configs, key=sort_key)
    
    def _record_success(self, name: str, match_count: int = 1) -> None:
        """Record a successful selector match."""
        if name in self._stats:
            stat = self._stats[name]
            stat.successes += 1
            stat.last_success = datetime.now(timezone.utc).isoformat()
            # Update rolling average
            if stat.total_attempts > 1:
                stat.avg_match_count = (stat.avg_match_count * 0.9) + (match_count * 0.1)
            else:
                stat.avg_match_count = float(match_count)
    
    def _record_failure(self, name: str) -> None:
        """Record a selector failure."""
        if name in self._stats:
            stat = self._stats[name]
            stat.failures += 1
            stat.last_failure = datetime.now(timezone.utc).isoformat()
    
    async def _alert_all_failed(self, element_type: str, tried: list[str]) -> None:
        """Alert when all selectors for an element type fail."""
        logger.error("all_selectors_failed", element_type=element_type, tried=tried)
        
        for callback in self._alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(element_type, tried)
                else:
                    callback(element_type, tried)
            except Exception as e:
                logger.warning("selector_alert_callback_failed", error=str(e))
    
    def register_alert_callback(self, callback: Callable) -> None:
        """Register a callback for selector failure alerts."""
        self._alert_callbacks.append(callback)
    
    # =========================================================================
    # PUBLIC QUERY METHODS
    # =========================================================================
    
    async def find_posts(self, page: Any) -> list[Any]:
        """Find all post containers on page with fallback."""
        ordered = self._get_ordered_selectors(POST_CONTAINER_SELECTORS)
        tried = []
        
        for config in ordered:
            tried.append(config.name)
            try:
                elements = await page.query_selector_all(config.css)
                if elements and len(elements) >= config.min_expected:
                    self._record_success(config.name, len(elements))
                    logger.debug("selector_success", type="post", selector=config.name, count=len(elements))
                    return elements
                self._record_failure(config.name)
            except Exception as e:
                self._record_failure(config.name)
                logger.debug("selector_error", type="post", selector=config.name, error=str(e))
        
        await self._alert_all_failed("post_container", tried)
        return []
    
    async def find_author(self, element: Any) -> Optional[str]:
        """Find author name within a post element."""
        ordered = self._get_ordered_selectors(AUTHOR_SELECTORS)
        tried = []
        
        for config in ordered:
            tried.append(config.name)
            try:
                el = await element.query_selector(config.css)
                if el:
                    text = await el.text_content()
                    if text and text.strip():
                        self._record_success(config.name)
                        return text.strip()
                self._record_failure(config.name)
            except Exception:
                self._record_failure(config.name)
        
        # Don't alert for author - it's common to fail
        return None
    
    async def find_text(self, element: Any) -> Optional[str]:
        """Find post text content."""
        ordered = self._get_ordered_selectors(TEXT_SELECTORS)
        tried = []
        
        for config in ordered:
            tried.append(config.name)
            try:
                el = await element.query_selector(config.css)
                if el:
                    text = await el.text_content()
                    if text and len(text.strip()) > 20:  # Minimum meaningful content
                        self._record_success(config.name)
                        return text.strip()
                self._record_failure(config.name)
            except Exception:
                self._record_failure(config.name)
        
        await self._alert_all_failed("text", tried)
        return None
    
    async def find_date(self, element: Any) -> tuple[Optional[str], Optional[str]]:
        """Find date/timestamp. Returns (datetime_attr, text_content)."""
        ordered = self._get_ordered_selectors(DATE_SELECTORS)
        tried = []
        
        for config in ordered:
            tried.append(config.name)
            try:
                el = await element.query_selector(config.css)
                if el:
                    # Try datetime attribute first
                    dt_attr = await el.get_attribute("datetime")
                    text = await el.text_content()
                    if dt_attr or (text and text.strip()):
                        self._record_success(config.name)
                        return dt_attr, text.strip() if text else None
                self._record_failure(config.name)
            except Exception:
                self._record_failure(config.name)
        
        return None, None
    
    async def find_permalink(self, element: Any) -> Optional[str]:
        """Find post permalink URL."""
        ordered = self._get_ordered_selectors(PERMALINK_SELECTORS)
        tried = []
        
        for config in ordered:
            tried.append(config.name)
            try:
                el = await element.query_selector(config.css)
                if el:
                    href = await el.get_attribute("href")
                    if href and ("activity" in href or "posts" in href):
                        self._record_success(config.name)
                        return href
                self._record_failure(config.name)
            except Exception:
                self._record_failure(config.name)
        
        return None
    
    async def find_company(self, element: Any) -> Optional[str]:
        """Find company/organization name."""
        ordered = self._get_ordered_selectors(COMPANY_SELECTORS)
        tried = []
        
        for config in ordered:
            tried.append(config.name)
            try:
                el = await element.query_selector(config.css)
                if el:
                    text = await el.text_content()
                    if text and text.strip():
                        self._record_success(config.name)
                        return text.strip()
                self._record_failure(config.name)
            except Exception:
                self._record_failure(config.name)
        
        return None
    
    # =========================================================================
    # HEALTH & STATUS
    # =========================================================================
    
    def get_all_stats(self) -> dict[str, SelectorStats]:
        """Get all selector statistics.
        
        Returns:
            Dict mapping selector names to their stats
        """
        return self._stats.copy()
    
    def get_health_report(self) -> dict:
        """Generate health report for all selectors."""
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_healthy": True,
            "categories": {},
        }
        
        categories = {
            "post_container": POST_CONTAINER_SELECTORS,
            "author": AUTHOR_SELECTORS,
            "text": TEXT_SELECTORS,
            "date": DATE_SELECTORS,
            "permalink": PERMALINK_SELECTORS,
            "company": COMPANY_SELECTORS,
        }
        
        for cat_name, configs in categories.items():
            cat_stats = []
            has_working = False
            
            for config in configs:
                stat = self._stats.get(config.name)
                if stat:
                    cat_stats.append(stat.to_dict())
                    if stat.success_rate > 0.3:  # Consider working if >30% success
                        has_working = True
            
            report["categories"][cat_name] = {
                "healthy": has_working,
                "selectors": cat_stats,
            }
            
            if not has_working and cat_name in ("post_container", "text"):
                report["overall_healthy"] = False
        
        return report
    
    def persist(self) -> None:
        """Force persist current stats to disk."""
        self._save_stats()


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_manager_instance: Optional[SelectorManager] = None


async def get_selector_manager(db_path: Optional[str] = None) -> SelectorManager:
    """Get or create the singleton SelectorManager instance."""
    global _manager_instance
    
    if _manager_instance is None:
        _manager_instance = SelectorManager(db_path)
        await _manager_instance.initialize()
    
    return _manager_instance


def get_selector_manager_sync() -> Optional[SelectorManager]:
    """Get existing manager instance (sync, for non-async contexts)."""
    return _manager_instance


# =============================================================================
# HEALTH CHECK UTILITIES
# =============================================================================

async def test_selectors_on_page(page: Any) -> dict:
    """Run a live test of all selectors on a page.
    
    Args:
        page: Playwright page object on a LinkedIn search results page
        
    Returns:
        Dict with test results per selector category
    """
    manager = await get_selector_manager()
    results = {"timestamp": datetime.now(timezone.utc).isoformat(), "tests": {}}
    
    # Test post containers
    posts = await manager.find_posts(page)
    results["tests"]["post_container"] = {
        "found": len(posts),
        "success": len(posts) > 0,
    }
    
    if posts:
        # Test on first post
        post = posts[0]
        
        author = await manager.find_author(post)
        results["tests"]["author"] = {"found": author is not None, "value": author[:50] if author else None}
        
        text = await manager.find_text(post)
        results["tests"]["text"] = {"found": text is not None, "length": len(text) if text else 0}
        
        dt_attr, dt_text = await manager.find_date(post)
        results["tests"]["date"] = {"found": dt_attr is not None or dt_text is not None, "datetime": dt_attr, "text": dt_text}
        
        permalink = await manager.find_permalink(post)
        results["tests"]["permalink"] = {"found": permalink is not None}
        
        company = await manager.find_company(post)
        results["tests"]["company"] = {"found": company is not None, "value": company[:30] if company else None}
    
    return results


__all__ = [
    "SelectorManager",
    "SelectorConfig",
    "SelectorStats",
    "get_selector_manager",
    "get_selector_manager_sync",
    "test_selectors_on_page",
    "POST_CONTAINER_SELECTORS",
    "AUTHOR_SELECTORS",
    "TEXT_SELECTORS",
    "DATE_SELECTORS",
    "PERMALINK_SELECTORS",
    "COMPANY_SELECTORS",
]
