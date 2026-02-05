"""Integration guide and patches for new modules.

This file provides code examples for integrating the new modules into
the existing codebase. It's designed as a reference and can be imported
to get helper functions.

Modules to integrate:
1. selectors.py - Dynamic CSS selectors
2. keyword_strategy.py - Keyword rotation with scoring
3. progressive_mode.py - Adaptive scraping limits
4. unified.py - Single source of truth for filtering
5. metadata_extractor.py - Robust metadata extraction
6. post_cache.py - Deduplication cache
7. smart_scheduler.py - Adaptive intervals
8. ml_interface.py - ML classification plug-in

Author: Titan Scraper Team
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# =============================================================================
# INTEGRATION INSTRUCTIONS
# =============================================================================

INTEGRATION_GUIDE = """
# INTEGRATION GUIDE FOR NEW MODULES
# ==================================

## 1. DYNAMIC SELECTORS (selectors.py)
=====================================

In scrape_subprocess.py, replace hardcoded selectors:

BEFORE:
```python
posts = await page.query_selector_all("div.feed-shared-update-v2")
```

AFTER:
```python
from scraper.css_selectors import get_selector_manager

selector_mgr = get_selector_manager()
posts = await selector_mgr.find_posts(page)
```

For individual elements:
```python
# Author
author_el = await selector_mgr.find_author(post_el)
# Text
text_el = await selector_mgr.find_text(post_el)
# Date
date_el = await selector_mgr.find_date(post_el)
```


## 2. KEYWORD STRATEGY (keyword_strategy.py)
============================================

In worker.py, replace keyword rotation logic:

BEFORE:
```python
def _get_next_keywords_batch(self):
    batch = self.search_keywords[self._keyword_rotation_index:...]
    self._keyword_rotation_index += 3
    return batch
```

AFTER:
```python
from scraper.keyword_strategy import get_keyword_strategy

def _get_next_keywords_batch(self):
    strategy = get_keyword_strategy()
    return strategy.get_next_batch(batch_size=3)

def _record_keyword_results(self, keyword: str, posts_found: int, relevant_count: int):
    strategy = get_keyword_strategy()
    strategy.record_result(keyword, posts_found > 0, posts_found, relevant_count)
```


## 3. PROGRESSIVE MODE (progressive_mode.py)
============================================

In worker.py or autonomous mode:

BEFORE:
```python
MAX_POSTS_PER_KEYWORD = 8
KEYWORD_DELAY_MIN = 30000
```

AFTER:
```python
from scraper.progressive_mode import get_progressive_mode_manager, get_current_limits

limits = get_current_limits()
MAX_POSTS_PER_KEYWORD = limits.max_posts_per_keyword
KEYWORD_DELAY_MIN = limits.keyword_delay_min_ms

# After successful session
manager = get_progressive_mode_manager()
manager.record_session_result(success=True, posts_found=15)

# After restriction detected
manager.record_session_result(success=False, restriction_detected=True)
```


## 4. UNIFIED FILTERING (filters/unified.py)
============================================

Replace imports from multiple files:

BEFORE:
```python
from filters.juridique import LEGAL_ROLE_KEYWORDS
from scraper.legal_filter import is_legal_recruitment_post
from scraper.legal_classifier import classify_intent
```

AFTER:
```python
from filters.unified import (
    classify_post, 
    is_relevant_post,
    LEGAL_ROLES,
    PostCategory,
)

# Simple check
if is_relevant_post(text, author, company):
    # Process post
    pass

# Detailed classification
result = classify_post(text, author, company)
if result.is_relevant:
    print(f"Legal score: {result.legal_score}")
    print(f"Matched: {result.matched_patterns}")
```


## 5. METADATA EXTRACTOR (metadata_extractor.py)
================================================

In scrape_subprocess.py, replace manual extraction:

BEFORE:
```python
author = await author_el.inner_text() if author_el else ""
date_text = await date_el.inner_text() if date_el else ""
# ... lots of manual parsing
```

AFTER:
```python
from scraper.metadata_extractor import extract_metadata

metadata = extract_metadata(
    text_content=post_text,
    author_name=raw_author,
    author_title=raw_title,
    author_url=author_link,
    date_text=raw_date,
    company_name=raw_company,
    company_url=company_link,
    permalink=post_url,
)

# Use cleaned data
author_name = metadata.author.name
post_date = metadata.date.parsed_date
company = metadata.company.name
permalink = metadata.permalink.url
```


## 6. POST CACHE (post_cache.py)
================================

In worker.py or scrape_subprocess.py:

BEFORE:
```python
# No deduplication, or using set()
seen_urls = set()
if url in seen_urls:
    continue
```

AFTER:
```python
from scraper.post_cache import is_duplicate, mark_processed

# Before processing
if is_duplicate(url=post_url, post_id=post_id, text=post_text):
    logger.debug("skipping_duplicate")
    continue

# After successful processing
mark_processed(url=post_url, post_id=post_id, text=post_text)
```


## 7. SMART SCHEDULER (smart_scheduler.py)
==========================================

In worker.py, replace fixed intervals:

BEFORE:
```python
AUTONOMOUS_INTERVAL = 120  # Fixed 2 minutes
await asyncio.sleep(AUTONOMOUS_INTERVAL)
```

AFTER:
```python
from scraper.smart_scheduler import (
    get_next_interval, 
    record_event, 
    SchedulerEvent,
)

# Get adaptive interval
interval = get_next_interval()
await asyncio.sleep(interval)

# Record events
record_event(SchedulerEvent.SESSION_SUCCESS)
# or
record_event(SchedulerEvent.RESTRICTION_WARNING)
```


## 8. ML INTERFACE (ml_interface.py)
====================================

For ML-enhanced classification:

```python
from scraper.ml_interface import classify_with_ml, is_relevant_ml

# Simple check
if is_relevant_ml(text, author, company):
    # Process post
    pass

# Detailed result
result = classify_with_ml(text, author, company)
print(f"Category: {result.category}")
print(f"Confidence: {result.confidence}")
print(f"Backend used: {result.model_name}")
```

To add a custom ML backend:
```python
from scraper.ml_interface import get_ml_interface, BaseMLClassifier

class MyCustomClassifier(BaseMLClassifier):
    @property
    def name(self) -> str:
        return "custom_v1"
    
    @property  
    def is_available(self) -> bool:
        return True
    
    def classify(self, text, author="", company=""):
        # Your logic here
        pass

ml = get_ml_interface()
ml.register_backend("custom", MyCustomClassifier())
ml.switch_backend("custom")
```


## 9. ROUTES.PY ENDPOINTS
=========================

Add these endpoints to server/routes.py:

```python
from scraper.css_selectors import get_selector_manager
from scraper.keyword_strategy import get_keyword_strategy
from scraper.progressive_mode import get_progressive_mode_manager
from scraper.smart_scheduler import get_smart_scheduler
from scraper.post_cache import get_post_cache
from scraper.ml_interface import get_ml_interface

@app.get("/api/selector_health")
async def selector_health():
    return get_selector_manager().get_health_report()

@app.get("/api/keyword_stats")
async def keyword_stats():
    return get_keyword_strategy().get_stats_report()

@app.get("/api/progressive_mode")
async def progressive_mode_status():
    return get_progressive_mode_manager().get_status()

@app.get("/api/scheduler_status")
async def scheduler_status():
    return get_smart_scheduler().get_status()

@app.get("/api/cache_stats")
async def cache_stats():
    return get_post_cache().get_stats()

@app.get("/api/ml_status")
async def ml_status():
    return get_ml_interface().get_status()

@app.get("/api/system_health")
async def system_health():
    '''Unified health endpoint for all new modules.'''
    return {
        "selectors": get_selector_manager().get_health_report(),
        "keywords": get_keyword_strategy().get_stats_report(),
        "progressive_mode": get_progressive_mode_manager().get_status(),
        "scheduler": get_smart_scheduler().get_status(),
        "cache": get_post_cache().get_stats(),
        "ml": get_ml_interface().get_status(),
    }
```
"""


# =============================================================================
# HELPER FUNCTIONS FOR GRADUAL INTEGRATION
# =============================================================================

def get_integration_status() -> Dict[str, bool]:
    """Check which modules are available and loaded."""
    status = {}
    
    modules = [
        ("selectors", "scraper.css_selectors", "get_selector_manager"),
        ("keyword_strategy", "scraper.keyword_strategy", "get_keyword_strategy"),
        ("progressive_mode", "scraper.progressive_mode", "get_progressive_mode_manager"),
        ("unified_filters", "filters.unified", "get_filter_config"),
        ("metadata_extractor", "scraper.metadata_extractor", "get_metadata_extractor"),
        ("post_cache", "scraper.post_cache", "get_post_cache"),
        ("smart_scheduler", "scraper.smart_scheduler", "get_smart_scheduler"),
        ("ml_interface", "scraper.ml_interface", "get_ml_interface"),
    ]
    
    for name, module_path, func_name in modules:
        try:
            module = __import__(module_path, fromlist=[func_name])
            getattr(module, func_name)()
            status[name] = True
        except Exception:
            status[name] = False
    
    return status


def get_all_health_reports() -> Dict[str, Any]:
    """Get health reports from all available modules."""
    reports = {}
    
    try:
        from scraper.css_selectors import get_selector_manager
        reports["selectors"] = get_selector_manager().get_health_report()
    except Exception as e:
        reports["selectors"] = {"error": str(e)}
    
    try:
        from scraper.keyword_strategy import get_keyword_strategy
        reports["keywords"] = get_keyword_strategy().get_stats_report()
    except Exception as e:
        reports["keywords"] = {"error": str(e)}
    
    try:
        from scraper.progressive_mode import get_progressive_mode_manager
        reports["progressive_mode"] = get_progressive_mode_manager().get_status()
    except Exception as e:
        reports["progressive_mode"] = {"error": str(e)}
    
    try:
        from filters.unified import get_filter_config
        reports["filters"] = get_filter_config().get_stats()
    except Exception as e:
        reports["filters"] = {"error": str(e)}
    
    try:
        from scraper.post_cache import get_post_cache
        reports["cache"] = get_post_cache().get_stats()
    except Exception as e:
        reports["cache"] = {"error": str(e)}
    
    try:
        from scraper.smart_scheduler import get_smart_scheduler
        reports["scheduler"] = get_smart_scheduler().get_status()
    except Exception as e:
        reports["scheduler"] = {"error": str(e)}
    
    try:
        from scraper.ml_interface import get_ml_interface
        reports["ml"] = get_ml_interface().get_status()
    except Exception as e:
        reports["ml"] = {"error": str(e)}
    
    return reports


# =============================================================================
# FEATURE FLAGS FOR GRADUAL ROLLOUT
# =============================================================================

class FeatureFlags:
    """Feature flags for gradual module activation."""
    
    # Enable/disable new modules
    USE_DYNAMIC_SELECTORS = True
    USE_KEYWORD_STRATEGY = True
    USE_PROGRESSIVE_MODE = True
    USE_UNIFIED_FILTERS = True
    USE_METADATA_EXTRACTOR = True
    USE_POST_CACHE = True
    USE_SMART_SCHEDULER = True
    USE_ML_INTERFACE = False  # Disabled by default until trained model available
    
    @classmethod
    def get_all(cls) -> Dict[str, bool]:
        return {
            "dynamic_selectors": cls.USE_DYNAMIC_SELECTORS,
            "keyword_strategy": cls.USE_KEYWORD_STRATEGY,
            "progressive_mode": cls.USE_PROGRESSIVE_MODE,
            "unified_filters": cls.USE_UNIFIED_FILTERS,
            "metadata_extractor": cls.USE_METADATA_EXTRACTOR,
            "post_cache": cls.USE_POST_CACHE,
            "smart_scheduler": cls.USE_SMART_SCHEDULER,
            "ml_interface": cls.USE_ML_INTERFACE,
        }


# =============================================================================
# MIGRATION HELPERS
# =============================================================================

def migrate_keyword_stats_to_strategy(old_stats: Dict[str, Dict]) -> None:
    """Migrate old keyword statistics to new KeywordStrategy format.
    
    Args:
        old_stats: Dict with format {keyword: {"searches": N, "found": M}}
    """
    try:
        from scraper.keyword_strategy import get_keyword_strategy
        
        strategy = get_keyword_strategy()
        
        for keyword, stats in old_stats.items():
            searches = stats.get("searches", 0)
            found = stats.get("found", 0)
            
            # Simulate historical results
            for _ in range(searches):
                success = found > 0
                strategy.record_result(
                    keyword=keyword,
                    found_posts=success,
                    post_count=1 if success else 0,
                    relevant_count=1 if success else 0,
                )
        
        print(f"Migrated {len(old_stats)} keywords to new strategy")
        
    except Exception as e:
        print(f"Migration failed: {e}")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "INTEGRATION_GUIDE",
    "get_integration_status",
    "get_all_health_reports",
    "FeatureFlags",
    "migrate_keyword_stats_to_strategy",
]
