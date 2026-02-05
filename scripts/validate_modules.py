#!/usr/bin/env python3
"""Validation script for new Titan Scraper modules.

This script tests that all new modules are working correctly before
enabling them in production.

Usage:
    python scripts/validate_modules.py              # Test all modules
    python scripts/validate_modules.py --phase1    # Test Phase 1 only
    python scripts/validate_modules.py --phase2    # Test Phase 2 only
    python scripts/validate_modules.py --quick     # Quick smoke test
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class ValidationResult:
    """Result of a validation test."""
    def __init__(self, name: str, success: bool, message: str, duration_ms: float):
        self.name = name
        self.success = success
        self.message = message
        self.duration_ms = duration_ms


def validate(name: str):
    """Decorator to register a validation test."""
    def decorator(func: Callable):
        func._validation_name = name
        return func
    return decorator


class ModuleValidator:
    """Validates Titan Scraper modules."""
    
    def __init__(self):
        self.results: list[ValidationResult] = []
    
    def run_test(self, func: Callable) -> ValidationResult:
        """Run a single test and record result."""
        name = getattr(func, '_validation_name', func.__name__)
        start = time.perf_counter()
        
        try:
            result = func()
            duration = (time.perf_counter() - start) * 1000
            
            if result is True or result is None:
                return ValidationResult(name, True, "OK", duration)
            elif isinstance(result, str):
                return ValidationResult(name, True, result, duration)
            else:
                return ValidationResult(name, False, str(result), duration)
                
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return ValidationResult(name, False, f"Exception: {e}", duration)
    
    # =========================================================================
    # PHASE 1 TESTS - Low Risk (cache + scheduler)
    # =========================================================================
    
    @validate("PostCache - Import")
    def test_post_cache_import(self):
        from scraper.post_cache import PostCache, get_post_cache
        return True
    
    @validate("PostCache - Signature Generation")
    def test_post_cache_signatures(self):
        from scraper.post_cache import generate_content_signature, generate_url_signature
        
        sig1 = generate_content_signature("Test post content")
        sig2 = generate_content_signature("TEST POST CONTENT")  # Should normalize
        
        assert sig1 == sig2, "Signatures should match after normalization"
        assert len(sig1) == 32, "Signature should be 32 chars"
        return f"Signature: {sig1[:16]}..."
    
    @validate("PostCache - Deduplication")
    def test_post_cache_dedup(self):
        from scraper.post_cache import PostCache, CacheConfig
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            config = CacheConfig(
                memory_size=100,
                enable_persistence=True,
                persist_path=f.name
            )
            cache = PostCache(config=config)
        
        # First check should return False (not seen)
        is_dup1 = cache.is_duplicate(text="Unique post", post_id="12345")
        assert not is_dup1, "First check should not be duplicate"
        
        # Mark as seen
        cache.mark_processed(text="Unique post", post_id="12345")
        
        # Second check should return True (duplicate)
        is_dup2 = cache.is_duplicate(text="Unique post", post_id="12345")
        assert is_dup2, "Second check should be duplicate"
        
        return "Deduplication working"
    
    @validate("SmartScheduler - Import")
    def test_smart_scheduler_import(self):
        from scraper.smart_scheduler import SmartScheduler, get_smart_scheduler
        return True
    
    @validate("SmartScheduler - Interval Calculation")
    def test_smart_scheduler_interval(self):
        from scraper.smart_scheduler import SmartScheduler
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            scheduler = SmartScheduler(db_path=f.name)
        
        interval = scheduler.get_next_interval()
        assert interval > 0, "Interval should be positive"
        assert interval < 7200, "Interval should be less than 2 hours"
        
        return f"Interval: {interval}s"
    
    @validate("SmartScheduler - Success Recording")
    def test_smart_scheduler_success(self):
        from scraper.smart_scheduler import SmartScheduler, SchedulerEvent
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            scheduler = SmartScheduler(db_path=f.name)
        
        initial = scheduler.get_next_interval()
        scheduler.record_event(SchedulerEvent.SESSION_SUCCESS, {"posts_found": 10})
        after = scheduler.get_next_interval()
        
        # After success, interval should stay same or decrease
        assert after <= initial * 1.1, "Interval should not increase much after success"
        return f"Initial: {initial}s, After success: {after}s"
    
    @validate("SmartScheduler - Pause/Resume")
    def test_smart_scheduler_pause(self):
        from scraper.smart_scheduler import SmartScheduler
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            scheduler = SmartScheduler(db_path=f.name)
        
        scheduler.pause(duration_minutes=1)
        status = scheduler.get_status()
        assert status.get("is_paused") == True, "Should be paused"
        
        scheduler.resume()
        status = scheduler.get_status()
        assert status.get("is_paused") == False, "Should be resumed"
        
        return "Pause/Resume working"
    
    # =========================================================================
    # PHASE 2 TESTS - Medium Risk (keywords + progressive)
    # =========================================================================
    
    @validate("KeywordStrategy - Import")
    def test_keyword_strategy_import(self):
        from scraper.keyword_strategy import KeywordStrategy, get_keyword_strategy
        return True
    
    @validate("KeywordStrategy - Batch Selection")
    def test_keyword_strategy_batch(self):
        from scraper.keyword_strategy import KeywordStrategy, reset_keyword_strategy
        import tempfile
        
        reset_keyword_strategy()
        
        keywords = ["juriste", "avocat", "legal counsel", "compliance", "DPO"]
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            strategy = KeywordStrategy(keywords=keywords, db_path=f.name)
        
        batch = strategy.get_next_batch(batch_size=3)
        
        assert len(batch) == 3, f"Should return 3 keywords, got {len(batch)}"
        assert all(k in keywords for k in batch), "All batch keywords should be in original list"
        
        return f"Batch: {batch}"
    
    @validate("ProgressiveMode - Import")
    def test_progressive_mode_import(self):
        from scraper.progressive_mode import ProgressiveModeManager, get_progressive_mode_manager
        return True
    
    @validate("ProgressiveMode - Mode Transitions")
    def test_progressive_mode_transitions(self):
        from scraper.progressive_mode import ProgressiveModeManager, ScrapingMode, reset_progressive_mode_manager
        import tempfile
        
        reset_progressive_mode_manager()
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            manager = ProgressiveModeManager(db_path=f.name)
        
        # Should start conservative
        assert manager.get_current_mode() == ScrapingMode.CONSERVATIVE, "Should start conservative"
        
        # Record many successes to trigger upgrade
        for _ in range(25):
            manager.record_session_result(success=True, posts_found=5)
        
        # Get current mode
        mode = manager.get_current_mode()
        
        return f"Mode: {mode.value}"
    
    @validate("ProgressiveMode - Limits")
    def test_progressive_mode_limits(self):
        from scraper.progressive_mode import ProgressiveModeManager, reset_progressive_mode_manager
        import tempfile
        
        reset_progressive_mode_manager()
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            manager = ProgressiveModeManager(db_path=f.name)
        
        limits = manager.get_current_limits()
        
        assert limits.max_posts_per_keyword > 0, "max_posts_per_keyword should be positive"
        assert limits.keywords_per_batch > 0, "keywords_per_batch should be positive"
        assert limits.autonomous_interval_seconds > 0, "autonomous_interval should be positive"
        
        return f"Limits: {limits.max_posts_per_keyword} posts/kw, {limits.keywords_per_batch} kw, {limits.autonomous_interval_seconds}s"
    
    # =========================================================================
    # FULL TESTS - All modules
    # =========================================================================
    
    @validate("UnifiedFilter - Import")
    def test_unified_filter_import(self):
        from filters.unified import UnifiedFilterConfig, classify_post
        return True
    
    @validate("UnifiedFilter - Classification")
    def test_unified_filter_classify(self):
        from filters.unified import classify_post, PostCategory
        
        # Test relevant legal post
        result = classify_post(
            text="Notre cabinet d'avocats recrute un juriste en CDI à Paris",
            author="Cabinet Dupont",
            company="Cabinet Dupont AARPI"
        )
        
        assert result.category in [PostCategory.RELEVANT, PostCategory.AGENCY]
        return f"Category: {result.category.value}, Confidence: {result.confidence:.2f}"
    
    @validate("MetadataExtractor - Import")
    def test_metadata_extractor_import(self):
        from scraper.metadata_extractor import MetadataExtractor, parse_relative_date
        return True
    
    @validate("MetadataExtractor - Date Parsing")
    def test_metadata_extractor_dates(self):
        from scraper.metadata_extractor import parse_relative_date
        
        # Test French relative dates
        dt = parse_relative_date("il y a 3 jours")
        assert dt is not None, "Should parse French date"
        
        dt2 = parse_relative_date("2d")
        assert dt2 is not None, "Should parse English date"
        
        return "Date parsing working"
    
    @validate("SelectorManager - Import")
    def test_selector_manager_import(self):
        from scraper.css_selectors import SelectorManager, SelectorConfig
        return True
    
    @validate("SelectorManager - Health Report")
    def test_selector_manager_health(self):
        from scraper.css_selectors import SelectorManager
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            manager = SelectorManager(db_path=f.name)
        
        report = manager.get_health_report()
        
        assert "categories" in report, "Should have categories"
        assert "timestamp" in report, "Should have timestamp"
        
        return f"Categories: {list(report['categories'].keys())}"
    
    @validate("MLInterface - Import")
    def test_ml_interface_import(self):
        from scraper.ml_interface import MLInterface, classify_with_ml
        return True
    
    @validate("MLInterface - Heuristic Classification")
    def test_ml_interface_classify(self):
        from scraper.ml_interface import classify_with_ml, MLCategory
        
        result = classify_with_ml(
            text="Nous recrutons un avocat senior en CDI pour notre département juridique",
            author="Enterprise XYZ",
            company="Enterprise XYZ SA"
        )
        
        assert result.category in [MLCategory.LEGAL_RECRUITMENT, MLCategory.AGENCY_RECRUITMENT, MLCategory.UNKNOWN]
        return f"Category: {result.category.value}, Confidence: {result.confidence:.2f}"
    
    @validate("Adapters - Import")
    def test_adapters_import(self):
        from scraper.adapters import (
            get_feature_flags,
            set_feature_flags,
            get_next_keywords,
            get_scraping_limits,
            get_next_interval,
        )
        return True
    
    @validate("Adapters - Feature Flags")
    def test_adapters_flags(self):
        from scraper.adapters import get_feature_flags, set_feature_flags
        
        flags = get_feature_flags()
        assert hasattr(flags, 'use_post_cache'), "Should have use_post_cache flag"
        
        return f"Active flags: {sum(1 for v in flags.__dict__.values() if v)}/{len(flags.__dict__)}"
    
    # =========================================================================
    # TEST RUNNER
    # =========================================================================
    
    def run_phase1(self) -> list[ValidationResult]:
        """Run Phase 1 tests only."""
        tests = [
            self.test_post_cache_import,
            self.test_post_cache_signatures,
            self.test_post_cache_dedup,
            self.test_smart_scheduler_import,
            self.test_smart_scheduler_interval,
            self.test_smart_scheduler_success,
            self.test_smart_scheduler_pause,
        ]
        
        return [self.run_test(t) for t in tests]
    
    def run_phase2(self) -> list[ValidationResult]:
        """Run Phase 2 tests (includes Phase 1)."""
        results = self.run_phase1()
        
        tests = [
            self.test_keyword_strategy_import,
            self.test_keyword_strategy_batch,
            self.test_progressive_mode_import,
            self.test_progressive_mode_transitions,
            self.test_progressive_mode_limits,
        ]
        
        results.extend([self.run_test(t) for t in tests])
        return results
    
    def run_all(self) -> list[ValidationResult]:
        """Run all tests."""
        results = self.run_phase2()
        
        tests = [
            self.test_unified_filter_import,
            self.test_unified_filter_classify,
            self.test_metadata_extractor_import,
            self.test_metadata_extractor_dates,
            self.test_selector_manager_import,
            self.test_selector_manager_health,
            self.test_ml_interface_import,
            self.test_ml_interface_classify,
            self.test_adapters_import,
            self.test_adapters_flags,
        ]
        
        results.extend([self.run_test(t) for t in tests])
        return results
    
    def run_quick(self) -> list[ValidationResult]:
        """Quick smoke test - imports only."""
        tests = [
            self.test_post_cache_import,
            self.test_smart_scheduler_import,
            self.test_keyword_strategy_import,
            self.test_progressive_mode_import,
            self.test_unified_filter_import,
            self.test_metadata_extractor_import,
            self.test_selector_manager_import,
            self.test_ml_interface_import,
            self.test_adapters_import,
        ]
        
        return [self.run_test(t) for t in tests]


def print_results(results: list[ValidationResult], title: str):
    """Print validation results."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")
    
    passed = 0
    failed = 0
    
    for r in results:
        status = "✅" if r.success else "❌"
        print(f"  {status} {r.name}")
        print(f"     └─ {r.message} ({r.duration_ms:.1f}ms)")
        
        if r.success:
            passed += 1
        else:
            failed += 1
    
    print(f"\n{'─'*60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'─'*60}\n")
    
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Validate Titan Scraper modules")
    parser.add_argument("--phase1", action="store_true", help="Test Phase 1 only (cache + scheduler)")
    parser.add_argument("--phase2", action="store_true", help="Test Phase 2 (keywords + progressive + Phase 1)")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test (imports only)")
    
    args = parser.parse_args()
    
    validator = ModuleValidator()
    
    if args.quick:
        results = validator.run_quick()
        title = "Quick Smoke Test"
    elif args.phase1:
        results = validator.run_phase1()
        title = "Phase 1 Validation (cache + scheduler)"
    elif args.phase2:
        results = validator.run_phase2()
        title = "Phase 2 Validation (keywords + progressive + Phase 1)"
    else:
        results = validator.run_all()
        title = "Full Module Validation"
    
    success = print_results(results, title)
    
    if success:
        print("🎉 All validations passed! Modules are ready for activation.\n")
        
        if args.phase1:
            print("To enable Phase 1:")
            print("  - Set environment variable: TITAN_ENABLE_PHASE1=1")
            print("  - Or call: POST /api/feature_flags/enable_phase1")
        elif args.phase2:
            print("To enable Phase 2:")
            print("  - Set environment variable: TITAN_ENABLE_PHASE2=1")
            print("  - Or call: POST /api/feature_flags/enable_phase2")
        else:
            print("To enable all features:")
            print("  - Set environment variable: TITAN_ENABLE_ALL=1")
            print("  - Or call: POST /api/feature_flags/enable_all")
    else:
        print("⚠️  Some validations failed. Please fix before enabling modules.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
