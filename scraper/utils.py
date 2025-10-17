"""Utility functions for the LinkedIn scraping subsystem.

This module groups stateless helpers used by the worker:
- Random User-Agent generation (realistic desktop browsers)
- Jitter sleep (respect rate limiting heuristics)
- Language detection (graceful fallback)
- Text normalization & keyword density
- Scoring heuristic (combines several signals)
- Stable post identifier hashing
- Retry decorator wrapping Tenacity with standard config
- Lightweight date parsing (LinkedIn relative date patterns may later be mapped)

All functions are pure (no side effects) except for those doing async sleeps or
logging. They accept primitives / simple structures for easier testing.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import random
import re
import time
from datetime import datetime, timedelta, timezone
import unicodedata
from typing import Iterable, Callable, Awaitable, Any, Optional

try:
    from user_agents import parse as parse_ua  # type: ignore
except Exception:  # pragma: no cover
    def parse_ua(_ua: str):  # type: ignore
        """Fallback parser noop if user_agents not installed.

        Returns a minimal object with attributes referenced nowhere else; keeps interface harmless.
        """
        class _Dummy:  # noqa: D401
            browser = device = os = None
        return _Dummy()
try:
    from langdetect import detect  # type: ignore
except Exception:  # pragma: no cover
    detect = None  # type: ignore

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

# Local import kept light to avoid circular imports (only for Settings type hints)
try:  # pragma: no cover - type checking friendly
    from .bootstrap import Settings  # noqa: F401
except Exception:  # pragma: no cover
    Settings = Any  # type: ignore

# ---------------------------------------------------------------------------
# User-Agent generation
# ---------------------------------------------------------------------------
_DESKTOP_UA_TEMPLATES = [
    # Chrome (Win / Mac / Linux) variants
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{build}.100 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{safari_major}.1 Safari/605.1.15 Chrome/{major}.0.{build}.100",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{build}.120 Safari/537.36",
]


def random_user_agent(seed: Optional[int] = None) -> str:
    """Return a pseudo-realistic desktop User-Agent string.

    Args:
        seed: Optional seed for deterministic output in tests.
    """
    rnd = random.Random(seed)
    template = rnd.choice(_DESKTOP_UA_TEMPLATES)
    major = rnd.randint(115, 125)
    build = rnd.randint(4000, 5900)
    safari_major = rnd.randint(16, 18)
    ua = template.format(major=major, build=build, safari_major=safari_major)
    # Quick validation (parse; not used but ensures plausible structure)
    try:
        parse_ua(ua)
    except Exception:  # pragma: no cover - parse should not fail
        pass
    return ua


# ---------------------------------------------------------------------------
# Sleep with jitter
# ---------------------------------------------------------------------------
async def jitter_sleep(min_ms: int, max_ms: int) -> float:
    """Async sleep for a random duration between bounds.

    Returns actual seconds slept (float) to allow instrumentation.
    """
    if max_ms < min_ms:
        max_ms = min_ms
    duration_ms = random.randint(min_ms, max_ms)
    seconds = duration_ms / 1000.0
    await asyncio.sleep(seconds)
    return seconds


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------
_LANG_REGEXP = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def detect_language(text: str, default: str = "fr") -> str:
    """Detect language of the text with graceful fallback.

    - If langdetect not available or detection fails, returns default
    - If text too short / empty, returns default
    """
    cleaned = " ".join(_LANG_REGEXP.findall(text))
    if not cleaned or len(cleaned) < 4:
        return default
    if detect is None:  # library missing
        return default
    try:
        lang = detect(cleaned)
        if len(lang) == 2:
            return lang
    except Exception:  # pragma: no cover - depends on library behavior
        return default
    return default


# ---------------------------------------------------------------------------
# Text normalization & keyword density
# ---------------------------------------------------------------------------
_WS_RE = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def keyword_density(text: str, keywords: Iterable[str]) -> float:
    """Compute a naive keyword density (0..1)."""
    text_lc = text.lower()
    total_hits = 0
    total_len = max(len(text_lc), 1)
    for kw in keywords:
        kw = kw.strip().lower()
        if not kw:
            continue
        total_hits += text_lc.count(kw)
    # scale by log to reduce huge bias for repeated words
    score = min(1.0, math.log1p(total_hits) / math.log1p(total_len / 15))
    return max(0.0, score)


# ---------------------------------------------------------------------------
# Scoring heuristic
# ---------------------------------------------------------------------------

def compute_score(
    *,
    text: str,
    language: str,
    expected_lang: str,
    has_media: bool,
    keywords: list[str],
    settings,
) -> float:
    """Compute a relevance score combining several weighted factors.

    Formula (simplified):
        length_norm * W_length + media * W_media + kw_density * W_kw + lang_match * W_lang
    Clamped into [0, 1].
    """
    length_norm = min(1.0, len(text) / 800)  # saturates at ~800 chars
    lang_match = 1.0 if language == expected_lang else 0.0
    kw_density = keyword_density(text, keywords)
    media_val = 1.0 if has_media else 0.0

    raw = (
        length_norm * settings.weight_length
        + media_val * settings.weight_media
        + kw_density * settings.weight_keyword_density
        + lang_match * settings.weight_lang_match
    )
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Stable post identifier
# ---------------------------------------------------------------------------

def make_post_id(*parts: str) -> str:
    """Return a deterministic hash ID from provided parts.

    Any None/empty parts are ignored; uses SHA256 truncated to 16 hex chars.
    """
    filtered = [p for p in parts if p]
    blob = "||".join(filtered).encode("utf-8", errors="ignore")
    return hashlib.sha256(blob).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Retry helper (wrapping Tenacity)
# ---------------------------------------------------------------------------
class TransientScrapeError(Exception):
    """An error type that indicates a retryable transient failure."""


def retryable(*exc_types: type[BaseException]):
    """Decorator factory for retry logic with exponential backoff + jitter.

    Example:
        @retryable(TimeoutError, TransientScrapeError)
        async def fragile(): ...
    """
    if not exc_types:
        exc_types = (Exception,)  # type: ignore

    def _decorator(fn: Callable[..., Awaitable[Any]]):
        return retry(
            reraise=True,
            stop=stop_after_attempt(4),
            wait=wait_exponential_jitter(multiplier=0.4, max=6),
            retry=retry_if_exception_type(exc_types),
        )(fn)

    return _decorator


# ---------------------------------------------------------------------------
# Lightweight date parsing (placeholder)
# ---------------------------------------------------------------------------
_RELATIVE_MAP = {
    # key fragment => minutes
    "1 h": 60,
    "1h": 60,
    "1 j": 1440,
}

_RELATIVE_PATTERN = re.compile(r"(\d+)\s*(s|min|h|j)")


def parse_possible_date(raw: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Very small helper to parse relative LinkedIn-like timestamps.

    Accepts fragments such as:
        '5 min' => now - 5 minutes
        '2 h'   => now - 2 hours
        '1 j'   => now - 1 day

    Returns timezone-aware UTC datetime or None if not parsed.
    This is intentionally conservative; the worker may supply a fallback.
    """
    raw = raw.strip().lower()
    if not raw:
        return None
    now = now or datetime.now(timezone.utc)

    # Match pattern like '5 h', '12 min'
    m = _RELATIVE_PATTERN.search(raw)
    if m:
        value = int(m.group(1))
        unit = m.group(2)
        delta: timedelta
        if unit == "s":
            delta = timedelta(seconds=value)
        elif unit == "min":
            delta = timedelta(minutes=value)
        elif unit == "h":
            delta = timedelta(hours=value)
        elif unit == "j":  # jour
            delta = timedelta(days=value)
        else:  # pragma: no cover
            return None
        return now - delta

    # Accept some explicit forms stored in mapping
    for frag, minutes in _RELATIVE_MAP.items():
        if frag in raw:
            return now - timedelta(minutes=minutes)

    # Could extend to full absolute date parse with dateutil if necessary.
    return None


# ---------------------------------------------------------------------------
# Utility for timing blocks (context manager)
# ---------------------------------------------------------------------------
class Timer:
    """Simple async-compatible timer context for performance metrics."""

    def __init__(self) -> None:
        self._start: float | None = None
        self.elapsed: float | None = None

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info):
        if self._start is not None:
            self.elapsed = time.perf_counter() - self._start
        return False


__all__ = [
    "random_user_agent",
    "jitter_sleep",
    "detect_language",
    "normalize_whitespace",
    "normalize_for_search",
    "build_search_norm",
    "keyword_density",
    "compute_score",
    "compute_recruitment_signal",
    "is_opportunity",
    "make_post_id",
    "retryable",
    "TransientScrapeError",
    "parse_possible_date",
    "Timer",
]

# ---------------------------------------------------------------------------
# Recruitment signal scoring (heuristic): counts stems & phrases indicating hiring.
# ---------------------------------------------------------------------------
_RECRUIT_TOKENS = [
    "recrut",  # recrutement / recrute / recrutons
    "offre",
    "poste",
    "opportunité",
    "opportunite",
    "hiring",
    "job",
    "nous cherchons",
    "on recherche",
    "rejoignez",
    "join the team",
    "join our team",
    "embauche",
    "cdi",
    "cdd",
    "alternance",
    "stage",
    "stagiaire",
    "mission",
    "nous recherchons",
    "je recrute",
    "je recherche",
]
_MULTI_TOKEN_PRIORITY = {"nous recherchons": 2.2, "je recrute": 2.0, "je recherche": 1.6}


def compute_recruitment_signal(text: str) -> float:
    """Return a heuristic recruitment intent score in ~[0,1]."""
    if not text:
        return 0.0
    low = text.lower()
    raw = 0.0
    for tok in _RECRUIT_TOKENS:
        cnt = low.count(tok)
        if cnt:
            raw += cnt * _MULTI_TOKEN_PRIORITY.get(tok, 1.0)
    norm = raw / (len(low) / 60.0 + 1.0)
    score = min(1.0, math.log1p(norm) / math.log1p(10))
    return max(0.0, score)


def is_opportunity(text: str | None, *, threshold: float = 0.05) -> bool:
    """Unified opportunity / recruitment signal predicate.

    A post is considered an "opportunity" if its recruitment signal score
    (compute_recruitment_signal) is above the configured threshold OR it contains
    high-salience imperative phrases frequently used in hiring posts.

    Centralising this logic prevents divergence between auto-favorite, UI badges
    and API summarisation.
    """
    if not text:
        return False
    score = compute_recruitment_signal(text)
    if score >= threshold:
        return True
    low = text.lower()
    phrase_hits = [
        # existants
        "nous recrutons", "on recrute", "je recrute", "recrutement en cours",
        "poste a pourvoir", "poste à pourvoir", "apply now", "we are hiring",
        "we're hiring", "join our team", "envoyez votre cv", "postulez",
        # nouveaux
        "hiring", "on recherche un juriste", "nous cherchons", "join the team",
        "rejoignez la direction juridique",
    ]
    return any(p in low for p in phrase_hits)


# ---------------------------------------------------------------------------
# Normalization helpers for accent-insensitive search
# ---------------------------------------------------------------------------
def normalize_for_search(s: str | None) -> str:
    """Lowercase and strip accents/diacritics for accent-insensitive search.

    Returns an ASCII-ish string (but keeps non-letter chars except diacritics).
    """
    if not s:
        return ""
    s = s.lower().strip()
    # NFD decomposition, drop non-spacing marks (Mn)
    nfd = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn").strip()


def build_search_norm(*parts: str | None) -> str:
    """Build a normalized search blob from multiple fields (text, author, company, keyword).

    Joins normalized parts with spaces and trims size to a safe length.
    """
    normed = [normalize_for_search(p) for p in parts if p]
    blob = " ".join(filter(None, normed))
    # clamp to avoid extreme size
    return blob[:4000]
