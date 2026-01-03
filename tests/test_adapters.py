"""Tests for scraper/adapters.py - Bridge module tests."""
import pytest


class TestFeatureFlags:
    """Tests for FeatureFlags configuration."""
    
    def test_default_flags_all_disabled(self):
        from scraper.adapters import FeatureFlags
        
        flags = FeatureFlags()
        
        assert flags.use_keyword_strategy is False
        assert flags.use_progressive_mode is False
        assert flags.use_smart_scheduler is False
        assert flags.use_post_cache is False
    
    def test_set_feature_flags(self):
        from scraper.adapters import get_feature_flags, set_feature_flags
        
        # Reset to defaults first
        set_feature_flags(
            use_keyword_strategy=False,
            use_progressive_mode=False,
        )
        
        set_feature_flags(use_keyword_strategy=True)
        
        flags = get_feature_flags()
        assert flags.use_keyword_strategy is True
        
        # Reset
        set_feature_flags(use_keyword_strategy=False)
    
    def test_enable_all_features(self):
        from scraper.adapters import get_feature_flags, set_feature_flags, enable_all_features
        
        # Reset first
        set_feature_flags(
            use_keyword_strategy=False,
            use_progressive_mode=False,
            use_smart_scheduler=False,
        )
        
        enable_all_features()
        
        flags = get_feature_flags()
        assert flags.use_keyword_strategy is True
        assert flags.use_progressive_mode is True
        assert flags.use_smart_scheduler is True
        assert flags.use_post_cache is True
        
        # Reset after test
        set_feature_flags(
            use_keyword_strategy=False,
            use_progressive_mode=False,
            use_smart_scheduler=False,
            use_post_cache=False,
        )


class TestKeywordAdapter:
    """Tests for keyword selection adapter."""
    
    def test_legacy_rotation(self):
        from scraper.adapters import get_next_keywords, set_feature_flags
        
        set_feature_flags(use_keyword_strategy=False)
        
        keywords = ["python", "java", "rust", "go", "kotlin"]
        
        batch1 = get_next_keywords(keywords, batch_size=2)
        batch2 = get_next_keywords(keywords, batch_size=2)
        
        assert len(batch1) == 2
        assert len(batch2) == 2
        # Should rotate through
        assert batch1 != batch2 or len(keywords) <= 2
    
    def test_empty_keywords(self):
        from scraper.adapters import get_next_keywords, set_feature_flags
        
        set_feature_flags(use_keyword_strategy=False)
        
        result = get_next_keywords([], batch_size=3)
        
        assert result == []
    
    def test_record_keyword_result_no_error(self):
        from scraper.adapters import record_keyword_result, set_feature_flags
        
        set_feature_flags(use_keyword_strategy=False)
        
        # Should not raise even without strategy enabled
        record_keyword_result("python", posts_found=5)


class TestLimitsAdapter:
    """Tests for scraping limits adapter."""
    
    def test_default_limits(self):
        from scraper.adapters import get_scraping_limits, set_feature_flags
        
        set_feature_flags(use_progressive_mode=False)
        
        limits = get_scraping_limits(
            default_posts_per_run=100,
            default_keywords_per_run=20,
            default_interval=900,
        )
        
        assert limits.posts_per_run == 100
        assert limits.keywords_per_run == 20
        assert limits.min_interval_seconds == 900
    
    def test_record_restriction_no_error(self):
        from scraper.adapters import record_restriction_event, set_feature_flags
        
        set_feature_flags(use_progressive_mode=False)
        
        # Should not raise
        record_restriction_event("restriction")
        record_restriction_event("captcha")


class TestSchedulingAdapter:
    """Tests for scheduling adapter."""
    
    def test_default_interval(self):
        from scraper.adapters import get_next_interval, set_feature_flags
        
        set_feature_flags(use_smart_scheduler=False)
        
        interval = get_next_interval(default_interval=600)
        
        assert interval == 600
    
    def test_should_scrape_now_legacy(self):
        from scraper.adapters import should_scrape_now, set_feature_flags
        
        set_feature_flags(use_smart_scheduler=False)
        
        should, reason = should_scrape_now()
        
        assert should is True
        assert "legacy" in reason.lower()
    
    def test_pause_resume_no_error(self):
        from scraper.adapters import pause_scheduler, resume_scheduler, set_feature_flags
        
        set_feature_flags(use_smart_scheduler=False)
        
        # Should not raise
        pause_scheduler(3600)
        resume_scheduler()


class TestDeduplicationAdapter:
    """Tests for deduplication adapter."""
    
    def test_no_dedup_when_disabled(self):
        from scraper.adapters import is_duplicate_post, set_feature_flags
        
        set_feature_flags(use_post_cache=False)
        
        # Without cache, nothing is a duplicate
        result = is_duplicate_post(text="Some post content")
        
        assert result is False
    
    def test_mark_seen_no_error(self):
        from scraper.adapters import mark_post_seen, set_feature_flags
        
        set_feature_flags(use_post_cache=False)
        
        # Should not raise
        mark_post_seen(text="Content", url="http://example.com")


class TestFilteringAdapter:
    """Tests for filtering adapter."""
    
    def test_no_filter_returns_true(self):
        from scraper.adapters import should_keep_post, set_feature_flags
        
        set_feature_flags(use_unified_filter=False, use_ml_interface=False)
        
        keep, category, confidence = should_keep_post("Some post text")
        
        assert keep is True
        assert category == "no_filter"
    
    def test_legacy_exclusions(self):
        from scraper.adapters import should_keep_post, set_feature_flags
        
        set_feature_flags(use_unified_filter=False, use_ml_interface=False)
        
        legacy_exclusions = ["spam", "advertisement"]
        
        keep, category, _ = should_keep_post(
            "This is a spam message",
            legacy_exclusions=legacy_exclusions,
        )
        
        assert keep is False
        assert category == "excluded_pattern"


class TestMetadataAdapter:
    """Tests for metadata extraction adapter."""
    
    def test_fallback_extraction(self):
        from scraper.adapters import extract_post_metadata, set_feature_flags
        
        set_feature_flags(use_metadata_extractor=False)
        
        result = extract_post_metadata(
            text="This is a test post with several words",
            raw_author="John Doe",
        )
        
        assert result["author"] == "John Doe"
        assert result["word_count"] == 8
        assert result["language"] == "fr"


class TestSelectorAdapter:
    """Tests for selector adapter."""
    
    def test_fallback_selector(self):
        from scraper.adapters import get_selector, set_feature_flags
        
        set_feature_flags(use_selector_manager=False)
        
        result = get_selector("post_container", fallback=".default-selector")
        
        assert result == ".default-selector"
    
    def test_record_success_no_error(self):
        from scraper.adapters import record_selector_success, set_feature_flags
        
        set_feature_flags(use_selector_manager=False)
        
        # Should not raise
        record_selector_success("post_container")


class TestUnifiedRecording:
    """Tests for unified result recording."""
    
    def test_record_scrape_result(self):
        from scraper.adapters import record_scrape_result, set_feature_flags
        
        set_feature_flags(
            use_keyword_strategy=False,
            use_progressive_mode=False,
            use_smart_scheduler=False,
        )
        
        # Should not raise
        record_scrape_result(
            keywords_processed=["python", "java"],
            posts_found=10,
            posts_stored=8,
            had_restriction=False,
            duration_seconds=30.5,
        )
    
    def test_record_with_restriction(self):
        from scraper.adapters import record_scrape_result, set_feature_flags
        
        set_feature_flags(
            use_keyword_strategy=False,
            use_progressive_mode=False,
            use_smart_scheduler=False,
        )
        
        # Should not raise
        record_scrape_result(
            keywords_processed=["python"],
            posts_found=0,
            posts_stored=0,
            had_restriction=True,
            had_captcha=True,
        )


class TestAdapterStatus:
    """Tests for adapter status reporting."""
    
    def test_get_status_all_disabled(self):
        from scraper.adapters import get_adapter_status, set_feature_flags
        
        set_feature_flags(
            use_keyword_strategy=False,
            use_progressive_mode=False,
            use_smart_scheduler=False,
            use_post_cache=False,
        )
        
        status = get_adapter_status()
        
        assert "feature_flags" in status
        assert "modules" in status
        assert status["feature_flags"]["use_keyword_strategy"] is False
