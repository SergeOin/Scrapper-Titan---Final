"""Progressive mode management for adaptive scraping limits.

This module implements a tiered approach to scraping intensity:
- CONSERVATIVE: Low limits, long delays (after restriction or initial state)
- MODERATE: Medium limits (after 7+ days without issues)
- AGGRESSIVE: Higher limits (after 14+ days of success)

The mode automatically adjusts based on:
- Time since last LinkedIn restriction/warning
- Number of consecutive successful sessions
- Detection of rate limiting signals

Integration:
    - Initialize in bootstrap.py or worker.py
    - Call get_current_limits() to get dynamic parameters
    - Call record_session_result() after each scraping session

Author: Titan Scraper Team
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional
import os

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# MODE DEFINITIONS
# =============================================================================

class ScrapingMode(str, Enum):
    """Scraping intensity modes."""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    
    def __str__(self) -> str:
        return self.value


@dataclass
class ModeLimits:
    """Scraping limits for a given mode."""
    mode: ScrapingMode
    
    # Posts & extraction
    max_posts_per_keyword: int
    max_scroll_steps: int
    min_posts_target: int
    
    # Batch size
    keywords_per_batch: int
    
    # Delays (milliseconds)
    keyword_delay_min_ms: int
    keyword_delay_max_ms: int
    scroll_delay_min_ms: int
    scroll_delay_max_ms: int
    page_load_delay_min_ms: int
    page_load_delay_max_ms: int
    
    # Worker interval (seconds)
    autonomous_interval_seconds: int
    
    # Risk thresholds
    long_pause_probability: float
    
    def to_dict(self) -> dict:
        return {
            "mode": str(self.mode),
            "max_posts_per_keyword": self.max_posts_per_keyword,
            "max_scroll_steps": self.max_scroll_steps,
            "min_posts_target": self.min_posts_target,
            "keywords_per_batch": self.keywords_per_batch,
            "keyword_delay_min_ms": self.keyword_delay_min_ms,
            "keyword_delay_max_ms": self.keyword_delay_max_ms,
            "scroll_delay_min_ms": self.scroll_delay_min_ms,
            "scroll_delay_max_ms": self.scroll_delay_max_ms,
            "page_load_delay_min_ms": self.page_load_delay_min_ms,
            "page_load_delay_max_ms": self.page_load_delay_max_ms,
            "autonomous_interval_seconds": self.autonomous_interval_seconds,
            "long_pause_probability": self.long_pause_probability,
        }


# Default limits per mode
MODE_LIMITS: dict[ScrapingMode, ModeLimits] = {
    ScrapingMode.CONSERVATIVE: ModeLimits(
        mode=ScrapingMode.CONSERVATIVE,
        max_posts_per_keyword=8,
        max_scroll_steps=2,
        min_posts_target=5,
        keywords_per_batch=3,
        keyword_delay_min_ms=30000,  # 30s
        keyword_delay_max_ms=60000,  # 60s
        scroll_delay_min_ms=3000,
        scroll_delay_max_ms=7000,
        page_load_delay_min_ms=5000,
        page_load_delay_max_ms=12000,
        autonomous_interval_seconds=120,  # 2 minutes
        long_pause_probability=0.20,  # 20%
    ),
    ScrapingMode.MODERATE: ModeLimits(
        mode=ScrapingMode.MODERATE,
        max_posts_per_keyword=15,
        max_scroll_steps=4,
        min_posts_target=10,
        keywords_per_batch=5,
        keyword_delay_min_ms=20000,  # 20s
        keyword_delay_max_ms=45000,  # 45s
        scroll_delay_min_ms=2000,
        scroll_delay_max_ms=5000,
        page_load_delay_min_ms=3000,
        page_load_delay_max_ms=8000,
        autonomous_interval_seconds=90,  # 1.5 minutes
        long_pause_probability=0.12,  # 12%
    ),
    ScrapingMode.AGGRESSIVE: ModeLimits(
        mode=ScrapingMode.AGGRESSIVE,
        max_posts_per_keyword=25,
        max_scroll_steps=6,
        min_posts_target=15,
        keywords_per_batch=8,
        keyword_delay_min_ms=15000,  # 15s
        keyword_delay_max_ms=30000,  # 30s
        scroll_delay_min_ms=1500,
        scroll_delay_max_ms=4000,
        page_load_delay_min_ms=2000,
        page_load_delay_max_ms=6000,
        autonomous_interval_seconds=60,  # 1 minute
        long_pause_probability=0.08,  # 8%
    ),
}


# =============================================================================
# PROGRESSIVE MODE MANAGER
# =============================================================================

class ProgressiveModeManager:
    """Manages progressive scraping mode based on session history.
    
    Thresholds for mode transitions:
    - CONSERVATIVE → MODERATE: 7 days without restriction + 20 successful sessions
    - MODERATE → AGGRESSIVE: 14 days without restriction + 50 successful sessions
    - Any restriction → CONSERVATIVE (immediate)
    """
    
    # Transition thresholds
    CONSERVATIVE_TO_MODERATE_DAYS = 7
    CONSERVATIVE_TO_MODERATE_SESSIONS = 20
    MODERATE_TO_AGGRESSIVE_DAYS = 14
    MODERATE_TO_AGGRESSIVE_SESSIONS = 50
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self._default_db_path()
        self._current_mode = ScrapingMode.CONSERVATIVE
        self._last_restriction: Optional[datetime] = None
        self._successful_sessions = 0
        self._failed_sessions = 0
        self._manual_override: Optional[ScrapingMode] = None
        
        self._load_state()
    
    @staticmethod
    def _default_db_path() -> str:
        if os.name == 'nt':
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            return str(Path(base) / "TitanScraper" / "progressive_mode.sqlite3")
        else:
            return str(Path.home() / ".local" / "share" / "TitanScraper" / "progressive_mode.sqlite3")
    
    def _load_state(self) -> None:
        """Load persisted state from SQLite."""
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mode_state (
                    id TEXT PRIMARY KEY,
                    current_mode TEXT,
                    last_restriction TEXT,
                    successful_sessions INTEGER DEFAULT 0,
                    failed_sessions INTEGER DEFAULT 0,
                    manual_override TEXT
                )
            """)
            
            # Session history for detailed tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    success INTEGER,
                    posts_found INTEGER,
                    restriction_detected INTEGER,
                    mode_at_time TEXT
                )
            """)
            
            cursor = conn.execute("SELECT * FROM mode_state WHERE id = 'global'")
            row = cursor.fetchone()
            if row:
                self._current_mode = ScrapingMode(row[1]) if row[1] else ScrapingMode.CONSERVATIVE
                self._last_restriction = datetime.fromisoformat(row[2]) if row[2] else None
                self._successful_sessions = row[3] or 0
                self._failed_sessions = row[4] or 0
                self._manual_override = ScrapingMode(row[5]) if row[5] else None
            
            conn.close()
            logger.info("progressive_mode_loaded", mode=str(self._current_mode),
                        successful_sessions=self._successful_sessions)
        except Exception as e:
            logger.warning("progressive_mode_load_failed", error=str(e))
    
    def _save_state(self) -> None:
        """Persist state to SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT OR REPLACE INTO mode_state 
                (id, current_mode, last_restriction, successful_sessions, failed_sessions, manual_override)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                "global",
                str(self._current_mode),
                self._last_restriction.isoformat() if self._last_restriction else None,
                self._successful_sessions,
                self._failed_sessions,
                str(self._manual_override) if self._manual_override else None,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("progressive_mode_save_failed", error=str(e))
    
    def _record_session(self, success: bool, posts_found: int, restriction: bool) -> None:
        """Record session in history table."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT INTO session_history (timestamp, success, posts_found, restriction_detected, mode_at_time)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                int(success),
                posts_found,
                int(restriction),
                str(self._current_mode),
            ))
            conn.commit()
            
            # Cleanup old history (keep last 1000)
            conn.execute("DELETE FROM session_history WHERE id NOT IN (SELECT id FROM session_history ORDER BY id DESC LIMIT 1000)")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("session_history_record_failed", error=str(e))
    
    def _evaluate_mode(self) -> ScrapingMode:
        """Evaluate what mode we should be in based on current state."""
        if self._manual_override:
            return self._manual_override
        
        # Calculate days since last restriction
        if self._last_restriction:
            days_since = (datetime.now(timezone.utc) - self._last_restriction).days
        else:
            days_since = 999  # No restriction ever recorded
        
        # Check for AGGRESSIVE eligibility
        if (days_since >= self.MODERATE_TO_AGGRESSIVE_DAYS and 
            self._successful_sessions >= self.MODERATE_TO_AGGRESSIVE_SESSIONS):
            return ScrapingMode.AGGRESSIVE
        
        # Check for MODERATE eligibility
        if (days_since >= self.CONSERVATIVE_TO_MODERATE_DAYS and 
            self._successful_sessions >= self.CONSERVATIVE_TO_MODERATE_SESSIONS):
            return ScrapingMode.MODERATE
        
        return ScrapingMode.CONSERVATIVE
    
    def record_session_result(self, success: bool, posts_found: int = 0, 
                               restriction_detected: bool = False) -> ScrapingMode:
        """Record a session result and update mode.
        
        Args:
            success: Whether the session completed without errors
            posts_found: Number of posts extracted
            restriction_detected: Whether LinkedIn showed restriction warning
            
        Returns:
            New current mode after evaluation
        """
        self._record_session(success, posts_found, restriction_detected)
        
        if restriction_detected:
            # Immediate reset to CONSERVATIVE
            logger.warning("restriction_detected_resetting_mode")
            self._last_restriction = datetime.now(timezone.utc)
            self._successful_sessions = 0
            self._failed_sessions = 0
            self._current_mode = ScrapingMode.CONSERVATIVE
        elif success:
            self._successful_sessions += 1
            # Evaluate if we should upgrade
            new_mode = self._evaluate_mode()
            if new_mode != self._current_mode:
                logger.info("mode_upgraded", from_mode=str(self._current_mode), 
                           to_mode=str(new_mode), sessions=self._successful_sessions)
                self._current_mode = new_mode
        else:
            self._failed_sessions += 1
            # Multiple consecutive failures might indicate issues
            if self._failed_sessions >= 5:
                logger.warning("multiple_failures_downgrading")
                if self._current_mode == ScrapingMode.AGGRESSIVE:
                    self._current_mode = ScrapingMode.MODERATE
                elif self._current_mode == ScrapingMode.MODERATE:
                    self._current_mode = ScrapingMode.CONSERVATIVE
                self._failed_sessions = 0
        
        self._save_state()
        return self._current_mode
    
    def get_current_mode(self) -> ScrapingMode:
        """Get current scraping mode."""
        if self._manual_override:
            return self._manual_override
        return self._current_mode
    
    def get_current_limits(self) -> ModeLimits:
        """Get limits for current mode."""
        return MODE_LIMITS[self.get_current_mode()]
    
    def set_manual_override(self, mode: Optional[ScrapingMode]) -> None:
        """Set or clear manual mode override.
        
        Args:
            mode: Mode to force, or None to clear override
        """
        self._manual_override = mode
        self._save_state()
        logger.info("manual_override_set", mode=str(mode) if mode else "cleared")
    
    def get_status(self) -> dict:
        """Get full status report."""
        days_since = 0
        if self._last_restriction:
            days_since = (datetime.now(timezone.utc) - self._last_restriction).days
        
        return {
            "current_mode": str(self.get_current_mode()),
            "evaluated_mode": str(self._evaluate_mode()),
            "manual_override": str(self._manual_override) if self._manual_override else None,
            "last_restriction": self._last_restriction.isoformat() if self._last_restriction else None,
            "days_since_restriction": days_since,
            "successful_sessions": self._successful_sessions,
            "failed_sessions": self._failed_sessions,
            "limits": self.get_current_limits().to_dict(),
            "thresholds": {
                "conservative_to_moderate": {
                    "days_required": self.CONSERVATIVE_TO_MODERATE_DAYS,
                    "sessions_required": self.CONSERVATIVE_TO_MODERATE_SESSIONS,
                },
                "moderate_to_aggressive": {
                    "days_required": self.MODERATE_TO_AGGRESSIVE_DAYS,
                    "sessions_required": self.MODERATE_TO_AGGRESSIVE_SESSIONS,
                },
            },
        }
    
    def reset_to_conservative(self) -> None:
        """Force reset to conservative mode (e.g., after manual intervention)."""
        self._current_mode = ScrapingMode.CONSERVATIVE
        self._successful_sessions = 0
        self._failed_sessions = 0
        self._manual_override = None
        self._save_state()
        logger.info("mode_reset_to_conservative")


# =============================================================================
# SINGLETON
# =============================================================================

_manager_instance: Optional[ProgressiveModeManager] = None


def get_progressive_mode_manager() -> ProgressiveModeManager:
    """Get or create progressive mode manager singleton."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ProgressiveModeManager()
    return _manager_instance


def reset_progressive_mode_manager() -> None:
    """Reset singleton (for testing)."""
    global _manager_instance
    _manager_instance = None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_current_limits() -> ModeLimits:
    """Convenience function to get current limits."""
    return get_progressive_mode_manager().get_current_limits()


def record_session(success: bool, posts_found: int = 0, 
                   restriction_detected: bool = False) -> ScrapingMode:
    """Convenience function to record session result."""
    return get_progressive_mode_manager().record_session_result(
        success, posts_found, restriction_detected)


__all__ = [
    "ScrapingMode",
    "ModeLimits",
    "ProgressiveModeManager",
    "MODE_LIMITS",
    "get_progressive_mode_manager",
    "reset_progressive_mode_manager",
    "get_current_limits",
    "record_session",
]
