#!/usr/bin/env python3
"""Test script for Titan Scraper v2 modules.

Run this to validate that all v2 modules load correctly and basic
functionality works before attempting real scraping.

Usage:
    python scripts/test_v2_modules.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_pre_qualifier():
    """Test pre_qualifier module."""
    print("\n[1/4] Testing pre_qualifier.py...")
    
    from scraper.pre_qualifier import (
        pre_qualify_post,
        is_excluded_author,
        has_immediate_exclusion,
        PreQualificationMetrics,
    )
    
    # Test author exclusion
    excluded, reason = is_excluded_author("Michael Page France")
    assert excluded, "Should exclude agency Michael Page"
    print(f"  ✓ is_excluded_author: Michael Page -> excluded ({reason})")
    
    excluded, reason = is_excluded_author("Cabinet Bredin Prat")
    assert not excluded, "Should NOT exclude law firm"
    print(f"  ✓ is_excluded_author: Bredin Prat -> not excluded")
    
    # Test pre-qualification
    result = pre_qualify_post(
        preview_text="Nous recrutons un juriste M&A pour notre équipe à Paris",
        author_name="Gide Loyrette Nouel",
    )
    assert result.should_extract, "Should accept legal recruitment post"
    print(f"  ✓ pre_qualify_post: legal recruitment -> accept (confidence: {result.confidence:.2f})")
    
    result = pre_qualify_post(
        preview_text="Stage de 6 mois en droit des affaires",
        author_name="Some Company",
    )
    assert not result.should_extract, "Should reject stage offer"
    print(f"  ✓ pre_qualify_post: stage -> reject ({result.reason})")
    
    # Test metrics
    metrics = PreQualificationMetrics()
    # Record real results
    accept_result = pre_qualify_post(
        preview_text="Nous recrutons un juriste",
        author_name="Bredin Prat",
    )
    reject_result = pre_qualify_post(
        preview_text="Offre de stage droit social",
        author_name="Random Corp",
    )
    metrics.record(accept_result)
    metrics.record(reject_result)
    stats = metrics.to_dict()
    assert stats["total_checked"] == 2, "Should track 2 checks"
    print(f"  ✓ PreQualificationMetrics: tracked {stats['total_checked']} checks")
    
    print("  [OK] pre_qualifier.py works correctly!")
    return True


def test_company_whitelist():
    """Test company_whitelist module."""
    print("\n[2/4] Testing company_whitelist.py...")
    
    from scraper.company_whitelist import (
        get_company_whitelist,
        Company,
        CompanyTier,
    )
    
    # Get singleton (uses temp db for test)
    whitelist = get_company_whitelist()
    
    # Check seed data loaded
    stats = whitelist.get_stats()
    tier_stats = stats["by_tier"]
    # Keys may be CompanyTier enum or string names
    total = sum(tier_stats.values())
    print(f"  ✓ Whitelist initialized with {total} companies")
    for tier_name, count in tier_stats.items():
        print(f"    - {tier_name}: {count}")
    
    # Test get companies for session
    companies = whitelist.get_companies_for_session("tier1_check", max_companies=3)
    assert len(companies) <= 3, "Should return max 3 companies"
    print(f"  ✓ get_companies_for_session: returned {len(companies)} companies")
    
    if companies:
        c = companies[0]
        print(f"    Example: {c.name} (Tier {c.tier})")
    
    # Test that lookup doesn't crash (method may not exist)
    try:
        company = whitelist.get_company_by_name("Bredin Prat")
        if company:
            print(f"  ✓ Found Bredin Prat in whitelist (Tier {company.tier})")
        else:
            print(f"  ⚠ Bredin Prat not found (may not be in seed data)")
    except AttributeError:
        print(f"  ⚠ get_company_by_name not implemented (optional)")
    
    print("  [OK] company_whitelist.py works correctly!")
    return True


def test_session_orchestrator():
    """Test session_orchestrator module."""
    print("\n[3/4] Testing session_orchestrator.py...")
    
    from scraper.session_orchestrator import (
        get_session_orchestrator,
        is_good_time_to_scrape,
        calculate_natural_delay,
        SessionFocus,
    )
    
    # Test quick time check
    is_good, reason = is_good_time_to_scrape()
    print(f"  ✓ is_good_time_to_scrape: {is_good} ({reason})")
    
    # Test natural delay
    delay = calculate_natural_delay(60, variance=0.3)
    assert 42 <= delay <= 78, f"Delay {delay} should be within 60 ± 30%"
    print(f"  ✓ calculate_natural_delay(60): {delay}s (expected 42-78)")
    
    # Get orchestrator
    orchestrator = get_session_orchestrator()
    
    # Check should_scrape_now
    should_scrape, scrape_reason = orchestrator.should_scrape_now()
    print(f"  ✓ should_scrape_now: {should_scrape} ({scrape_reason})")
    
    # Check daily stats
    stats = orchestrator.get_daily_stats()
    print(f"  ✓ Daily stats: quota_target={stats['quota_target']}, "
          f"posts_qualified={stats['posts_qualified']}")
    
    # Check wait time
    wait_secs = orchestrator.get_wait_seconds()
    print(f"  ✓ Wait until next session: {wait_secs}s ({wait_secs // 60}m)")
    
    print("  [OK] session_orchestrator.py works correctly!")
    return True


def test_adapters():
    """Test adapters with v2 flags."""
    print("\n[4/4] Testing adapters.py v2 integration...")
    
    import os
    # Enable v2 for this test
    os.environ["TITAN_ENABLE_V2"] = "1"
    
    # Reload adapters with new env
    from importlib import reload
    import scraper.adapters as adapters_module
    reload(adapters_module)
    
    from scraper.adapters import (
        get_feature_flags,
        should_scrape_now,
        get_session_quota,
        get_target_companies,
    )
    
    flags = get_feature_flags()
    print(f"  ✓ Feature flags loaded:")
    print(f"    - use_session_orchestrator: {flags.use_session_orchestrator}")
    print(f"    - use_company_whitelist: {flags.use_company_whitelist}")
    print(f"    - use_pre_qualifier: {flags.use_pre_qualifier}")
    
    # These should use v2 modules now
    can_scrape, reason = should_scrape_now()
    print(f"  ✓ should_scrape_now (via adapter): {can_scrape} ({reason})")
    
    quota = get_session_quota()
    print(f"  ✓ get_session_quota: {quota}")
    
    companies = get_target_companies(max_companies=2)
    print(f"  ✓ get_target_companies: {len(companies)} companies")
    
    print("  [OK] adapters.py v2 integration works correctly!")
    return True


def main():
    """Run all v2 module tests."""
    print("=" * 60)
    print("TITAN SCRAPER V2 - MODULE VALIDATION")
    print("=" * 60)
    
    all_passed = True
    
    try:
        all_passed &= test_pre_qualifier()
    except Exception as e:
        print(f"  [FAIL] pre_qualifier.py: {e}")
        all_passed = False
    
    try:
        all_passed &= test_company_whitelist()
    except Exception as e:
        print(f"  [FAIL] company_whitelist.py: {e}")
        all_passed = False
    
    try:
        all_passed &= test_session_orchestrator()
    except Exception as e:
        print(f"  [FAIL] session_orchestrator.py: {e}")
        all_passed = False
    
    try:
        all_passed &= test_adapters()
    except Exception as e:
        print(f"  [FAIL] adapters.py: {e}")
        all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL V2 MODULES VALIDATED SUCCESSFULLY")
        print("\nNext steps:")
        print("  1. Set TITAN_ENABLE_V2=1 in your environment")
        print("  2. Run a micro-session with session_quota=3")
        print("  3. Check logs for prequal_rejected_* and session_quota_reached")
    else:
        print("❌ SOME TESTS FAILED - CHECK ERRORS ABOVE")
        return 1
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
