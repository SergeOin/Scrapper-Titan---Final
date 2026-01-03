"""Post deduplication cache for efficient duplicate detection.

This module provides a fast LRU-based cache to track already-processed posts
and avoid:
- Re-processing the same post multiple times per session
- Storing duplicates in the database
- Wasting API/filter resources on known posts

Features:
- Dual-layer caching: memory (fast) + SQLite (persistent)
- Configurable TTL for entries
- Multiple signature strategies (URL, content hash, permalink)
- Memory-efficient with size limits

Integration:
    - Call is_duplicate() before processing a post
    - Call mark_processed() after successful processing

Author: Titan Scraper Team
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MEMORY_CACHE_SIZE = 10000  # Max entries in memory
DEFAULT_SQLITE_CACHE_SIZE = 100000  # Max entries in SQLite
DEFAULT_TTL_HOURS = 168  # 7 days


@dataclass
class CacheConfig:
    """Cache configuration."""
    memory_size: int = DEFAULT_MEMORY_CACHE_SIZE
    sqlite_size: int = DEFAULT_SQLITE_CACHE_SIZE
    ttl_hours: int = DEFAULT_TTL_HOURS
    persist_path: Optional[str] = None
    enable_persistence: bool = True
    
    def __post_init__(self):
        if self.persist_path is None:
            self.persist_path = self._default_path()
    
    @staticmethod
    def _default_path() -> str:
        if os.name == 'nt':
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            return str(Path(base) / "TitanScraper" / "post_cache.sqlite3")
        else:
            return str(Path.home() / ".local" / "share" / "TitanScraper" / "post_cache.sqlite3")


# =============================================================================
# SIGNATURE GENERATION
# =============================================================================

def generate_content_signature(text: str, author: str = "") -> str:
    """Generate content-based signature.
    
    Uses normalized text + author for deduplication.
    Handles minor variations in formatting.
    """
    # Normalize text
    normalized = text.lower()
    normalized = " ".join(normalized.split())  # Collapse whitespace
    normalized = normalized[:500]  # First 500 chars for efficiency
    
    # Add author if available
    if author:
        normalized = f"{author.lower().strip()}:{normalized}"
    
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def generate_url_signature(url: str) -> str:
    """Generate URL-based signature.
    
    Removes query parameters and normalizes.
    """
    if not url:
        return ""
    
    # Remove query params and fragments
    base_url = url.split("?")[0].split("#")[0]
    
    # Normalize
    base_url = base_url.rstrip("/").lower()
    
    return hashlib.md5(base_url.encode()).hexdigest()


def generate_post_id_signature(post_id: str) -> str:
    """Generate signature from LinkedIn post ID."""
    if not post_id:
        return ""
    return f"pid:{post_id}"


def generate_composite_signature(
    url: str = "",
    post_id: str = "",
    text: str = "",
    author: str = "",
) -> str:
    """Generate composite signature with priority fallbacks.
    
    Priority:
    1. Post ID (most reliable)
    2. URL signature
    3. Content hash (fallback)
    """
    # Try post ID first
    if post_id:
        return generate_post_id_signature(post_id)
    
    # Try URL
    if url:
        return f"url:{generate_url_signature(url)}"
    
    # Fallback to content
    if text:
        return f"content:{generate_content_signature(text, author)}"
    
    return ""


# =============================================================================
# MEMORY CACHE (LRU)
# =============================================================================

class LRUCache:
    """Thread-safe LRU cache for in-memory deduplication."""
    
    def __init__(self, maxsize: int = DEFAULT_MEMORY_CACHE_SIZE):
        self._maxsize = maxsize
        self._cache: OrderedDict[str, datetime] = OrderedDict()
        self._lock = threading.Lock()
    
    def contains(self, key: str) -> bool:
        """Check if key exists and move to end (most recently used)."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return True
            return False
    
    def add(self, key: str) -> None:
        """Add key to cache, evicting oldest if needed."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                self._cache[key] = datetime.now(timezone.utc)
                # Evict oldest entries if over capacity
                while len(self._cache) > self._maxsize:
                    self._cache.popitem(last=False)
    
    def remove(self, key: str) -> bool:
        """Remove key from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> int:
        """Clear cache and return number of entries removed."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count
    
    def size(self) -> int:
        """Return current cache size."""
        with self._lock:
            return len(self._cache)
    
    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "utilization": round(len(self._cache) / self._maxsize, 2) if self._maxsize > 0 else 0,
            }


# =============================================================================
# PERSISTENT CACHE (SQLite)
# =============================================================================

class PersistentCache:
    """SQLite-based persistent cache."""
    
    def __init__(self, db_path: str, maxsize: int = DEFAULT_SQLITE_CACHE_SIZE, 
                 ttl_hours: int = DEFAULT_TTL_HOURS):
        self._db_path = db_path
        self._maxsize = maxsize
        self._ttl_hours = ttl_hours
        self._lock = threading.Lock()
        self._initialized = False
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS post_cache (
                        signature TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        source TEXT,
                        metadata TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON post_cache(created_at)")
                conn.commit()
            self._initialized = True
        except Exception as e:
            logger.warning("persistent_cache_init_failed", error=str(e))
    
    def contains(self, signature: str) -> bool:
        """Check if signature exists in cache."""
        if not self._initialized:
            return False
        
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.execute(
                        "SELECT 1 FROM post_cache WHERE signature = ?",
                        (signature,)
                    )
                    return cursor.fetchone() is not None
            except Exception as e:
                logger.debug("cache_contains_error", error=str(e))
                return False
    
    def add(self, signature: str, source: str = "", metadata: str = "") -> None:
        """Add signature to cache."""
        if not self._initialized or not signature:
            return
        
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO post_cache (signature, created_at, source, metadata)
                        VALUES (?, ?, ?, ?)
                    """, (signature, datetime.now(timezone.utc).isoformat(), source, metadata))
                    conn.commit()
                    self._maybe_cleanup(conn)
            except Exception as e:
                logger.debug("cache_add_error", error=str(e))
    
    def _maybe_cleanup(self, conn: sqlite3.Connection) -> None:
        """Cleanup old entries if needed."""
        try:
            # Check size
            cursor = conn.execute("SELECT COUNT(*) FROM post_cache")
            count = cursor.fetchone()[0]
            
            if count > self._maxsize * 1.1:  # 10% buffer
                # Delete oldest entries
                to_delete = count - self._maxsize
                conn.execute("""
                    DELETE FROM post_cache 
                    WHERE signature IN (
                        SELECT signature FROM post_cache 
                        ORDER BY created_at ASC 
                        LIMIT ?
                    )
                """, (to_delete,))
            
            # Delete expired entries
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=self._ttl_hours)).isoformat()
            conn.execute("DELETE FROM post_cache WHERE created_at < ?", (cutoff,))
            conn.commit()
        except Exception as e:
            logger.debug("cache_cleanup_error", error=str(e))
    
    def remove(self, signature: str) -> bool:
        """Remove signature from cache."""
        if not self._initialized:
            return False
        
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.execute(
                        "DELETE FROM post_cache WHERE signature = ?",
                        (signature,)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                logger.debug("cache_remove_error", error=str(e))
                return False
    
    def clear(self) -> int:
        """Clear entire cache."""
        if not self._initialized:
            return 0
        
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM post_cache")
                    count = cursor.fetchone()[0]
                    conn.execute("DELETE FROM post_cache")
                    conn.commit()
                    return count
            except Exception as e:
                logger.warning("cache_clear_error", error=str(e))
                return 0
    
    def size(self) -> int:
        """Return current cache size."""
        if not self._initialized:
            return 0
        
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM post_cache")
                    return cursor.fetchone()[0]
            except Exception:
                return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        return {
            "size": self.size(),
            "maxsize": self._maxsize,
            "ttl_hours": self._ttl_hours,
            "initialized": self._initialized,
            "db_path": self._db_path,
        }


# =============================================================================
# UNIFIED POST CACHE
# =============================================================================

class PostCache:
    """Unified post cache with memory + persistent layers.
    
    Two-tier caching:
    1. Memory (LRU): Fast lookups for current session
    2. SQLite: Persistent across restarts
    
    Lookup checks memory first, then SQLite.
    """
    
    def __init__(self, config: Optional[CacheConfig] = None):
        self._config = config or CacheConfig()
        self._memory = LRUCache(self._config.memory_size)
        self._persistent: Optional[PersistentCache] = None
        
        if self._config.enable_persistence and self._config.persist_path:
            self._persistent = PersistentCache(
                self._config.persist_path,
                self._config.sqlite_size,
                self._config.ttl_hours,
            )
        
        self._stats = {
            "checks": 0,
            "memory_hits": 0,
            "persistent_hits": 0,
            "misses": 0,
            "additions": 0,
        }
    
    def is_duplicate(
        self,
        url: str = "",
        post_id: str = "",
        text: str = "",
        author: str = "",
    ) -> bool:
        """Check if post is a duplicate.
        
        Args:
            url: Post URL
            post_id: LinkedIn post ID
            text: Post text content
            author: Author name
            
        Returns:
            True if post was already processed
        """
        signature = generate_composite_signature(url, post_id, text, author)
        if not signature:
            return False
        
        self._stats["checks"] += 1
        
        # Check memory first
        if self._memory.contains(signature):
            self._stats["memory_hits"] += 1
            return True
        
        # Check persistent
        if self._persistent and self._persistent.contains(signature):
            self._stats["persistent_hits"] += 1
            # Promote to memory cache
            self._memory.add(signature)
            return True
        
        self._stats["misses"] += 1
        return False
    
    def mark_processed(
        self,
        url: str = "",
        post_id: str = "",
        text: str = "",
        author: str = "",
        source: str = "scraper",
        metadata: str = "",
    ) -> str:
        """Mark post as processed.
        
        Args:
            url: Post URL
            post_id: LinkedIn post ID
            text: Post text content
            author: Author name
            source: Processing source (scraper, api, etc.)
            metadata: Additional metadata JSON
            
        Returns:
            Generated signature
        """
        signature = generate_composite_signature(url, post_id, text, author)
        if not signature:
            return ""
        
        self._stats["additions"] += 1
        
        # Add to both caches
        self._memory.add(signature)
        if self._persistent:
            self._persistent.add(signature, source, metadata)
        
        return signature
    
    def remove(
        self,
        url: str = "",
        post_id: str = "",
        text: str = "",
        author: str = "",
    ) -> bool:
        """Remove post from cache (e.g., if processing failed)."""
        signature = generate_composite_signature(url, post_id, text, author)
        if not signature:
            return False
        
        removed_memory = self._memory.remove(signature)
        removed_persistent = self._persistent.remove(signature) if self._persistent else False
        
        return removed_memory or removed_persistent
    
    def clear_memory(self) -> int:
        """Clear only memory cache."""
        return self._memory.clear()
    
    def clear_all(self) -> Tuple[int, int]:
        """Clear both caches.
        
        Returns:
            (memory_cleared, persistent_cleared)
        """
        memory_count = self._memory.clear()
        persistent_count = self._persistent.clear() if self._persistent else 0
        return memory_count, persistent_count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        total_checks = self._stats["checks"] or 1
        hit_rate = (self._stats["memory_hits"] + self._stats["persistent_hits"]) / total_checks
        
        return {
            "hit_rate": round(hit_rate, 3),
            "checks": self._stats["checks"],
            "memory_hits": self._stats["memory_hits"],
            "persistent_hits": self._stats["persistent_hits"],
            "misses": self._stats["misses"],
            "additions": self._stats["additions"],
            "memory": self._memory.get_stats(),
            "persistent": self._persistent.get_stats() if self._persistent else None,
        }
    
    def get_health(self) -> Dict[str, Any]:
        """Get health status for monitoring."""
        memory_stats = self._memory.get_stats()
        
        # Warning if memory cache is very full
        memory_warning = memory_stats["utilization"] > 0.95
        
        return {
            "healthy": not memory_warning,
            "warnings": ["Memory cache near capacity"] if memory_warning else [],
            "memory_utilization": memory_stats["utilization"],
            "hit_rate": round(
                (self._stats["memory_hits"] + self._stats["persistent_hits"]) / 
                max(1, self._stats["checks"]), 2
            ),
        }


# =============================================================================
# SINGLETON
# =============================================================================

_cache_instance: Optional[PostCache] = None
_cache_lock = threading.Lock()


def get_post_cache(config: Optional[CacheConfig] = None) -> PostCache:
    """Get or create post cache singleton."""
    global _cache_instance
    
    with _cache_lock:
        if _cache_instance is None:
            _cache_instance = PostCache(config)
        return _cache_instance


def reset_post_cache() -> None:
    """Reset singleton (for testing)."""
    global _cache_instance
    with _cache_lock:
        _cache_instance = None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def is_duplicate(
    url: str = "",
    post_id: str = "",
    text: str = "",
    author: str = "",
) -> bool:
    """Convenience function to check duplicate."""
    return get_post_cache().is_duplicate(url, post_id, text, author)


def mark_processed(
    url: str = "",
    post_id: str = "",
    text: str = "",
    author: str = "",
) -> str:
    """Convenience function to mark as processed."""
    return get_post_cache().mark_processed(url, post_id, text, author)


__all__ = [
    # Classes
    "PostCache",
    "CacheConfig",
    "LRUCache",
    "PersistentCache",
    
    # Functions
    "get_post_cache",
    "reset_post_cache",
    "is_duplicate",
    "mark_processed",
    "generate_composite_signature",
    "generate_content_signature",
    "generate_url_signature",
    "generate_post_id_signature",
]
