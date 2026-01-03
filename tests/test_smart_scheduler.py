"""Tests for scraper/smart_scheduler.py - Adaptive intervals."""
import pytest
import tempfile
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path for direct module import (avoids heavy __init__.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Mock structlog before importing the module to avoid heavy dependencies
import unittest.mock as mock
sys.modules.setdefault('structlog', mock.MagicMock())


class TestTimeWindow:
    """Tests for TimeWindow enum."""
    
    def test_window_values(self):
        from scraper.smart_scheduler import TimeWindow
        
        assert str(TimeWindow.PEAK) == "peak"
        assert str(TimeWindow.MODERATE) == "moderate"
        assert str(TimeWindow.LOW) == "low"
        assert str(TimeWindow.MINIMAL) == "minimal"


class TestDayType:
    """Tests for DayType enum."""
    
    def test_day_type_values(self):
        from scraper.smart_scheduler import DayType
        
        assert str(DayType.WEEKDAY) == "weekday"
        assert str(DayType.WEEKEND) == "weekend"


class TestScheduleConfig:
    """Tests for ScheduleConfig."""
    
    def test_default_config(self):
        from scraper.smart_scheduler import ScheduleConfig
        
        config = ScheduleConfig()
        
        assert config.base_interval_seconds == 90
        assert config.weekend_multiplier == 0.8
        assert len(config.peak_hours) > 0
    
    def test_window_multipliers(self):
        from scraper.smart_scheduler import ScheduleConfig, TimeWindow
        
        config = ScheduleConfig()
        
        # Peak should have higher multiplier (more delay)
        assert config.window_multipliers[TimeWindow.PEAK] > config.window_multipliers[TimeWindow.LOW]


class TestSmartScheduler:
    """Tests for SmartScheduler."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        os.unlink(f.name)
    
    def test_scheduler_initialization(self, temp_db):
        from scraper.smart_scheduler import SmartScheduler, reset_smart_scheduler
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        assert scheduler._current_multiplier == 1.0
        assert scheduler._success_streak == 0
    
    def test_get_next_interval_returns_positive(self, temp_db):
        from scraper.smart_scheduler import SmartScheduler, reset_smart_scheduler
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        interval = scheduler.get_next_interval()
        
        assert interval > 0
        assert isinstance(interval, int)
    
    def test_interval_has_jitter(self, temp_db):
        from scraper.smart_scheduler import SmartScheduler, reset_smart_scheduler
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        intervals = [scheduler.get_next_interval() for _ in range(10)]
        
        # Should have some variation
        assert len(set(intervals)) > 1
    
    def test_record_success_reduces_interval(self, temp_db):
        from scraper.smart_scheduler import (
            SmartScheduler, SchedulerEvent, reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        initial_multiplier = scheduler._current_multiplier
        
        # Record many successes
        for _ in range(10):
            scheduler.record_event(SchedulerEvent.SESSION_SUCCESS)
        
        # Multiplier should have decreased
        assert scheduler._current_multiplier < initial_multiplier
        assert scheduler._success_streak == 10
    
    def test_record_failure_increases_interval(self, temp_db):
        from scraper.smart_scheduler import (
            SmartScheduler, SchedulerEvent, reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        initial_multiplier = scheduler._current_multiplier
        
        scheduler.record_event(SchedulerEvent.SESSION_FAILURE)
        
        assert scheduler._current_multiplier > initial_multiplier
        assert scheduler._success_streak == 0
    
    def test_restriction_triggers_pause(self, temp_db):
        from scraper.smart_scheduler import (
            SmartScheduler, SchedulerEvent, reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        scheduler.record_event(SchedulerEvent.RESTRICTION_DETECTED)
        
        assert scheduler._paused_until is not None
        assert scheduler._last_restriction is not None
        status = scheduler.get_status()
        assert status["is_paused"] is True
    
    def test_captcha_triggers_pause(self, temp_db):
        from scraper.smart_scheduler import (
            SmartScheduler, SchedulerEvent, reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        scheduler.record_event(SchedulerEvent.CAPTCHA_DETECTED)
        
        assert scheduler._paused_until is not None
    
    def test_manual_pause_and_resume(self, temp_db):
        from scraper.smart_scheduler import SmartScheduler, reset_smart_scheduler
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        scheduler.pause(duration_minutes=30)
        assert scheduler.get_status()["is_paused"] is True
        
        scheduler.resume()
        assert scheduler.get_status()["is_paused"] is False
    
    def test_reset(self, temp_db):
        from scraper.smart_scheduler import (
            SmartScheduler, SchedulerEvent, reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        # Modify state
        scheduler._current_multiplier = 2.5
        scheduler._success_streak = 50
        scheduler.pause(30)
        
        # Reset
        scheduler.reset()
        
        assert scheduler._current_multiplier == 1.0
        assert scheduler._success_streak == 0
        assert scheduler._paused_until is None
    
    def test_get_status(self, temp_db):
        from scraper.smart_scheduler import SmartScheduler, reset_smart_scheduler
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        status = scheduler.get_status()
        
        assert "current_interval_seconds" in status
        assert "time_window" in status
        assert "day_type" in status
        assert "success_streak" in status
        assert "is_paused" in status
    
    def test_get_recommended_schedule(self, temp_db):
        from scraper.smart_scheduler import SmartScheduler, reset_smart_scheduler
        
        reset_smart_scheduler()
        scheduler = SmartScheduler(db_path=temp_db)
        
        schedule = scheduler.get_recommended_schedule()
        
        assert len(schedule) == 24  # All hours
        assert "00:00" in schedule
        assert "12:00" in schedule
        
        for hour_data in schedule.values():
            assert "window" in hour_data
            assert "estimated_interval_seconds" in hour_data
            assert "sessions_per_hour" in hour_data
    
    def test_multiplier_limits(self, temp_db):
        from scraper.smart_scheduler import (
            SmartScheduler, SchedulerEvent, ScheduleConfig,
            reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        config = ScheduleConfig()
        scheduler = SmartScheduler(config=config, db_path=temp_db)
        
        # Try to exceed max
        for _ in range(100):
            scheduler.record_event(SchedulerEvent.SESSION_FAILURE)
        
        assert scheduler._current_multiplier <= config.max_increase_factor
        
        # Try to go below min
        reset_smart_scheduler()
        scheduler2 = SmartScheduler(config=config, db_path=temp_db)
        for _ in range(100):
            scheduler2.record_event(SchedulerEvent.SESSION_SUCCESS)
        
        assert scheduler2._current_multiplier >= config.max_reduction_factor
    
    def test_persistence(self, temp_db):
        from scraper.smart_scheduler import (
            SmartScheduler, SchedulerEvent, reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        
        # Create and modify
        scheduler1 = SmartScheduler(db_path=temp_db)
        for _ in range(5):
            scheduler1.record_event(SchedulerEvent.SESSION_SUCCESS)
        
        # New instance
        reset_smart_scheduler()
        scheduler2 = SmartScheduler(db_path=temp_db)
        
        assert scheduler2._success_streak == 5


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        os.unlink(f.name)
    
    def test_get_next_interval_function(self, temp_db):
        from scraper.smart_scheduler import (
            get_next_interval, reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        
        import scraper.smart_scheduler as sched_module
        original = sched_module.SmartScheduler._default_db_path
        sched_module.SmartScheduler._default_db_path = staticmethod(lambda: temp_db)
        
        try:
            interval = get_next_interval()
            assert interval > 0
        finally:
            sched_module.SmartScheduler._default_db_path = original
            reset_smart_scheduler()
    
    def test_record_event_function(self, temp_db):
        from scraper.smart_scheduler import (
            record_event, SchedulerEvent, get_smart_scheduler,
            reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        
        import scraper.smart_scheduler as sched_module
        original = sched_module.SmartScheduler._default_db_path
        sched_module.SmartScheduler._default_db_path = staticmethod(lambda: temp_db)
        
        try:
            record_event(SchedulerEvent.SESSION_SUCCESS)
            assert get_smart_scheduler()._success_streak == 1
        finally:
            sched_module.SmartScheduler._default_db_path = original
            reset_smart_scheduler()
    
    def test_singleton_pattern(self, temp_db):
        from scraper.smart_scheduler import (
            get_smart_scheduler, reset_smart_scheduler
        )
        
        reset_smart_scheduler()
        
        import scraper.smart_scheduler as sched_module
        original = sched_module.SmartScheduler._default_db_path
        sched_module.SmartScheduler._default_db_path = staticmethod(lambda: temp_db)
        
        try:
            sched1 = get_smart_scheduler()
            sched2 = get_smart_scheduler()
            assert sched1 is sched2
        finally:
            sched_module.SmartScheduler._default_db_path = original
            reset_smart_scheduler()
