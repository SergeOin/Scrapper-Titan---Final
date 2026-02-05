"""Session orchestrator for realistic micro-session scheduling.

This module replaces continuous scraping with human-like browsing patterns:
- 5 micro-sessions per day (15-20 min each)
- Natural breaks between sessions
- Time-of-day awareness
- Automatic quota management

Key benefits:
    - Realistic browsing pattern (not robotic)
    - Reduced detection risk
    - Better resource utilization
    - Clear session boundaries for debugging

Architecture:
    - SessionPlan: Static daily plan generated at startup
    - SessionOrchestrator: Runtime manager for session execution
    - Integration with worker.py main loop

Author: Titan Scraper Team
Version: 2.0.0
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Timezone for scheduling (Paris for France-focused scraping)
TIMEZONE = ZoneInfo("Europe/Paris")

# Daily quota target
DAILY_QUOTA_TARGET = 50

# Session configuration
class SessionFocus(str, Enum):
    """Types of session focus."""
    TIER1_CHECK = "tier1_check"      # Priority companies
    TIER2_CHECK = "tier2_check"      # Secondary companies
    EXPLORATION = "exploration"       # New company discovery
    TARGETED_SEARCH = "targeted_search"  # Keyword search (fallback)
    FOLLOWUP = "followup"            # Re-check high-yield pages

    def __str__(self) -> str:
        return self.value


@dataclass
class SessionConfig:
    """Configuration for a single session."""
    start_time: time
    duration_minutes: int
    focus: SessionFocus
    max_pages: int
    priority: int = 0  # Lower = higher priority

    def __post_init__(self):
        # Add natural variance (±20%)
        variance = random.uniform(0.8, 1.2)
        self.duration_minutes = int(self.duration_minutes * variance)


# Default session plan (Monday-Friday)
DEFAULT_WEEKDAY_SESSIONS = [
    SessionConfig(time(9, 0), 15, SessionFocus.TIER1_CHECK, max_pages=5),
    SessionConfig(time(10, 30), 20, SessionFocus.EXPLORATION, max_pages=5),
    SessionConfig(time(11, 45), 15, SessionFocus.FOLLOWUP, max_pages=3),
    SessionConfig(time(14, 30), 20, SessionFocus.TIER2_CHECK, max_pages=6),
    SessionConfig(time(16, 15), 20, SessionFocus.TARGETED_SEARCH, max_pages=4),
]

# Weekend: Reduced activity
DEFAULT_WEEKEND_SESSIONS = [
    SessionConfig(time(10, 0), 15, SessionFocus.TIER1_CHECK, max_pages=3),
    SessionConfig(time(15, 0), 15, SessionFocus.EXPLORATION, max_pages=3),
]

# Hours when scraping is NOT allowed (too suspicious)
BLACKOUT_HOURS = list(range(0, 7)) + list(range(22, 24))  # Midnight-7AM, 10PM-Midnight


# =============================================================================
# SESSION STATE
# =============================================================================

@dataclass
class SessionState:
    """Runtime state of a session."""
    session_id: int
    config: SessionConfig
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    pages_visited: int = 0
    posts_found: int = 0
    posts_qualified: int = 0
    is_active: bool = False

    @property
    def duration_elapsed(self) -> timedelta:
        if not self.started_at:
            return timedelta(0)
        end = self.ended_at or datetime.now(TIMEZONE)
        return end - self.started_at

    @property
    def is_time_expired(self) -> bool:
        if not self.started_at:
            return False
        max_duration = timedelta(minutes=self.config.duration_minutes)
        return self.duration_elapsed >= max_duration

    @property
    def is_pages_exhausted(self) -> bool:
        return self.pages_visited >= self.config.max_pages

    @property
    def should_end(self) -> bool:
        return self.is_time_expired or self.is_pages_exhausted

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "focus": str(self.config.focus),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "duration_minutes": self.config.duration_minutes,
            "elapsed_seconds": self.duration_elapsed.total_seconds(),
            "pages_visited": self.pages_visited,
            "max_pages": self.config.max_pages,
            "posts_found": self.posts_found,
            "posts_qualified": self.posts_qualified,
            "is_active": self.is_active,
            "should_end": self.should_end,
        }


@dataclass
class DailyPlan:
    """Daily session plan."""
    date: datetime
    sessions: List[SessionConfig]
    quota_target: int = DAILY_QUOTA_TARGET

    @property
    def total_max_pages(self) -> int:
        return sum(s.max_pages for s in self.sessions)

    def get_next_session(self, current_time: time) -> Optional[SessionConfig]:
        """Get the next session that should start after current_time."""
        for session in sorted(self.sessions, key=lambda s: s.start_time):
            if session.start_time > current_time:
                return session
        return None

    def get_current_session(self, current_time: time) -> Optional[SessionConfig]:
        """Get the session that should be active at current_time."""
        for session in self.sessions:
            session_end = (datetime.combine(datetime.today(), session.start_time) +
                          timedelta(minutes=session.duration_minutes)).time()
            if session.start_time <= current_time <= session_end:
                return session
        return None


# =============================================================================
# SESSION ORCHESTRATOR
# =============================================================================

class SessionOrchestrator:
    """Orchestrates daily scraping sessions.
    
    This class manages:
    - Daily plan generation with natural variance
    - Session start/stop timing
    - Quota tracking across sessions
    - Integration with worker.py
    """

    def __init__(self, quota_target: int = DAILY_QUOTA_TARGET):
        self.quota_target = quota_target
        self._current_plan: Optional[DailyPlan] = None
        self._current_session: Optional[SessionState] = None
        self._session_counter = 0
        self._daily_posts_qualified = 0
        self._daily_pages_visited = 0
        self._last_plan_date: Optional[datetime] = None

        # Generate initial plan
        self._generate_daily_plan()

    def _generate_daily_plan(self) -> None:
        """Generate plan for today with natural variance."""
        now = datetime.now(TIMEZONE)
        today = now.date()

        # Check if we need a new plan
        if self._last_plan_date and self._last_plan_date.date() == today:
            return

        # Select session template based on day of week
        is_weekend = now.weekday() >= 5
        base_sessions = DEFAULT_WEEKEND_SESSIONS if is_weekend else DEFAULT_WEEKDAY_SESSIONS

        # Add variance to session times (±15 minutes)
        varied_sessions = []
        for config in base_sessions:
            variance_minutes = random.randint(-15, 15)
            base_dt = datetime.combine(today, config.start_time)
            varied_dt = base_dt + timedelta(minutes=variance_minutes)

            # Ensure not in blackout hours
            if varied_dt.hour not in BLACKOUT_HOURS:
                varied_sessions.append(SessionConfig(
                    start_time=varied_dt.time(),
                    duration_minutes=config.duration_minutes,
                    focus=config.focus,
                    max_pages=config.max_pages,
                    priority=config.priority,
                ))

        self._current_plan = DailyPlan(
            date=now,
            sessions=varied_sessions,
            quota_target=self.quota_target,
        )
        self._last_plan_date = now
        self._daily_posts_qualified = 0
        self._daily_pages_visited = 0

        logger.info("daily_plan_generated",
                   date=today.isoformat(),
                   sessions=len(varied_sessions),
                   is_weekend=is_weekend)

    def should_scrape_now(self) -> Tuple[bool, str]:
        """Check if we should be scraping right now.
        
        Returns:
            (should_scrape, reason)
        """
        now = datetime.now(TIMEZONE)
        current_hour = now.hour
        current_time = now.time()

        # Regenerate plan if needed (new day)
        self._generate_daily_plan()

        # Check blackout hours
        if current_hour in BLACKOUT_HOURS:
            return False, "blackout_hours"

        # Check quota
        if self._daily_posts_qualified >= self.quota_target:
            return False, "quota_reached"

        # Check if a session is active or should start
        if self._current_session and self._current_session.is_active:
            if self._current_session.should_end:
                return False, "session_ending"
            return True, "session_active"

        # Check for scheduled session
        if self._current_plan:
            current_session = self._current_plan.get_current_session(current_time)
            if current_session:
                return True, f"session_window:{current_session.focus}"

        return False, "no_session_scheduled"

    def start_session(self) -> Optional[SessionState]:
        """Start a new session if one is scheduled.
        
        Returns:
            SessionState if started, None otherwise
        """
        should_start, reason = self.should_scrape_now()

        if not should_start:
            logger.debug("session_not_started", reason=reason)
            return None

        now = datetime.now(TIMEZONE)

        # Find the session config for now
        if not self._current_plan:
            return None

        config = self._current_plan.get_current_session(now.time())
        if not config:
            return None

        # End any existing session
        if self._current_session and self._current_session.is_active:
            self.end_session()

        # Start new session
        self._session_counter += 1
        self._current_session = SessionState(
            session_id=self._session_counter,
            config=config,
            started_at=now,
            is_active=True,
        )

        logger.info("session_started",
                   session_id=self._session_counter,
                   focus=str(config.focus),
                   max_pages=config.max_pages,
                   duration_minutes=config.duration_minutes)

        return self._current_session

    def end_session(self) -> Optional[dict]:
        """End the current session.
        
        Returns:
            Session summary dict if ended, None otherwise
        """
        if not self._current_session:
            return None

        self._current_session.ended_at = datetime.now(TIMEZONE)
        self._current_session.is_active = False

        summary = self._current_session.to_dict()

        logger.info("session_ended",
                   session_id=self._current_session.session_id,
                   pages=self._current_session.pages_visited,
                   posts_found=self._current_session.posts_found,
                   posts_qualified=self._current_session.posts_qualified,
                   duration=self._current_session.duration_elapsed.total_seconds())

        self._current_session = None
        return summary

    def record_page_visit(self) -> None:
        """Record that a page was visited."""
        self._daily_pages_visited += 1
        if self._current_session:
            self._current_session.pages_visited += 1

    def record_post_found(self, qualified: bool = False) -> None:
        """Record that a post was found."""
        if self._current_session:
            self._current_session.posts_found += 1
            if qualified:
                self._current_session.posts_qualified += 1
                self._daily_posts_qualified += 1

    def should_continue_session(self) -> Tuple[bool, str]:
        """Check if current session should continue.
        
        Returns:
            (should_continue, reason)
        """
        if not self._current_session or not self._current_session.is_active:
            return False, "no_active_session"

        if self._daily_posts_qualified >= self.quota_target:
            return False, "daily_quota_reached"

        if self._current_session.should_end:
            return False, "session_limit_reached"

        return True, "continue"

    def get_current_focus(self) -> Optional[SessionFocus]:
        """Get the focus type of current session."""
        if self._current_session:
            return self._current_session.config.focus
        return None

    def get_session_state(self) -> Optional[dict]:
        """Get current session state as dict."""
        if self._current_session:
            return self._current_session.to_dict()
        return None

    def get_session_quota(self) -> int:
        """Get the post quota for current session.

        Returns 10 posts per micro-session by default.
        """
        if self._current_session and self._current_session.is_active:
            # Calculate remaining quota for this session
            session_target = 10  # ~10 posts per 15-min session
            return max(0, session_target - self._current_session.posts_qualified)
        # Not in session - return daily remaining
        return max(0, self.quota_target - self._daily_posts_qualified)

    def get_daily_stats(self) -> dict:
        """Get daily statistics."""
        return {
            "date": datetime.now(TIMEZONE).date().isoformat(),
            "quota_target": self.quota_target,
            "posts_qualified": self._daily_posts_qualified,
            "pages_visited": self._daily_pages_visited,
            "sessions_completed": self._session_counter,
            "quota_progress": round(self._daily_posts_qualified / self.quota_target, 3),
            "current_session": self.get_session_state(),
        }

    def get_next_session_time(self) -> Optional[datetime]:
        """Get the datetime of the next scheduled session."""
        now = datetime.now(TIMEZONE)

        if not self._current_plan:
            return None

        next_config = self._current_plan.get_next_session(now.time())
        if next_config:
            return datetime.combine(now.date(), next_config.start_time, tzinfo=TIMEZONE)

        return None

    def get_wait_seconds(self) -> int:
        """Get seconds to wait until next session.
        
        Returns:
            Seconds to wait, or 0 if should scrape now
        """
        should_start, _ = self.should_scrape_now()
        if should_start:
            return 0

        next_session = self.get_next_session_time()
        if next_session:
            now = datetime.now(TIMEZONE)
            wait = (next_session - now).total_seconds()
            return max(0, int(wait))

        # No more sessions today, wait until tomorrow 9 AM
        now = datetime.now(TIMEZONE)
        tomorrow_9am = datetime.combine(
            now.date() + timedelta(days=1),
            time(9, 0),
            tzinfo=TIMEZONE
        )
        return int((tomorrow_9am - now).total_seconds())


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_orchestrator_instance: Optional[SessionOrchestrator] = None


def get_orchestrator(quota_target: int = DAILY_QUOTA_TARGET) -> SessionOrchestrator:
    """Get the global session orchestrator instance."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = SessionOrchestrator(quota_target=quota_target)
    return _orchestrator_instance

# Alias for adapters.py compatibility
get_session_orchestrator = get_orchestrator

def reset_orchestrator() -> None:
    """Reset the global orchestrator instance."""
    global _orchestrator_instance
    _orchestrator_instance = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_good_time_to_scrape() -> Tuple[bool, str]:
    """Quick check if it's a good time to scrape.
    
    Use this for fast checks without full orchestrator logic.
    """
    now = datetime.now(TIMEZONE)

    if now.hour in BLACKOUT_HOURS:
        return False, "blackout"

    # Check for extreme hours (very early/late)
    if now.hour < 8 or now.hour > 20:
        return False, "off_hours"

    return True, "ok"


def calculate_natural_delay(base_seconds: int, variance: float = 0.3) -> int:
    """Calculate a natural delay with variance.
    
    Args:
        base_seconds: Base delay in seconds
        variance: Variance as fraction (0.3 = ±30%)
    
    Returns:
        Delay in seconds with natural variance
    """
    min_delay = int(base_seconds * (1 - variance))
    max_delay = int(base_seconds * (1 + variance))
    return random.randint(min_delay, max_delay)
