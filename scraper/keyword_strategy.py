"""Keyword strategy module with scoring and intelligent rotation.

This module manages keyword effectiveness tracking:
- Success rate per keyword (posts found / attempts)
- Relevance rate (posts retained after filtering / posts found)
- Intelligent rotation prioritizing high-yield keywords
- Automatic keyword retirement for consistently poor performers

Architecture:
    KeywordStrategy is initialized with the base keyword list.
    After each scraping session, update_stats() records results.
    get_next_batch() returns keywords ordered by expected yield.

Integration:
    - Initialize in worker.py before keyword processing
    - Call update_stats() after each keyword is processed
    - Replace static keyword iteration with get_next_batch()

Author: Titan Scraper Team
"""
from __future__ import annotations

import json
import sqlite3
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import os

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# KEYWORD STATS
# =============================================================================

@dataclass
class KeywordStats:
    """Statistics for a single keyword."""
    keyword: str
    attempts: int = 0
    posts_found: int = 0
    posts_retained: int = 0  # After filtering
    last_used: Optional[str] = None
    last_success: Optional[str] = None
    consecutive_failures: int = 0
    is_retired: bool = False
    
    @property
    def success_rate(self) -> float:
        """Rate of finding any posts."""
        if self.attempts == 0:
            return 0.5  # Neutral for untested
        return self.posts_found / self.attempts
    
    @property
    def relevance_rate(self) -> float:
        """Rate of retained posts vs found."""
        if self.posts_found == 0:
            return 0.5  # Neutral
        return self.posts_retained / self.posts_found
    
    @property
    def yield_score(self) -> float:
        """Combined score for ranking (0-1)."""
        # Weight: 40% success rate, 60% relevance rate
        return (self.success_rate * 0.4) + (self.relevance_rate * 0.6)
    
    @property
    def avg_retained_per_attempt(self) -> float:
        """Average retained posts per attempt."""
        if self.attempts == 0:
            return 0.0
        return self.posts_retained / self.attempts
    
    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "attempts": self.attempts,
            "posts_found": self.posts_found,
            "posts_retained": self.posts_retained,
            "success_rate": round(self.success_rate, 3),
            "relevance_rate": round(self.relevance_rate, 3),
            "yield_score": round(self.yield_score, 3),
            "avg_retained": round(self.avg_retained_per_attempt, 2),
            "last_used": self.last_used,
            "consecutive_failures": self.consecutive_failures,
            "is_retired": self.is_retired,
        }


# =============================================================================
# KEYWORD STRATEGY MANAGER
# =============================================================================

class KeywordStrategy:
    """Manages keyword selection and rotation based on performance.
    
    Features:
    - Tracks success/relevance per keyword
    - Prioritizes high-yield keywords
    - Retires consistently failing keywords
    - Ensures fair rotation (exploration vs exploitation)
    - Persists stats to SQLite
    """
    
    # Configuration
    MIN_ATTEMPTS_FOR_SCORING = 3  # Need at least N attempts before trusting score
    RETIREMENT_THRESHOLD = 5  # Consecutive failures before retirement
    EXPLORATION_RATIO = 0.2  # 20% of batch reserved for exploration
    RECENCY_PENALTY_HOURS = 2  # Penalize keywords used within N hours
    
    def __init__(self, keywords: list[str], db_path: Optional[str] = None):
        """Initialize with keyword list and optional custom DB path."""
        self.base_keywords = list(set(keywords))  # Deduplicate
        self.db_path = db_path or self._default_db_path()
        self._stats: dict[str, KeywordStats] = {}
        self._rotation_index = 0
        
        # Initialize stats for all keywords
        for kw in self.base_keywords:
            self._stats[kw] = KeywordStats(keyword=kw)
        
        self._load_stats()
        logger.info("keyword_strategy_initialized", keywords_count=len(self.base_keywords))
    
    @staticmethod
    def _default_db_path() -> str:
        if os.name == 'nt':
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            return str(Path(base) / "TitanScraper" / "keyword_stats.sqlite3")
        else:
            return str(Path.home() / ".local" / "share" / "TitanScraper" / "keyword_stats.sqlite3")
    
    def _load_stats(self) -> None:
        """Load persisted stats from SQLite."""
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS keyword_stats (
                    keyword TEXT PRIMARY KEY,
                    attempts INTEGER DEFAULT 0,
                    posts_found INTEGER DEFAULT 0,
                    posts_retained INTEGER DEFAULT 0,
                    last_used TEXT,
                    last_success TEXT,
                    consecutive_failures INTEGER DEFAULT 0,
                    is_retired INTEGER DEFAULT 0
                )
            """)
            
            cursor = conn.execute("SELECT * FROM keyword_stats")
            for row in cursor.fetchall():
                kw = row[0]
                if kw in self._stats:
                    stat = self._stats[kw]
                    stat.attempts = row[1] or 0
                    stat.posts_found = row[2] or 0
                    stat.posts_retained = row[3] or 0
                    stat.last_used = row[4]
                    stat.last_success = row[5]
                    stat.consecutive_failures = row[6] or 0
                    stat.is_retired = bool(row[7])
            
            conn.close()
        except Exception as e:
            logger.warning("keyword_stats_load_failed", error=str(e))
    
    def _save_stats(self) -> None:
        """Persist stats to SQLite."""
        try:
            conn = sqlite3.connect(self.db_path)
            for stat in self._stats.values():
                conn.execute("""
                    INSERT OR REPLACE INTO keyword_stats
                    (keyword, attempts, posts_found, posts_retained, last_used, 
                     last_success, consecutive_failures, is_retired)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (stat.keyword, stat.attempts, stat.posts_found, stat.posts_retained,
                      stat.last_used, stat.last_success, stat.consecutive_failures,
                      int(stat.is_retired)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("keyword_stats_save_failed", error=str(e))
    
    def update_stats(self, keyword: str, posts_found: int, posts_retained: int) -> None:
        """Update stats after processing a keyword.
        
        Args:
            keyword: The keyword that was used
            posts_found: Number of posts extracted (before filtering)
            posts_retained: Number of posts kept (after filtering)
        """
        if keyword not in self._stats:
            self._stats[keyword] = KeywordStats(keyword=keyword)
        
        stat = self._stats[keyword]
        stat.attempts += 1
        stat.posts_found += posts_found
        stat.posts_retained += posts_retained
        stat.last_used = datetime.now(timezone.utc).isoformat()
        
        if posts_retained > 0:
            stat.last_success = stat.last_used
            stat.consecutive_failures = 0
            # Un-retire if it starts working again
            if stat.is_retired:
                stat.is_retired = False
                logger.info("keyword_un_retired", keyword=keyword)
        else:
            stat.consecutive_failures += 1
            if stat.consecutive_failures >= self.RETIREMENT_THRESHOLD:
                if not stat.is_retired:
                    stat.is_retired = True
                    logger.warning("keyword_retired", keyword=keyword, 
                                   failures=stat.consecutive_failures)
        
        self._save_stats()
    
    def _calculate_priority(self, stat: KeywordStats) -> float:
        """Calculate priority score for keyword selection."""
        if stat.is_retired:
            return -1.0  # Never select retired
        
        base_score = stat.yield_score
        
        # Boost untested keywords for exploration
        if stat.attempts < self.MIN_ATTEMPTS_FOR_SCORING:
            base_score = max(base_score, 0.6)  # Ensure exploration
        
        # Recency penalty to ensure rotation
        if stat.last_used:
            try:
                last_used_dt = datetime.fromisoformat(stat.last_used.replace('Z', '+00:00'))
                hours_ago = (datetime.now(timezone.utc) - last_used_dt).total_seconds() / 3600
                if hours_ago < self.RECENCY_PENALTY_HOURS:
                    base_score *= 0.5  # Penalize recently used
            except Exception:
                pass
        
        return base_score
    
    def get_next_batch(self, batch_size: int = 3) -> list[str]:
        """Get next batch of keywords to process.
        
        Uses a mix of exploitation (high-yield) and exploration (untested/rotated).
        
        Args:
            batch_size: Number of keywords to return
            
        Returns:
            List of keywords ordered by priority
        """
        active_keywords = [kw for kw, stat in self._stats.items() if not stat.is_retired]
        
        if not active_keywords:
            # All retired - reset and try again
            logger.warning("all_keywords_retired_resetting")
            for stat in self._stats.values():
                stat.is_retired = False
                stat.consecutive_failures = 0
            active_keywords = list(self._stats.keys())
        
        if len(active_keywords) <= batch_size:
            return active_keywords
        
        # Split between exploitation and exploration
        exploit_count = max(1, int(batch_size * (1 - self.EXPLORATION_RATIO)))
        explore_count = batch_size - exploit_count
        
        # Exploitation: top performers
        scored = [(kw, self._calculate_priority(self._stats[kw])) for kw in active_keywords]
        scored.sort(key=lambda x: x[1], reverse=True)
        
        exploit_batch = [kw for kw, _ in scored[:exploit_count]]
        
        # Exploration: random from remaining (prioritizing untested)
        remaining = [kw for kw, _ in scored[exploit_count:]]
        untested = [kw for kw in remaining if self._stats[kw].attempts < self.MIN_ATTEMPTS_FOR_SCORING]
        
        if untested and len(untested) >= explore_count:
            explore_batch = random.sample(untested, explore_count)
        else:
            explore_batch = random.sample(remaining, min(explore_count, len(remaining)))
        
        batch = exploit_batch + explore_batch
        logger.debug("keyword_batch_selected", 
                     exploit=exploit_batch, explore=explore_batch,
                     scores={kw: round(self._calculate_priority(self._stats[kw]), 2) for kw in batch})
        
        return batch
    
    def get_all_keywords_round_robin(self, batch_size: int = 3) -> list[str]:
        """Get keywords using simple round-robin (ensures all are covered).
        
        Use this for initial passes or when exploration is prioritized.
        """
        active = [kw for kw, stat in self._stats.items() if not stat.is_retired]
        if not active:
            return []
        
        start_idx = self._rotation_index % len(active)
        batch = []
        for i in range(batch_size):
            idx = (start_idx + i) % len(active)
            batch.append(active[idx])
        
        self._rotation_index = (self._rotation_index + batch_size) % len(active)
        return batch
    
    def get_stats_report(self) -> dict:
        """Generate full stats report."""
        active = [s.to_dict() for s in self._stats.values() if not s.is_retired]
        retired = [s.to_dict() for s in self._stats.values() if s.is_retired]
        
        total_attempts = sum(s.attempts for s in self._stats.values())
        total_retained = sum(s.posts_retained for s in self._stats.values())
        
        # Top performers
        top_5 = sorted(active, key=lambda x: x["yield_score"], reverse=True)[:5]
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_keywords": len(self._stats),
            "active_keywords": len(active),
            "retired_keywords": len(retired),
            "total_attempts": total_attempts,
            "total_retained": total_retained,
            "avg_yield": round(total_retained / max(1, total_attempts), 3),
            "top_performers": top_5,
            "retired": retired,
            "all_active": sorted(active, key=lambda x: x["yield_score"], reverse=True),
        }
    
    def retire_keyword(self, keyword: str) -> bool:
        """Manually retire a keyword."""
        if keyword in self._stats:
            self._stats[keyword].is_retired = True
            self._save_stats()
            logger.info("keyword_manually_retired", keyword=keyword)
            return True
        return False
    
    def unretire_keyword(self, keyword: str) -> bool:
        """Manually un-retire a keyword."""
        if keyword in self._stats:
            self._stats[keyword].is_retired = False
            self._stats[keyword].consecutive_failures = 0
            self._save_stats()
            logger.info("keyword_manually_unretired", keyword=keyword)
            return True
        return False
    
    def add_keyword(self, keyword: str) -> bool:
        """Add a new keyword to the strategy."""
        if keyword not in self._stats:
            self._stats[keyword] = KeywordStats(keyword=keyword)
            self.base_keywords.append(keyword)
            self._save_stats()
            logger.info("keyword_added", keyword=keyword)
            return True
        return False


# =============================================================================
# FACTORY & SINGLETON
# =============================================================================

_strategy_instance: Optional[KeywordStrategy] = None


def get_keyword_strategy(keywords: Optional[list[str]] = None) -> KeywordStrategy:
    """Get or create keyword strategy singleton."""
    global _strategy_instance
    
    if _strategy_instance is None:
        if keywords is None:
            raise ValueError("Keywords must be provided for first initialization")
        _strategy_instance = KeywordStrategy(keywords)
    
    return _strategy_instance


def reset_keyword_strategy() -> None:
    """Reset singleton (for testing)."""
    global _strategy_instance
    _strategy_instance = None


__all__ = [
    "KeywordStrategy",
    "KeywordStats",
    "get_keyword_strategy",
    "reset_keyword_strategy",
]
