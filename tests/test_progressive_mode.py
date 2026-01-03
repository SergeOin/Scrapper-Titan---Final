"""Tests for scraper/progressive_mode.py - Adaptive scraping limits."""
import pytest
import tempfile
import os
from datetime import datetime, timezone, timedelta


class TestScrapingMode:
    """Tests for ScrapingMode enum."""
    
    def test_mode_values(self):
        from scraper.progressive_mode import ScrapingMode
        
        assert str(ScrapingMode.CONSERVATIVE) == "conservative"
        assert str(ScrapingMode.MODERATE) == "moderate"
        assert str(ScrapingMode.AGGRESSIVE) == "aggressive"


class TestModeLimits:
    """Tests for ModeLimits dataclass."""
    
    def test_conservative_limits(self):
        from scraper.progressive_mode import MODE_LIMITS, ScrapingMode
        
        limits = MODE_LIMITS[ScrapingMode.CONSERVATIVE]
        
        assert limits.max_posts_per_keyword == 8
        assert limits.keywords_per_batch == 3
        assert limits.keyword_delay_min_ms >= 30000
    
    def test_moderate_limits(self):
        from scraper.progressive_mode import MODE_LIMITS, ScrapingMode
        
        limits = MODE_LIMITS[ScrapingMode.MODERATE]
        
        assert limits.max_posts_per_keyword > 8
        assert limits.keywords_per_batch > 3
        assert limits.keyword_delay_min_ms < 30000
    
    def test_aggressive_limits(self):
        from scraper.progressive_mode import MODE_LIMITS, ScrapingMode
        
        limits = MODE_LIMITS[ScrapingMode.AGGRESSIVE]
        
        assert limits.max_posts_per_keyword >= 20
        assert limits.keywords_per_batch >= 5
    
    def test_limits_to_dict(self):
        from scraper.progressive_mode import MODE_LIMITS, ScrapingMode
        
        limits = MODE_LIMITS[ScrapingMode.CONSERVATIVE]
        d = limits.to_dict()
        
        assert "mode" in d
        assert "max_posts_per_keyword" in d
        assert "keyword_delay_min_ms" in d


class TestProgressiveModeManager:
    """Tests for ProgressiveModeManager."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        os.unlink(f.name)
    
    def test_manager_initialization(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        # Should start in conservative mode
        assert manager.get_current_mode() == ScrapingMode.CONSERVATIVE
    
    def test_record_success_increments_counter(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        initial_sessions = manager._successful_sessions
        manager.record_session_result(success=True, posts_found=10)
        
        assert manager._successful_sessions == initial_sessions + 1
    
    def test_restriction_resets_to_conservative(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        # Simulate being in moderate mode
        manager._current_mode = ScrapingMode.MODERATE
        manager._successful_sessions = 30
        
        # Record restriction
        manager.record_session_result(
            success=False, 
            posts_found=0, 
            restriction_detected=True
        )
        
        assert manager.get_current_mode() == ScrapingMode.CONSERVATIVE
        assert manager._successful_sessions == 0
        assert manager._last_restriction is not None
    
    def test_upgrade_conservative_to_moderate(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        # Simulate conditions for upgrade
        manager._last_restriction = datetime.now(timezone.utc) - timedelta(days=10)
        manager._successful_sessions = manager.CONSERVATIVE_TO_MODERATE_SESSIONS - 1
        
        # One more success should trigger upgrade
        manager.record_session_result(success=True, posts_found=10)
        
        assert manager.get_current_mode() == ScrapingMode.MODERATE
    
    def test_upgrade_moderate_to_aggressive(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        # Simulate conditions for aggressive upgrade
        manager._current_mode = ScrapingMode.MODERATE
        manager._last_restriction = datetime.now(timezone.utc) - timedelta(days=20)
        manager._successful_sessions = manager.MODERATE_TO_AGGRESSIVE_SESSIONS - 1
        
        manager.record_session_result(success=True, posts_found=15)
        
        assert manager.get_current_mode() == ScrapingMode.AGGRESSIVE
    
    def test_manual_override(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        # Set manual override
        manager.set_manual_override(ScrapingMode.AGGRESSIVE)
        
        assert manager.get_current_mode() == ScrapingMode.AGGRESSIVE
        
        # Clear override
        manager.set_manual_override(None)
        
        assert manager.get_current_mode() == ScrapingMode.CONSERVATIVE
    
    def test_get_current_limits(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, MODE_LIMITS, 
            reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        limits = manager.get_current_limits()
        
        assert limits == MODE_LIMITS[ScrapingMode.CONSERVATIVE]
    
    def test_get_status(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        status = manager.get_status()
        
        assert "current_mode" in status
        assert "successful_sessions" in status
        assert "limits" in status
        assert "thresholds" in status
    
    def test_reset_to_conservative(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        # Simulate advanced state
        manager._current_mode = ScrapingMode.AGGRESSIVE
        manager._successful_sessions = 100
        manager._manual_override = ScrapingMode.AGGRESSIVE
        
        # Reset
        manager.reset_to_conservative()
        
        assert manager.get_current_mode() == ScrapingMode.CONSERVATIVE
        assert manager._successful_sessions == 0
        assert manager._manual_override is None
    
    def test_failure_downgrade(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        manager = ProgressiveModeManager(db_path=temp_db)
        
        # Start in aggressive
        manager._current_mode = ScrapingMode.AGGRESSIVE
        
        # Record multiple failures
        for _ in range(5):
            manager.record_session_result(success=False)
        
        # Should have downgraded
        assert manager.get_current_mode() in [ScrapingMode.MODERATE, ScrapingMode.CONSERVATIVE]
    
    def test_persistence(self, temp_db):
        from scraper.progressive_mode import (
            ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        
        # Create and modify
        manager1 = ProgressiveModeManager(db_path=temp_db)
        manager1._current_mode = ScrapingMode.MODERATE
        manager1._successful_sessions = 25
        manager1._save_state()
        
        # Create new instance
        reset_progressive_mode_manager()
        manager2 = ProgressiveModeManager(db_path=temp_db)
        
        assert manager2._current_mode == ScrapingMode.MODERATE
        assert manager2._successful_sessions == 25


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        os.unlink(f.name)
    
    def test_get_current_limits(self, temp_db):
        from scraper.progressive_mode import (
            get_current_limits, get_progressive_mode_manager,
            reset_progressive_mode_manager, ScrapingMode
        )
        
        reset_progressive_mode_manager()
        
        # Patch default path
        import scraper.progressive_mode as pm_module
        original = pm_module.ProgressiveModeManager._default_db_path
        pm_module.ProgressiveModeManager._default_db_path = staticmethod(lambda: temp_db)
        
        try:
            limits = get_current_limits()
            assert limits.mode == ScrapingMode.CONSERVATIVE
        finally:
            pm_module.ProgressiveModeManager._default_db_path = original
            reset_progressive_mode_manager()
    
    def test_record_session(self, temp_db):
        from scraper.progressive_mode import (
            record_session, get_progressive_mode_manager,
            reset_progressive_mode_manager
        )
        
        reset_progressive_mode_manager()
        
        import scraper.progressive_mode as pm_module
        original = pm_module.ProgressiveModeManager._default_db_path
        pm_module.ProgressiveModeManager._default_db_path = staticmethod(lambda: temp_db)
        
        try:
            result = record_session(success=True, posts_found=5)
            assert result is not None
        finally:
            pm_module.ProgressiveModeManager._default_db_path = original
            reset_progressive_mode_manager()
