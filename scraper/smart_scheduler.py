"""Smart scheduler with adaptive intervals.

This module implements an intelligent scheduler that adjusts scraping
intervals based on:
- Time of day (peak hours vs off-hours)
- Day of week (weekdays vs weekends)
- Recent restriction signals
- Session success rate
- LinkedIn activity patterns

Integration:
    - Replace fixed intervals in worker.py with get_next_interval()
    - Call record_event() to feed the scheduler with signals

Author: Titan Scraper Team
"""
from __future__ import annotations

import os
import random
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# TIME WINDOWS
# =============================================================================

class TimeWindow(str, Enum):
    """Time windows for scheduling."""
    PEAK = "peak"           # High LinkedIn activity (9-12, 14-17)
    MODERATE = "moderate"   # Moderate activity (8-9, 12-14, 17-19)
    LOW = "low"             # Low activity (19-22)
    MINIMAL = "minimal"     # Very low activity (22-8)
    
    def __str__(self) -> str:
        return self.value


class DayType(str, Enum):
    """Day type classification."""
    WEEKDAY = "weekday"
    WEEKEND = "weekend"
    
    def __str__(self) -> str:
        return self.value


# =============================================================================
# SCHEDULE CONFIGURATION
# =============================================================================

@dataclass
class ScheduleConfig:
    """Configuration for the smart scheduler."""
    
    # Base intervals (seconds)
    base_interval_seconds: int = 90
    
    # Multipliers per time window (higher = more delay)
    window_multipliers: Dict[TimeWindow, float] = field(default_factory=lambda: {
        TimeWindow.PEAK: 1.5,      # More careful during peak hours
        TimeWindow.MODERATE: 1.2,
        TimeWindow.LOW: 0.9,       # Can be slightly faster
        TimeWindow.MINIMAL: 0.7,   # Night mode - faster
    })
    
    # Weekend multiplier (LinkedIn is less monitored)
    weekend_multiplier: float = 0.8
    
    # Jitter range (percentage)
    jitter_min: float = 0.8
    jitter_max: float = 1.2
    
    # Adaptive parameters
    success_streak_reduction: float = 0.95  # Reduce interval after each success
    failure_increase: float = 1.5           # Increase after failure
    max_reduction_factor: float = 0.5       # Don't go below 50% of base
    max_increase_factor: float = 3.0        # Don't go above 300% of base
    
    # Restriction cooldown
    restriction_cooldown_hours: int = 4
    restriction_multiplier: float = 2.5
    
    # Time windows (24h format, Paris timezone)
    peak_hours: List[Tuple[int, int]] = field(default_factory=lambda: [
        (9, 12), (14, 17)
    ])
    moderate_hours: List[Tuple[int, int]] = field(default_factory=lambda: [
        (8, 9), (12, 14), (17, 19)
    ])
    low_hours: List[Tuple[int, int]] = field(default_factory=lambda: [
        (19, 22)
    ])
    # minimal_hours: everything else (22-8)


# =============================================================================
# SCHEDULER EVENTS
# =============================================================================

class SchedulerEvent(str, Enum):
    """Events that affect scheduling."""
    SESSION_SUCCESS = "session_success"
    SESSION_FAILURE = "session_failure"
    RESTRICTION_WARNING = "restriction_warning"
    RESTRICTION_DETECTED = "restriction_detected"
    RATE_LIMIT_HIT = "rate_limit_hit"
    CAPTCHA_DETECTED = "captcha_detected"
    POSTS_FOUND = "posts_found"
    NO_POSTS = "no_posts"


# =============================================================================
# SMART SCHEDULER
# =============================================================================

class SmartScheduler:
    """Adaptive scheduler that optimizes scraping intervals."""
    
    def __init__(
        self, 
        config: Optional[ScheduleConfig] = None,
        db_path: Optional[str] = None,
    ):
        self._config = config or ScheduleConfig()
        self._db_path = db_path or self._default_db_path()
        self._lock = threading.Lock()
        
        # Current state
        self._success_streak = 0
        self._current_multiplier = 1.0
        self._last_restriction: Optional[datetime] = None
        self._paused_until: Optional[datetime] = None
        
        # Statistics
        self._session_count = 0
        self._total_interval_ms = 0
        
        self._load_state()
    
    @staticmethod
    def _default_db_path() -> str:
        if os.name == 'nt':
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            return str(Path(base) / "TitanScraper" / "scheduler.sqlite3")
        else:
            return str(Path.home() / ".local" / "share" / "TitanScraper" / "scheduler.sqlite3")
    
    def _load_state(self) -> None:
        """Load persisted state from SQLite."""
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduler_state (
                    id TEXT PRIMARY KEY,
                    success_streak INTEGER DEFAULT 0,
                    current_multiplier REAL DEFAULT 1.0,
                    last_restriction TEXT,
                    paused_until TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduler_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    event_type TEXT,
                    interval_used INTEGER,
                    metadata TEXT
                )
            """)
            
            cursor = conn.execute("SELECT * FROM scheduler_state WHERE id = 'global'")
            row = cursor.fetchone()
            if row:
                self._success_streak = row[1] or 0
                self._current_multiplier = row[2] or 1.0
                self._last_restriction = datetime.fromisoformat(row[3]) if row[3] else None
                self._paused_until = datetime.fromisoformat(row[4]) if row[4] else None
            
            conn.close()
        except Exception as e:
            logger.warning("scheduler_load_failed", error=str(e))
    
    def _save_state(self) -> None:
        """Persist state to SQLite."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                INSERT OR REPLACE INTO scheduler_state 
                (id, success_streak, current_multiplier, last_restriction, paused_until)
                VALUES (?, ?, ?, ?, ?)
            """, (
                "global",
                self._success_streak,
                self._current_multiplier,
                self._last_restriction.isoformat() if self._last_restriction else None,
                self._paused_until.isoformat() if self._paused_until else None,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("scheduler_save_failed", error=str(e))
    
    def _get_current_time_window(self, dt: Optional[datetime] = None) -> TimeWindow:
        """Determine current time window based on Paris time."""
        if dt is None:
            dt = datetime.now(timezone.utc)
        
        # Convert to Paris time (simplified - just +1/+2 for CET/CEST)
        # In production, use pytz or zoneinfo
        paris_hour = (dt.hour + 1) % 24  # Rough approximation
        
        for start, end in self._config.peak_hours:
            if start <= paris_hour < end:
                return TimeWindow.PEAK
        
        for start, end in self._config.moderate_hours:
            if start <= paris_hour < end:
                return TimeWindow.MODERATE
        
        for start, end in self._config.low_hours:
            if start <= paris_hour < end:
                return TimeWindow.LOW
        
        return TimeWindow.MINIMAL
    
    def _get_day_type(self, dt: Optional[datetime] = None) -> DayType:
        """Determine if current day is weekday or weekend."""
        if dt is None:
            dt = datetime.now(timezone.utc)
        
        # weekday(): Monday=0, Sunday=6
        if dt.weekday() >= 5:
            return DayType.WEEKEND
        return DayType.WEEKDAY
    
    def _apply_jitter(self, interval: float) -> float:
        """Apply random jitter to interval."""
        jitter = random.uniform(self._config.jitter_min, self._config.jitter_max)
        return interval * jitter
    
    def _is_in_cooldown(self) -> bool:
        """Check if we're in restriction cooldown."""
        if self._last_restriction is None:
            return False
        
        cooldown_end = self._last_restriction + timedelta(
            hours=self._config.restriction_cooldown_hours
        )
        return datetime.now(timezone.utc) < cooldown_end
    
    def _calculate_interval_unlocked(self) -> int:
        """Calculate interval without acquiring lock (internal use only).
        
        MUST be called while already holding self._lock.
        """
        # Check if paused
        if self._paused_until and datetime.now(timezone.utc) < self._paused_until:
            remaining = (self._paused_until - datetime.now(timezone.utc)).total_seconds()
            return int(remaining)
        
        # Base interval
        interval = float(self._config.base_interval_seconds)
        
        # Apply time window multiplier
        window = self._get_current_time_window()
        interval *= self._config.window_multipliers.get(window, 1.0)
        
        # Apply weekend multiplier
        if self._get_day_type() == DayType.WEEKEND:
            interval *= self._config.weekend_multiplier
        
        # Apply restriction cooldown
        if self._is_in_cooldown():
            interval *= self._config.restriction_multiplier
        
        # Apply adaptive multiplier from success/failure history
        interval *= self._current_multiplier
        
        # Apply limits
        min_interval = self._config.base_interval_seconds * self._config.max_reduction_factor
        max_interval = self._config.base_interval_seconds * self._config.max_increase_factor
        interval = max(min_interval, min(max_interval, interval))
        
        # Apply jitter
        interval = self._apply_jitter(interval)
        
        return int(interval)
    
    def get_next_interval(self) -> int:
        """Calculate next scraping interval.
        
        Returns:
            Interval in seconds
        """
        with self._lock:
            interval = self._calculate_interval_unlocked()
            
            # Update stats
            self._session_count += 1
            self._total_interval_ms += interval * 1000
            
            return interval
    
    def record_event(self, event: SchedulerEvent, metadata: Optional[Dict] = None) -> None:
        """Record an event that affects scheduling.
        
        Args:
            event: Type of event
            metadata: Additional event data
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            
            if event == SchedulerEvent.SESSION_SUCCESS:
                self._success_streak += 1
                # Gradually reduce interval after successful sessions
                if self._success_streak > 5:
                    self._current_multiplier *= self._config.success_streak_reduction
                    self._current_multiplier = max(
                        self._config.max_reduction_factor,
                        self._current_multiplier
                    )
            
            elif event == SchedulerEvent.SESSION_FAILURE:
                self._success_streak = 0
                self._current_multiplier *= self._config.failure_increase
                self._current_multiplier = min(
                    self._config.max_increase_factor,
                    self._current_multiplier
                )
            
            elif event in (SchedulerEvent.RESTRICTION_WARNING, 
                          SchedulerEvent.RESTRICTION_DETECTED):
                self._last_restriction = now
                self._success_streak = 0
                self._current_multiplier = self._config.max_increase_factor
                
                # Pause for cooldown
                cooldown_hours = self._config.restriction_cooldown_hours
                if event == SchedulerEvent.RESTRICTION_DETECTED:
                    cooldown_hours *= 2  # Double cooldown for actual restriction
                self._paused_until = now + timedelta(hours=cooldown_hours)
                
                logger.warning("scheduler_restriction_detected", 
                              paused_until=self._paused_until.isoformat())
            
            elif event == SchedulerEvent.RATE_LIMIT_HIT:
                # Temporary backoff
                self._current_multiplier = min(
                    self._config.max_increase_factor,
                    self._current_multiplier * 1.5
                )
            
            elif event == SchedulerEvent.CAPTCHA_DETECTED:
                # Significant backoff
                self._current_multiplier = min(
                    self._config.max_increase_factor,
                    self._current_multiplier * 2.0
                )
                self._paused_until = now + timedelta(minutes=30)
            
            elif event == SchedulerEvent.NO_POSTS:
                # Slightly increase interval if nothing found
                self._current_multiplier *= 1.1
                self._current_multiplier = min(
                    self._config.max_increase_factor,
                    self._current_multiplier
                )
            
            # Persist state
            self._save_state()
            
            # Get interval value before releasing lock (avoid deadlock)
            current_interval = self._calculate_interval_unlocked()
            
            # Log event to history
            try:
                conn = sqlite3.connect(self._db_path)
                conn.execute("""
                    INSERT INTO scheduler_events (timestamp, event_type, interval_used, metadata)
                    VALUES (?, ?, ?, ?)
                """, (
                    now.isoformat(),
                    event.value,
                    current_interval,
                    str(metadata) if metadata else None,
                ))
                conn.commit()
                
                # Cleanup old events (keep last 1000)
                conn.execute("""
                    DELETE FROM scheduler_events 
                    WHERE id NOT IN (SELECT id FROM scheduler_events ORDER BY id DESC LIMIT 1000)
                """)
                conn.commit()
                conn.close()
            except Exception as e:
                logger.debug("scheduler_event_log_failed", error=str(e))
    
    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status."""
        window = self._get_current_time_window()
        day_type = self._get_day_type()
        
        return {
            "current_interval_seconds": self.get_next_interval(),
            "time_window": str(window),
            "day_type": str(day_type),
            "success_streak": self._success_streak,
            "current_multiplier": round(self._current_multiplier, 2),
            "in_cooldown": self._is_in_cooldown(),
            "last_restriction": self._last_restriction.isoformat() if self._last_restriction else None,
            "paused_until": self._paused_until.isoformat() if self._paused_until else None,
            "is_paused": bool(self._paused_until and datetime.now(timezone.utc) < self._paused_until),
            "session_count": self._session_count,
            "avg_interval_ms": int(self._total_interval_ms / max(1, self._session_count)),
        }
    
    def get_recommended_schedule(self) -> Dict[str, Any]:
        """Get recommended schedule for today.
        
        Returns estimated intervals for each hour.
        """
        now = datetime.now(timezone.utc)
        schedule = {}
        
        for hour in range(24):
            test_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            window = self._get_current_time_window(test_time)
            
            # Calculate theoretical interval
            interval = self._config.base_interval_seconds
            interval *= self._config.window_multipliers.get(window, 1.0)
            
            if self._get_day_type() == DayType.WEEKEND:
                interval *= self._config.weekend_multiplier
            
            schedule[f"{hour:02d}:00"] = {
                "window": str(window),
                "estimated_interval_seconds": int(interval),
                "sessions_per_hour": int(3600 / interval),
            }
        
        return schedule
    
    def reset(self) -> None:
        """Reset scheduler to default state."""
        with self._lock:
            self._success_streak = 0
            self._current_multiplier = 1.0
            self._last_restriction = None
            self._paused_until = None
            self._save_state()
            logger.info("scheduler_reset")
    
    def pause(self, duration_minutes: int = 30) -> None:
        """Pause scheduler for specified duration."""
        with self._lock:
            self._paused_until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
            self._save_state()
            logger.info("scheduler_paused", until=self._paused_until.isoformat())
    
    def resume(self) -> None:
        """Resume scheduler immediately."""
        with self._lock:
            self._paused_until = None
            self._save_state()
            logger.info("scheduler_resumed")


# =============================================================================
# SINGLETON
# =============================================================================

_scheduler_instance: Optional[SmartScheduler] = None
_scheduler_lock = threading.Lock()


def get_smart_scheduler(config: Optional[ScheduleConfig] = None) -> SmartScheduler:
    """Get or create smart scheduler singleton."""
    global _scheduler_instance
    
    with _scheduler_lock:
        if _scheduler_instance is None:
            _scheduler_instance = SmartScheduler(config)
        return _scheduler_instance


def reset_smart_scheduler() -> None:
    """Reset singleton (for testing)."""
    global _scheduler_instance
    with _scheduler_lock:
        _scheduler_instance = None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_next_interval() -> int:
    """Convenience function to get next interval."""
    return get_smart_scheduler().get_next_interval()


def record_event(event: SchedulerEvent, metadata: Optional[Dict] = None) -> None:
    """Convenience function to record event."""
    get_smart_scheduler().record_event(event, metadata)


__all__ = [
    # Classes
    "SmartScheduler",
    "ScheduleConfig",
    "SchedulerEvent",
    "TimeWindow",
    "DayType",
    
    # Functions
    "get_smart_scheduler",
    "reset_smart_scheduler",
    "get_next_interval",
    "record_event",
]
