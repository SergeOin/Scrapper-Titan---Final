"""Content Loader - Robust dynamic content handling for LinkedIn.

This module provides utilities for waiting for dynamically loaded content,
with intelligent retry logic and network activity monitoring.

LinkedIn heavily uses lazy loading and dynamic content injection.
Standard Playwright wait_for_selector often fails because:
1. Selectors change frequently
2. Content loads in stages
3. Network requests complete but DOM isn't updated yet

This module provides:
- wait_for_content_stable: Wait until DOM stops changing
- wait_for_network_idle: Wait for all pending requests
- smart_wait_for_posts: Combined waiting strategy for post containers
- retry_extraction: Retry extraction with exponential backoff

Author: Titan Scraper Team
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, Optional, TypeVar, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

T = TypeVar('T')


# =============================================================================
# NETWORK IDLE DETECTION
# =============================================================================

async def wait_for_network_idle(
    page,
    timeout_ms: int = 10000,
    idle_time_ms: int = 500,
    max_inflight: int = 2
) -> bool:
    """Wait until network activity settles.
    
    LinkedIn makes many API calls after page load. This waits until
    the number of in-flight requests drops below threshold.
    
    Args:
        page: Playwright page instance
        timeout_ms: Maximum time to wait
        idle_time_ms: How long network must be idle
        max_inflight: Maximum allowed in-flight requests to consider "idle"
        
    Returns:
        bool: True if network became idle, False if timeout
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        return True
    except Exception:
        # Fallback: just wait a bit for content to settle
        await page.wait_for_timeout(min(idle_time_ms * 2, 2000))
        return False


# =============================================================================
# DOM STABILITY DETECTION
# =============================================================================

async def wait_for_content_stable(
    page,
    selector: str,
    timeout_ms: int = 10000,
    stability_ms: int = 1000,
    min_elements: int = 1
) -> int:
    """Wait until content matching selector stops changing.
    
    This handles the common LinkedIn pattern where content loads
    progressively - the selector matches but more content is still coming.
    
    Args:
        page: Playwright page instance
        selector: CSS selector to monitor
        timeout_ms: Maximum time to wait
        stability_ms: Content must be stable for this duration
        min_elements: Minimum elements required
        
    Returns:
        int: Number of matching elements, or 0 if timeout
    """
    start = datetime.now(timezone.utc)
    last_count = 0
    stable_since: Optional[datetime] = None
    
    while True:
        elapsed = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        if elapsed > timeout_ms:
            logger.debug(f"content_stable_timeout selector={selector} last_count={last_count}")
            return last_count
        
        try:
            elements = await page.query_selector_all(selector)
            current_count = len(elements)
            
            if current_count != last_count:
                # Content changed, reset stability timer
                last_count = current_count
                stable_since = datetime.now(timezone.utc)
            elif current_count >= min_elements and stable_since:
                # Check if stable for long enough
                stable_duration = (datetime.now(timezone.utc) - stable_since).total_seconds() * 1000
                if stable_duration >= stability_ms:
                    logger.debug(f"content_stable selector={selector} count={current_count}")
                    return current_count
            elif current_count >= min_elements and stable_since is None:
                stable_since = datetime.now(timezone.utc)
                
        except Exception as e:
            logger.debug(f"content_stable_error selector={selector} error={e}")
        
        await page.wait_for_timeout(200)


# =============================================================================
# SMART POST WAITING
# =============================================================================

# Multiple selectors to try in order of reliability
POST_SELECTORS_PRIORITY = [
    "article[data-urn*='urn:li:activity']",
    "div[data-urn*='urn:li:activity:']",
    "div.feed-shared-update-v2",
    "div.update-components-feed-update",
    "div.occludable-update",
]


async def smart_wait_for_posts(
    page,
    min_posts: int = 1,
    timeout_ms: int = 15000,
    max_retries: int = 3
) -> tuple[str, List[Any]]:
    """Intelligently wait for post elements to load.
    
    Tries multiple strategies:
    1. Wait for network idle
    2. Try each selector in priority order
    3. Wait for content stability
    4. Retry with scroll if needed
    
    Args:
        page: Playwright page instance
        min_posts: Minimum posts required
        timeout_ms: Timeout per attempt
        max_retries: Number of retry attempts
        
    Returns:
        tuple: (winning_selector, list_of_elements)
    """
    for attempt in range(max_retries):
        if attempt > 0:
            logger.info(f"smart_wait_retry attempt={attempt + 1}")
            # Light scroll to trigger lazy loading
            try:
                await page.evaluate("window.scrollBy(0, 300)")
                await page.wait_for_timeout(1000)
            except Exception:
                pass
        
        # First wait for network to settle
        await wait_for_network_idle(page, timeout_ms=5000)
        
        # Try each selector
        for selector in POST_SELECTORS_PRIORITY:
            try:
                count = await wait_for_content_stable(
                    page, 
                    selector, 
                    timeout_ms=timeout_ms // max_retries,
                    stability_ms=800,
                    min_elements=min_posts
                )
                
                if count >= min_posts:
                    elements = await page.query_selector_all(selector)
                    logger.info(f"smart_wait_success selector={selector} count={len(elements)}")
                    return selector, elements
                    
            except Exception as e:
                logger.debug(f"smart_wait_selector_failed selector={selector} error={e}")
                continue
    
    # Fallback: return whatever we can find
    for selector in POST_SELECTORS_PRIORITY:
        try:
            elements = await page.query_selector_all(selector)
            if elements:
                logger.warning(f"smart_wait_fallback selector={selector} count={len(elements)}")
                return selector, elements
        except Exception:
            continue
    
    logger.warning("smart_wait_no_posts_found")
    return "", []


# =============================================================================
# EXTRACTION WITH RETRY
# =============================================================================

async def retry_extraction(
    extract_fn: Callable[..., T],
    *args,
    max_retries: int = 3,
    base_delay_ms: int = 500,
    max_delay_ms: int = 5000,
    jitter: bool = True,
    **kwargs
) -> Optional[T]:
    """Retry an extraction function with exponential backoff.
    
    Args:
        extract_fn: Async function to call
        *args: Positional arguments for function
        max_retries: Maximum retry attempts
        base_delay_ms: Initial delay between retries
        max_delay_ms: Maximum delay between retries
        jitter: Add random jitter to delays
        **kwargs: Keyword arguments for function
        
    Returns:
        Result of extract_fn, or None if all retries fail
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if asyncio.iscoroutinefunction(extract_fn):
                result = await extract_fn(*args, **kwargs)
            else:
                result = extract_fn(*args, **kwargs)
            
            if result is not None:
                return result
                
        except asyncio.CancelledError:
            raise
        except Exception as e:
            last_error = e
            logger.debug(f"retry_extraction_attempt={attempt + 1} error={e}")
        
        if attempt < max_retries - 1:
            # Exponential backoff
            delay = min(base_delay_ms * (2 ** attempt), max_delay_ms)
            if jitter:
                delay = int(delay * (0.5 + random.random()))
            await asyncio.sleep(delay / 1000)
    
    if last_error:
        logger.warning(f"retry_extraction_exhausted error={last_error}")
    return None


# =============================================================================
# ELEMENT EXISTENCE VERIFICATION
# =============================================================================

async def safe_element_text(
    element,
    default: str = "",
    strip: bool = True
) -> str:
    """Safely extract text from an element with error handling.
    
    Args:
        element: Playwright element
        default: Default value if extraction fails
        strip: Whether to strip whitespace
        
    Returns:
        str: Element text or default
    """
    if element is None:
        return default
    
    try:
        text = await element.inner_text()
        if text and strip:
            text = text.strip()
        return text if text else default
    except Exception:
        return default


async def safe_element_attribute(
    element,
    attr: str,
    default: Optional[str] = None
) -> Optional[str]:
    """Safely get an attribute from an element.
    
    Args:
        element: Playwright element
        attr: Attribute name
        default: Default value if not found
        
    Returns:
        Attribute value or default
    """
    if element is None:
        return default
    
    try:
        value = await element.get_attribute(attr)
        return value if value else default
    except Exception:
        return default


async def element_visible(element) -> bool:
    """Check if element is visible on page.
    
    Args:
        element: Playwright element
        
    Returns:
        bool: True if visible
    """
    if element is None:
        return False
    
    try:
        return await element.is_visible()
    except Exception:
        return False


# =============================================================================
# LAZY LOAD TRIGGER
# =============================================================================

async def trigger_lazy_load(
    page,
    scroll_count: int = 3,
    scroll_delay_ms: int = 1000,
    scroll_amount: int = 400
) -> None:
    """Trigger lazy loading by scrolling.
    
    LinkedIn loads more content as user scrolls. This simulates
    natural scrolling to trigger content loading.
    
    Args:
        page: Playwright page instance
        scroll_count: Number of scroll steps
        scroll_delay_ms: Delay between scrolls
        scroll_amount: Pixels per scroll
    """
    try:
        for i in range(scroll_count):
            # Scroll down
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await page.wait_for_timeout(scroll_delay_ms)
            
            # Small random horizontal movement (human-like)
            jitter = random.randint(-20, 20)
            await page.mouse.wheel(jitter, 0)
            
    except Exception as e:
        logger.debug(f"trigger_lazy_load_error: {e}")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "wait_for_network_idle",
    "wait_for_content_stable", 
    "smart_wait_for_posts",
    "retry_extraction",
    "safe_element_text",
    "safe_element_attribute",
    "element_visible",
    "trigger_lazy_load",
    "POST_SELECTORS_PRIORITY",
]
