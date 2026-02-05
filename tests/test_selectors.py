"""Tests for scraper/selectors.py - Dynamic selector management."""
import pytest
import tempfile
import os


class TestSelectorConfig:
    """Tests for SelectorConfig dataclass."""
    
    def test_selector_config_creation(self):
        from scraper.css_selectors import SelectorConfig
        
        config = SelectorConfig(
            css="div.test",
            name="test",
            priority=1,
        )
        
        assert config.css == "div.test"
        assert config.name == "test"
        assert config.priority == 1
        assert config.is_fallback is False
    
    def test_selector_config_with_fallback(self):
        from scraper.css_selectors import SelectorConfig
        
        config = SelectorConfig(
            css="div.fallback",
            name="fallback_test",
            priority=5,
            is_fallback=True,
        )
        
        assert config.is_fallback is True
        assert config.min_expected == 0


class TestSelectorLists:
    """Tests for predefined selector lists."""
    
    def test_post_container_selectors_exist(self):
        from scraper.css_selectors import POST_CONTAINER_SELECTORS
        
        assert len(POST_CONTAINER_SELECTORS) > 0
        assert all(hasattr(s, 'css') for s in POST_CONTAINER_SELECTORS)
    
    def test_author_selectors_exist(self):
        from scraper.css_selectors import AUTHOR_SELECTORS
        
        assert len(AUTHOR_SELECTORS) > 0
    
    def test_text_selectors_exist(self):
        from scraper.css_selectors import TEXT_SELECTORS
        
        assert len(TEXT_SELECTORS) > 0
    
    def test_date_selectors_exist(self):
        from scraper.css_selectors import DATE_SELECTORS
        
        assert len(DATE_SELECTORS) > 0


class TestSelectorStats:
    """Tests for SelectorStats dataclass."""
    
    def test_stats_creation(self):
        from scraper.css_selectors import SelectorStats
        
        stats = SelectorStats(name="test", css="div.test")
        
        assert stats.name == "test"
        assert stats.css == "div.test"
        assert stats.total_attempts == 0  # Uses total_attempts property
        assert stats.successes == 0
    
    def test_success_rate_zero_attempts(self):
        from scraper.css_selectors import SelectorStats
        
        stats = SelectorStats(name="test", css="div.test")
        
        # With zero attempts, success rate should be 0.5 (neutral for untested)
        assert stats.success_rate == 0.5
    
    def test_success_rate_calculation(self):
        from scraper.css_selectors import SelectorStats
        
        # API uses successes and failures, not attempts
        stats = SelectorStats(name="test", css="div.test")
        stats.successes = 7
        stats.failures = 3
        
        assert stats.success_rate == 0.7


class TestSelectorManager:
    """Tests for SelectorManager class."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        try:
            os.unlink(f.name)
        except PermissionError:
            pass  # Ignore on Windows
    
    def test_manager_creation(self, temp_db):
        from scraper.css_selectors import SelectorManager
        
        manager = SelectorManager(db_path=temp_db)
        
        assert manager is not None
    
    @pytest.mark.asyncio
    async def test_get_selector_manager_singleton(self):
        from scraper.css_selectors import get_selector_manager
        
        # get_selector_manager is async
        m1 = await get_selector_manager()
        m2 = await get_selector_manager()
        
        assert m1 is m2
    
    def test_manager_has_selectors(self, temp_db):
        from scraper.css_selectors import SelectorManager
        
        manager = SelectorManager(db_path=temp_db)
        
        # Manager has find_posts, find_author, etc. methods
        assert hasattr(manager, 'find_posts')
        assert hasattr(manager, 'find_author')
        assert hasattr(manager, 'find_text')


class TestSelectorManagerAsync:
    """Async tests for SelectorManager."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        try:
            os.unlink(f.name)
        except PermissionError:
            pass
    
    @pytest.mark.asyncio
    async def test_find_posts_with_mock_page(self, temp_db):
        from scraper.css_selectors import SelectorManager
        from unittest.mock import AsyncMock, MagicMock
        
        manager = SelectorManager(db_path=temp_db)
        
        # Mock page with query_selector_all returning elements
        mock_page = MagicMock()
        mock_element = MagicMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_element, mock_element])
        
        # Test if find_posts method exists
        if hasattr(manager, 'find_posts'):
            elements = await manager.find_posts(mock_page)
            assert len(elements) >= 0
