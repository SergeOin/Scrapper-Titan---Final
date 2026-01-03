"""Timing utilities for human-like delays.

This module consolidates all delay/timing logic previously duplicated
between worker.py and scrape_subprocess.py.

Usage:
    from scraper.timing import random_delay, human_delay, get_keyword_delay
    
Author: Titan Scraper Team (Q1 2025 - Debt reduction)
"""
from __future__ import annotations

import os
import random
from typing import Tuple


# =============================================================================
# SAFE MODE CONFIGURATION
# =============================================================================

def is_ultra_safe_mode() -> bool:
    """Check if ultra-safe mode is enabled (maximum stealth).
    
    When TITAN_ULTRA_SAFE_MODE=1, all delays are multiplied by 3x
    for maximum account protection. This is the DEFAULT mode.
    """
    # ACTIVÉ PAR DÉFAUT pour protéger le compte
    return os.environ.get("TITAN_ULTRA_SAFE_MODE", "1") == "1"


def is_safe_mode() -> bool:
    """Check if safe/prudent mode is enabled.
    
    When TITAN_SAFE_MODE=1, all delays are multiplied by 2x
    and long pauses are more frequent.
    """
    return os.environ.get("TITAN_SAFE_MODE", "0") == "1"


def get_delay_multiplier() -> float:
    """Get delay multiplier (3x ultra-safe, 2x safe, 1x normal)."""
    if is_ultra_safe_mode():
        return 3.0  # Mode ultra-prudent par défaut
    elif is_safe_mode():
        return 2.0
    return 1.0


# =============================================================================
# DELAY CONFIGURATION (milliseconds) - MODE ULTRA-PRUDENT
# =============================================================================

# Page load delays - TRÈS CONSERVATEUR pour éviter détection
_PAGE_LOAD_DELAY_MIN = 15000   # 15 seconds minimum (humain réaliste)
_PAGE_LOAD_DELAY_MAX = 40000   # 40 seconds maximum (humain réaliste)

# Scroll delays - LENT comme un humain qui lit vraiment
_SCROLL_DELAY_MIN = 6000    # 6 seconds minimum
_SCROLL_DELAY_MAX = 15000   # 15 seconds maximum

# Keyword search delays - TRÈS ESPACÉ pour éviter patterns
_KEYWORD_DELAY_MIN = 480000   # 8 minutes minimum
_KEYWORD_DELAY_MAX = 900000   # 15 minutes maximum

# Simulated post reading delay - LECTURE APPROFONDIE
_POST_READ_DELAY_MIN = 8000   # 8 seconds minimum (lecture réaliste)
_POST_READ_DELAY_MAX = 20000  # 20 seconds maximum (lecture réaliste)

# Long pause for simulated distraction - PAUSES FRÉQUENTES
_LONG_PAUSE_MIN = 120000      # 2 minutes
_LONG_PAUSE_MAX = 420000      # 7 minutes
_LONG_PAUSE_PROBABILITY = 0.35  # 35% chance per keyword (naturel)

# Micro hesitation pauses - HÉSITATIONS HUMAINES
_MICRO_PAUSE_MIN = 500
_MICRO_PAUSE_MAX = 2000

# Max scrolls per page - MINIMAL pour éviter détection
MAX_SCROLLS_PER_PAGE = 1  # UN SEUL scroll par page

# Coffee break probability per scraping session - FRÉQUENT
COFFEE_BREAK_PROBABILITY = 0.15  # 15% chance per keyword (naturel)


# =============================================================================
# DELAY GETTERS (with multiplier applied)
# =============================================================================

def get_page_load_delay() -> Tuple[int, int]:
    """Get page load delay range (min, max) in ms."""
    m = get_delay_multiplier()
    return int(_PAGE_LOAD_DELAY_MIN * m), int(_PAGE_LOAD_DELAY_MAX * m)


def get_scroll_delay() -> Tuple[int, int]:
    """Get scroll delay range (min, max) in ms."""
    m = get_delay_multiplier()
    return int(_SCROLL_DELAY_MIN * m), int(_SCROLL_DELAY_MAX * m)


def get_keyword_delay() -> Tuple[int, int]:
    """Get keyword search delay range (min, max) in ms."""
    m = get_delay_multiplier()
    return int(_KEYWORD_DELAY_MIN * m), int(_KEYWORD_DELAY_MAX * m)


def get_post_read_delay() -> Tuple[int, int]:
    """Get post reading delay range (min, max) in ms."""
    m = get_delay_multiplier()
    return int(_POST_READ_DELAY_MIN * m), int(_POST_READ_DELAY_MAX * m)


def get_long_pause() -> Tuple[int, int, float]:
    """Get long pause params (min, max, probability)."""
    m = get_delay_multiplier()
    prob = _LONG_PAUSE_PROBABILITY * m  # More frequent in safe mode
    return int(_LONG_PAUSE_MIN * m), int(_LONG_PAUSE_MAX * m), min(prob, 0.4)


def get_micro_pause() -> Tuple[int, int]:
    """Get micro pause range (min, max) in ms."""
    m = get_delay_multiplier()
    return int(_MICRO_PAUSE_MIN * m), int(_MICRO_PAUSE_MAX * m)


# =============================================================================
# DELAY GENERATORS
# =============================================================================

def random_delay(min_ms: int, max_ms: int) -> int:
    """Generate a random delay with Gaussian distribution.
    
    Uses a truncated normal distribution for more natural timing
    (humans tend to cluster around a mean).
    
    ULTRA_SAFE MODE: Applies 3x multiplier to all delays for maximum protection.
    
    Args:
        min_ms: Minimum delay in milliseconds
        max_ms: Maximum delay in milliseconds
        
    Returns:
        Delay in milliseconds (multiplied by safety factor)
    """
    # Apply safety multiplier
    multiplier = get_delay_multiplier()
    min_ms = int(min_ms * multiplier)
    max_ms = int(max_ms * multiplier)
    
    # Gaussian distribution centered on mean
    mean = (min_ms + max_ms) / 2
    std_dev = (max_ms - min_ms) / 4  # 95% of values within range
    
    value = random.gauss(mean, std_dev)
    # Truncate to limits + add some noise
    noise = random.randint(-200, 200)
    return max(min_ms, min(max_ms, int(value + noise)))


def human_delay(base_ms: int, variance_percent: float = 0.4) -> int:
    """Generate a human-like delay with natural variance.
    
    ULTRA_SAFE MODE: Applies 3x multiplier to all delays for maximum protection.
    
    Args:
        base_ms: Base delay in milliseconds
        variance_percent: Variance percentage (0.4 = ±40%)
        
    Returns:
        Delay in milliseconds (multiplied by safety factor)
    """
    # Apply safety multiplier
    multiplier = get_delay_multiplier()
    base_ms = int(base_ms * multiplier)
    
    variance = base_ms * variance_percent
    return int(base_ms + random.uniform(-variance, variance))


def should_take_long_pause() -> bool:
    """Determine if a long pause should be taken (distraction simulation)."""
    _, _, probability = get_long_pause()
    return random.random() < probability


def get_long_pause_duration() -> int:
    """Get a random long pause duration in ms."""
    min_ms, max_ms, _ = get_long_pause()
    return random_delay(min_ms, max_ms)


def should_take_coffee_break() -> bool:
    """Determine if a coffee break should be taken."""
    return random.random() < COFFEE_BREAK_PROBABILITY


# =============================================================================
# LEGACY COMPATIBILITY (for existing code imports)
# =============================================================================

# These are kept for backward compatibility with direct imports
PAGE_LOAD_DELAY_MIN = _PAGE_LOAD_DELAY_MIN
PAGE_LOAD_DELAY_MAX = _PAGE_LOAD_DELAY_MAX
SCROLL_DELAY_MIN = _SCROLL_DELAY_MIN
SCROLL_DELAY_MAX = _SCROLL_DELAY_MAX
KEYWORD_DELAY_MIN = _KEYWORD_DELAY_MIN
KEYWORD_DELAY_MAX = _KEYWORD_DELAY_MAX
POST_READ_DELAY_MIN = _POST_READ_DELAY_MIN
POST_READ_DELAY_MAX = _POST_READ_DELAY_MAX
LONG_PAUSE_MIN = _LONG_PAUSE_MIN
LONG_PAUSE_MAX = _LONG_PAUSE_MAX
LONG_PAUSE_PROBABILITY = _LONG_PAUSE_PROBABILITY
MICRO_PAUSE_MIN = _MICRO_PAUSE_MIN
MICRO_PAUSE_MAX = _MICRO_PAUSE_MAX
