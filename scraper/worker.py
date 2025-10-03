"""Scraper worker process.

Responsibilities:
- Consume scrape jobs (keywords) from Redis queue (simple list semantics)
- For each keyword, launch Playwright page, perform search, extract posts
- Apply retries + jitter sleeps; screenshot on fatal failure
- Store results in MongoDB (primary) with fallback to SQLite then CSV
- Update meta info (last_run, counts) and expose Prometheus metrics increments
- Respect global SCRAPING_ENABLED flag and file lock to prevent concurrent runs

Simplifications / Notes:
- Selectors are placeholders (subject to LinkedIn DOM changes).
- A more robust implementation would rely on official APIs or data partnerships.
- Use ethically & internally only; respect LinkedIn terms.

Queue contract (Redis list): pushing keywords set as a single job payload JSON:
{"keywords": ["python", "ai"]}
If no queue: iterate over settings.keywords once (manual run mode).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import re as _re  # local lightweight regex (avoid repeated imports)
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, TYPE_CHECKING

import structlog
from filelock import FileLock, Timeout
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

from .bootstrap import (
    AppContext,
    SCRAPE_DURATION_SECONDS,
    SCRAPE_JOBS_TOTAL,
    SCRAPE_POSTS_EXTRACTED,
    SCRAPE_MOCK_POSTS_EXTRACTED,
    SCRAPE_STORAGE_ATTEMPTS,
    SCRAPE_QUEUE_DEPTH,
    SCRAPE_JOB_FAILURES,
    SCRAPE_STEP_DURATION,
    SCRAPE_RATE_LIMIT_TOKENS,
    SCRAPE_SCROLL_ITERATIONS,
    SCRAPE_EXTRACTION_INCOMPLETE,
    SCRAPE_RECRUITMENT_POSTS,
    SCRAPE_FILTERED_POSTS,
    LEGAL_POSTS_TOTAL,
    LEGAL_POSTS_DISCARDED_TOTAL,
    LEGAL_INTENT_CLASSIFICATIONS_TOTAL,
    LEGAL_DAILY_CAP_REACHED,
    get_context,
)
from . import utils
from .legal_classifier import classify_legal_post, LEGAL_ROLE_KEYWORDS

if TYPE_CHECKING:
    from .bootstrap import Settings
try:
    from server.events import broadcast, EventType  # type: ignore
except Exception:  # pragma: no cover
    broadcast = None  # type: ignore
    EventType = None  # type: ignore

try:  # Optional heavy import lazy usage
    from playwright.async_api import async_playwright, Page, Browser
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore
    Page = Any  # type: ignore
    Browser = Any  # type: ignore

# ------------------------------------------------------------
# Authentication helpers (single session use)
# ------------------------------------------------------------
async def _has_li_at_cookie(page: Any) -> bool:
    """Return True if Playwright context currently has a non-empty 'li_at' cookie."""
    try:
        cookies = await page.context.cookies("https://www.linkedin.com")
        for c in cookies:
            if c.get("name") == "li_at" and c.get("value"):
                return True
        return False
    except Exception:
        return False

async def _ensure_authenticated(page: Any, ctx: AppContext, logger: structlog.BoundLogger) -> None:
    """Attempt to land on feed and allow manual login if needed.

    Strategy:
      1. Navigate to feed page.
      2. If looks unauthenticated: if configured wait window > 0 and first keyword => sleep allowing manual login.
      3. Re-check; if now authenticated, save storage state back to file to reuse.
    """
    try:
        await page.goto("https://www.linkedin.com/feed/", timeout=ctx.settings.navigation_timeout_ms)
    except Exception as exc:
        logger.warning("feed_navigation_failed", error=str(exc))
        return
    # Check cookie-based authentication
    if not await _has_li_at_cookie(page):
        logger.warning("unauthenticated_feed_detected")
        if ctx.settings.login_initial_wait_seconds > 0:
            wait_secs = ctx.settings.login_initial_wait_seconds
            logger.info("manual_login_window", seconds=wait_secs)
            try:
                await asyncio.sleep(wait_secs)
            except Exception:
                pass
    # Re-check after possible wait
    if await _has_li_at_cookie(page):
        # Save storage state (may contain fresh cookies / session)
        try:
            await page.context.storage_state(path=ctx.settings.storage_state)
            logger.info("storage_state_updated", path=ctx.settings.storage_state)
        except Exception as exc:
            logger.warning("storage_state_save_failed", error=str(exc))
    else:
        logger.warning("still_unauthenticated_after_wait")
    # Always attempt a diagnostic screenshot after auth handling (best-effort)
    try:
        shot_path = Path(ctx.settings.screenshot_dir) / "auth_state.png"
        await page.screenshot(path=str(shot_path))
        logger.info("auth_screenshot_captured", path=str(shot_path))
    except Exception:
        pass

async def process_keywords_single_session(keywords: list[str], ctx: AppContext) -> list[Post]:
    if async_playwright is None:
        raise RuntimeError("Playwright not installed.")
    logger = ctx.logger.bind(component="single_session")
    results: list[Post] = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=ctx.settings.playwright_headless_scrape)
            context = await browser.new_context(
                storage_state=ctx.settings.storage_state if os.path.exists(ctx.settings.storage_state) else None
            )
            page = await context.new_page()
            await _ensure_authenticated(page, ctx, logger)
            for idx, keyword in enumerate(keywords):
                if idx > 0 and ctx.settings.per_keyword_delay_ms > 0:
                    await asyncio.sleep(ctx.settings.per_keyword_delay_ms / 1000.0)
                if ctx.token_bucket:
                    await ctx.token_bucket.consume(1)
                    if ctx.token_bucket:
                        SCRAPE_RATE_LIMIT_TOKENS.set(ctx.token_bucket.tokens)
                try:
                    search_url = f"https://www.linkedin.com/search/results/content/?keywords={keyword}"
                    await page.goto(search_url, timeout=ctx.settings.navigation_timeout_ms)
                    await page.wait_for_timeout(1500)
                    posts = await extract_posts(page, keyword, ctx.settings.max_posts_per_keyword, ctx)
                    logger.info("keyword_extracted", keyword=keyword, count=len(posts))
                    results.extend(posts)
                except Exception as exc:
                    logger.warning("keyword_failed", keyword=keyword, error=str(exc))
            try:
                await browser.close()
            except Exception:
                pass
    except NotImplementedError:
        logger.error("playwright_subprocess_unsupported", hint="Relancer sans reload: python scripts/run_server.py")
        try:
            # Switch to mock mode dynamically so autonomous loop can still function
            if hasattr(ctx.settings, "playwright_mock_mode"):
                setattr(ctx.settings, "playwright_mock_mode", True)
            logger.warning("fallback_mock_mode_enabled")
        except Exception:
            pass
        return []
    return results

# ------------------------------------------------------------
# Batched multi-session processing with recovery & adaptive pauses
# ------------------------------------------------------------
async def _attempt_navigation(page: Any, url: str, ctx: AppContext, logger: structlog.BoundLogger) -> bool:
    attempts = 1 + max(0, ctx.settings.navigation_retry_attempts)
    for i in range(attempts):
        try:
            await page.goto(url, timeout=ctx.settings.navigation_timeout_ms)
            return True
        except Exception as exc:
            logger.warning("navigation_failed", url=url, attempt=i+1, error=str(exc))
            if i < attempts - 1:
                await asyncio.sleep(ctx.settings.navigation_retry_backoff_ms / 1000.0)
    return False

async def _recover_browser(pw, ctx: AppContext, logger: structlog.BoundLogger):  # returns (browser, page) or None
    try:
        browser = await pw.chromium.launch(headless=ctx.settings.playwright_headless_scrape)
        # Apply storage_state on context to restore authenticated session
        context = await browser.new_context(
            storage_state=ctx.settings.storage_state if os.path.exists(ctx.settings.storage_state) else None
        )
        page = await context.new_page()
        await _ensure_authenticated(page, ctx, logger)
        return browser, page
    except Exception as exc:
        logger.error("browser_recovery_failed", error=str(exc))
        return None

async def process_keywords_batched(all_keywords: list[str], ctx: AppContext) -> list[Post]:
    if async_playwright is None:
        raise RuntimeError("Playwright not installed.")
    logger = ctx.logger.bind(component="batched_session")
    batch_size = max(1, ctx.settings.keywords_session_batch_size)
    results: list[Post] = []
    # Split keywords into batches
    for batch_index in range(0, len(all_keywords), batch_size):
        batch = all_keywords[batch_index: batch_index + batch_size]
        logger.info("batch_start", batch_index=batch_index//batch_size + 1, size=len(batch))
        try:
            async with async_playwright() as pw:
                recovery = await _recover_browser(pw, ctx, logger)
                if recovery is None:
                    logger.warning("skip_batch_recovery_failed", batch=batch)
                    continue
                browser, page = recovery
                try:
                    for idx, keyword in enumerate(batch):
                        if ctx.settings.adaptive_pause_every > 0 and results and (len(results) // ctx.settings.max_posts_per_keyword) % ctx.settings.adaptive_pause_every == 0 and (len(results) // ctx.settings.max_posts_per_keyword) != 0:
                            logger.info("adaptive_pause", seconds=ctx.settings.adaptive_pause_seconds)
                            await asyncio.sleep(ctx.settings.adaptive_pause_seconds)
                        if page.is_closed():
                            logger.warning("page_closed_detected", action="attempt_recovery")
                            rec = await _recover_browser(pw, ctx, logger)
                            if rec is None:
                                logger.error("recovery_failed_abort_keyword", keyword=keyword)
                                break
                            browser, page = rec
                        if ctx.token_bucket:
                            await ctx.token_bucket.consume(1)
                            if ctx.token_bucket:
                                SCRAPE_RATE_LIMIT_TOKENS.set(ctx.token_bucket.tokens)
                        kw = keyword
                        try:
                            if ctx.settings.search_geo_hint:
                                kw = f"{keyword} {ctx.settings.search_geo_hint}".strip()
                        except Exception:
                            pass
                        search_url = f"https://www.linkedin.com/search/results/content/?keywords={kw}"
                        ok = await _attempt_navigation(page, search_url, ctx, logger)
                        if not ok:
                            logger.warning("skip_keyword_navigation_failed", keyword=keyword)
                            continue
                        try:
                            await page.wait_for_timeout(1200)
                            posts = await extract_posts(page, keyword, ctx.settings.max_posts_per_keyword, ctx)
                            logger.info("keyword_extracted", keyword=keyword, count=len(posts))
                            results.extend(posts)
                        except Exception as exc:
                            logger.warning("keyword_processing_failed", keyword=keyword, error=str(exc))
                            try:
                                screenshot_path = Path(ctx.settings.screenshot_dir) / f"error_{keyword.replace(' ','_')}.png"
                                await page.screenshot(path=str(screenshot_path))
                                logger.info("keyword_error_screenshot", path=str(screenshot_path))
                            except Exception:
                                pass
                finally:
                    try:
                        if not page.is_closed():
                            end_shot = Path(ctx.settings.screenshot_dir) / f"batch_{batch_index//batch_size + 1}_end.png"
                            await page.screenshot(path=str(end_shot))
                            logger.info("batch_screenshot", path=str(end_shot))
                    except Exception:
                        pass
                    with contextlib.suppress(Exception):
                        await browser.close()
        except NotImplementedError:
            logger.error("playwright_subprocess_unsupported", hint="Relancer sans reload: python scripts/run_server.py")
            try:
                if hasattr(ctx.settings, "playwright_mock_mode"):
                    setattr(ctx.settings, "playwright_mock_mode", True)
                logger.warning("fallback_mock_mode_enabled")
            except Exception:
                pass
            break
        logger.info("batch_complete", batch=batch)
    return results

# ------------------------------------------------------------
# Data model (lightweight) - could be pydantic models if needed
# ------------------------------------------------------------
@dataclass(slots=True)
class Post:
    id: str
    keyword: str
    author: str
    author_profile: Optional[str]
    text: str
    language: str
    published_at: Optional[str]
    collected_at: str
    company: Optional[str] = None
    permalink: Optional[str] = None
    # Keep score in-memory for tests/metrics, but do not persist to storage
    score: Optional[float] = None
    raw: dict[str, Any] | None = None


# ------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------
class ExtractionError(Exception):
    """Raised when the DOM extraction pattern fails irrecoverably."""


class StorageError(Exception):
    """Raised when all storage backends fail."""


# ------------------------------------------------------------
# Storage Helpers
# ------------------------------------------------------------
async def store_posts(ctx: AppContext, posts: list[Post]) -> None:
    """Store posts using priority: Mongo → SQLite → CSV.

    Each path tries to insert many; duplicates filtered by _id (hash)."""
    if not posts:
        return
    # Retain posts as-is (tests rely on counting inserted rows), previously we filtered mock artifacts here.
    logger = ctx.logger.bind(step="store_posts", count=len(posts))
    # Attempt Mongo
    if ctx.mongo_client:
        try:
            with SCRAPE_STEP_DURATION.labels(step="mongo_insert").time():
                coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
                docs = []
                for p in posts:
                    d = {
                        "_id": p.id,
                        "keyword": p.keyword,
                        "author": p.author,
                        "author_profile": p.author_profile,
                        "company": getattr(p, "company", None),
                        "permalink": getattr(p, "permalink", None),
                        "text": p.text,
                        "language": p.language,
                        "published_at": p.published_at,
                        "collected_at": p.collected_at,
                        # Scores removed from persistence
                        "raw": p.raw or {},
                        # Legal classification enriched fields (optional presence)
                        "intent": getattr(p, "intent", None),
                        "relevance_score": getattr(p, "relevance_score", None),
                        "confidence": getattr(p, "confidence", None),
                        "keywords_matched": getattr(p, "keywords_matched", None),
                        "location_ok": getattr(p, "location_ok", None),
                    }
                    docs.append(d)
                if docs:
                    await coll.insert_many(docs, ordered=False)
                    SCRAPE_STORAGE_ATTEMPTS.labels("mongo", "success").inc()
                    logger.info("mongo_inserted", inserted=len(docs))
                    return
        except Exception as exc:  # pragma: no cover
            SCRAPE_STORAGE_ATTEMPTS.labels("mongo", "error").inc()
            logger.error("mongo_insert_failed", error=str(exc))
    # SQLite fallback
    try:
        with SCRAPE_STEP_DURATION.labels(step="sqlite_insert").time():
            _store_sqlite(ctx.settings, posts)
        SCRAPE_STORAGE_ATTEMPTS.labels("sqlite", "success").inc()
        logger.info("sqlite_inserted", path=ctx.settings.sqlite_path, inserted=len(posts))
        return
    except Exception as exc:  # pragma: no cover
        SCRAPE_STORAGE_ATTEMPTS.labels("sqlite", "error").inc()
        logger.error("sqlite_insert_failed", error=str(exc))
    # CSV fallback
    try:
        with SCRAPE_STEP_DURATION.labels(step="csv_insert").time():
            _store_csv(Path(ctx.settings.csv_fallback_file), posts)
        SCRAPE_STORAGE_ATTEMPTS.labels("csv", "success").inc()
        logger.warning("csv_fallback_used", file=ctx.settings.csv_fallback_file, inserted=len(posts))
        return
    except Exception as exc:  # pragma: no cover
        SCRAPE_STORAGE_ATTEMPTS.labels("csv", "error").inc()
        logger.error("csv_fallback_failed", error=str(exc))
    raise StorageError("All storage backends failed")


def _store_sqlite(settings: "Settings", posts: list[Post]) -> None:
    path = settings.sqlite_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        # Create table (legacy layout first); new classification columns added via ALTER below
        conn.execute(
            """CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            keyword TEXT,
            author TEXT,
            author_profile TEXT,
            company TEXT,
            permalink TEXT,
            text TEXT,
            language TEXT,
            published_at TEXT,
            collected_at TEXT,
            raw_json TEXT,
            search_norm TEXT,
            content_hash TEXT
            )"""
        )
        # Detect legacy columns
        try:
            cur = conn.execute("PRAGMA table_info(posts)")
            cols = [r[1] for r in cur.fetchall()]
            if "score" in cols or "recruitment_score" in cols:
                # Perform lightweight migration: create temp, copy subset, drop old, rename
                conn.execute("CREATE TABLE IF NOT EXISTS posts_new (id TEXT PRIMARY KEY, keyword TEXT, author TEXT, author_profile TEXT, company TEXT, permalink TEXT, text TEXT, language TEXT, published_at TEXT, collected_at TEXT, raw_json TEXT, search_norm TEXT, content_hash TEXT)")
                # Copy only needed columns if they exist
                copy_cols_src = [c for c in ["id","keyword","author","author_profile","company","permalink","text","language","published_at","collected_at","raw_json","search_norm","content_hash"] if c in cols]
                copy_cols_dst = ["id","keyword","author","author_profile","company","permalink","text","language","published_at","collected_at","raw_json","search_norm","content_hash"]
                conn.execute(f"INSERT OR IGNORE INTO posts_new ({','.join(copy_cols_dst)}) SELECT {','.join(copy_cols_src)} FROM posts")
                conn.execute("DROP TABLE posts")
                conn.execute("ALTER TABLE posts_new RENAME TO posts")
            # Add content_hash column if missing (after migration path)
            if "content_hash" not in cols:
                try:
                    conn.execute("ALTER TABLE posts ADD COLUMN content_hash TEXT")
                except Exception:
                    pass
            # Create a unique index on permalink to avoid duplicate rows for the same LinkedIn post
            try:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_posts_permalink ON posts(permalink) WHERE permalink IS NOT NULL")
            except Exception:
                pass
            # Secondary composite unique index for fallback dedup when permalink missing
            try:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_posts_author_published ON posts(author, published_at) WHERE author IS NOT NULL AND published_at IS NOT NULL")
            except Exception:
                pass
            # Tertiary unique index on content_hash when no permalink/date
            try:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_posts_content_hash ON posts(content_hash) WHERE content_hash IS NOT NULL")
            except Exception:
                pass
        except Exception:
            pass
            # Add new classification columns if missing (idempotent)
            for new_col, ddl in [
                ("intent", "ALTER TABLE posts ADD COLUMN intent TEXT"),
                ("relevance_score", "ALTER TABLE posts ADD COLUMN relevance_score REAL"),
                ("confidence", "ALTER TABLE posts ADD COLUMN confidence REAL"),
                ("location_ok", "ALTER TABLE posts ADD COLUMN location_ok INTEGER"),
                ("keywords_matched", "ALTER TABLE posts ADD COLUMN keywords_matched TEXT"),
            ]:
                if new_col not in cols:
                    try:
                        conn.execute(ddl)
                        cols.append(new_col)
                    except Exception:
                        pass
        except Exception:
            cols = []  # pragma: no cover
        rows: list[tuple] = []
        seen_hashes = set()
        for p in posts:
            try:
                s_norm = utils.build_search_norm(p.text, p.author, getattr(p, 'company', None), p.keyword)
            except Exception:
                s_norm = None
            try:
                chash = _compute_content_hash(p.author, p.text)
            except Exception:
                chash = None
            # Ensure batch-level uniqueness to avoid INSERT OR IGNORE skipping later rows when same text/author
            if chash and chash in seen_hashes:
                chash = f"{chash}_{abs(hash(p.id))%997}"  # deterministic short salt
            if chash:
                seen_hashes.add(chash)
            # Extend raw JSON with legal classification fields for SQLite/CSV schemas
            raw_enriched = dict(p.raw or {})
            if getattr(p, 'intent', None):
                raw_enriched.setdefault('intent', p.intent)
            if getattr(p, 'relevance_score', None) is not None:
                raw_enriched.setdefault('relevance_score', p.relevance_score)
            if getattr(p, 'confidence', None) is not None:
                raw_enriched.setdefault('confidence', p.confidence)
            if getattr(p, 'keywords_matched', None):
                raw_enriched.setdefault('keywords_matched', p.keywords_matched)
            if getattr(p, 'location_ok', None) is not None:
                raw_enriched.setdefault('location_ok', p.location_ok)
            # Prepare dynamic column insertion: ensure backward compatibility (works even if new columns absent)
            base_values = {
                "id": p.id,
                "keyword": p.keyword,
                "author": p.author,
                "author_profile": p.author_profile,
                "company": getattr(p, 'company', None),
                "permalink": getattr(p, 'permalink', None),
                "text": p.text,
                "language": p.language,
                "published_at": p.published_at,
                "collected_at": p.collected_at,
                "raw_json": json.dumps(raw_enriched, ensure_ascii=False),
                "search_norm": s_norm,
                "content_hash": chash,
            }
            # Optional classification columns if table has them
            if 'intent' in cols:
                base_values['intent'] = getattr(p, 'intent', None)
            if 'relevance_score' in cols:
                base_values['relevance_score'] = getattr(p, 'relevance_score', None)
            if 'confidence' in cols:
                base_values['confidence'] = getattr(p, 'confidence', None)
            if 'location_ok' in cols:
                loc_ok = getattr(p, 'location_ok', None)
                base_values['location_ok'] = int(loc_ok) if isinstance(loc_ok, bool) else (loc_ok if loc_ok is not None else None)
            if 'keywords_matched' in cols:
                km = getattr(p, 'keywords_matched', None)
                if isinstance(km, (list, tuple)):
                    try:
                        base_values['keywords_matched'] = json.dumps(list(km), ensure_ascii=False)
                    except Exception:
                        base_values['keywords_matched'] = None
                elif isinstance(km, str):
                    base_values['keywords_matched'] = km
            rows.append(base_values)
        if rows:
            # Build statement per current columns subset present
            col_names = list(rows[0].keys())
            placeholders = ",".join(["?"] * len(col_names))
            sql = f"INSERT OR IGNORE INTO posts ({','.join(col_names)}) VALUES ({placeholders})"
            conn.executemany(sql, [tuple(r[c] for c in col_names) for r in rows])
    # Auto-favorite opportunity posts (unified predicate utils.is_opportunity)
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS post_flags (
                post_id TEXT PRIMARY KEY,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                favorite_at TEXT,
                deleted_at TEXT
            )""")
        except Exception:
            pass
        if getattr(settings, "auto_favorite_opportunities", False):
            try:
                from datetime import datetime as _dt, timezone as _tz
                now_iso = _dt.now(_tz.utc).isoformat()
                fav_rows = []
                for p in posts:
                    try:
                        threshold = getattr(settings, "recruitment_signal_threshold", 0.05)
                        if p.raw and isinstance(p.raw, dict):  # type: ignore[truthy-bool]
                            threshold = p.raw.get('recruitment_threshold', threshold)  # type: ignore[arg-type]
                        if utils.is_opportunity(p.text, threshold=threshold):
                            fav_rows.append((p.id, 1, 0, now_iso, None))
                    except Exception:
                        continue
                if fav_rows:
                    conn.executemany("INSERT INTO post_flags(post_id,is_favorite,is_deleted,favorite_at,deleted_at) VALUES(?,?,?,?,?) ON CONFLICT(post_id) DO UPDATE SET is_favorite=excluded.is_favorite, favorite_at=excluded.favorite_at WHERE excluded.is_favorite=1", fav_rows)
            except Exception:
                pass


def _store_csv(csv_path: Path, posts: list[Post]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not csv_path.exists()
    import csv

    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if header_needed:
            writer.writerow([
                "id","keyword","author","author_profile","company","permalink","text","language","published_at","collected_at","raw_json"
            ])
        for p in posts:
            writer.writerow([
                p.id,
                p.keyword,
                p.author,
                p.author_profile or "",
                getattr(p, 'company', '') or "",
                getattr(p, 'permalink', '') or "",
                p.text,
                p.language,
                p.published_at or "",
                p.collected_at,
                json.dumps(p.raw, ensure_ascii=False),
            ])


# ------------------------------------------------------------
# Meta update
# ------------------------------------------------------------
async def update_meta(ctx: AppContext, total_new: int) -> None:
    if not ctx.mongo_client:
        return
    try:
        meta_coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_meta]
        await meta_coll.update_one(
            {"_id": "global"},
            {
                "$set": {"last_run": datetime.now(timezone.utc).isoformat()},
                "$inc": {"posts_count": total_new},
                "$setOnInsert": {"scraping_enabled": ctx.settings.scraping_enabled},
            },
            upsert=True,
        )
    except Exception as exc:  # pragma: no cover
        ctx.logger.error("meta_update_failed", error=str(exc))

async def update_meta_job_stats(ctx: AppContext, total_new: int, unknown_authors: int):
    """Augment meta with per-job unknown author stats (last job only)."""
    if not ctx.mongo_client:
        return
    try:
        meta_coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_meta]
        ratio = (unknown_authors / total_new) if total_new > 0 else 0.0
        await meta_coll.update_one(
            {"_id": "global"},
            {"$set": {"last_job_unknown_authors": unknown_authors, "last_job_posts": total_new, "last_job_unknown_ratio": ratio}},
            upsert=True,
        )
    except Exception as exc:  # pragma: no cover
        ctx.logger.error("meta_job_stats_failed", error=str(exc))


# ------------------------------------------------------------
# Playwright extraction logic (élargi)
# ------------------------------------------------------------
# Plusieurs sélecteurs possibles pour couvrir différents layouts LinkedIn.
POST_CONTAINER_SELECTORS = [
    "article[data-urn*='urn:li:activity']",
    "div.feed-shared-update-v2",
    "div.update-components-feed-update",
    "div.occludable-update",
    "div[data-urn*='urn:li:activity:']",
]
AUTHOR_SELECTOR = (
    "a.update-components-actor__meta-link, "
    "span.update-components-actor__meta a, "
    "a.update-components-actor__sub-description, "
    "a.update-components-actor__meta, "
    "a.app-aware-link, "
    "span.feed-shared-actor__name, "
    "span.update-components-actor__name"
)
TEXT_SELECTOR = (
    "div.update-components-text, "
    "div.feed-shared-update-v2__description-wrapper, "
    "span.break-words, "
    "div[dir='ltr']"
)
DATE_SELECTOR = "time"
MEDIA_INDICATOR_SELECTOR = "img, video"
PERMALINK_LINK_SELECTORS = [
    "a[href*='/feed/update/']",
    "a.app-aware-link[href*='activity']",
    "a[href*='/posts/']",
    "a[href*='activity']",
]
COMPANY_SELECTORS = [
    # Frequent pattern: span or div containing company/organization name near actor metadata
    "span.update-components-actor__company",
    "span.update-components-actor__supplementary-info",
    "div.update-components-actor__meta span",
    "div.feed-shared-actor__subtitle span",
    "span.feed-shared-actor__description",
    "span.update-components-actor__description",
]

# ------------------------------------------------------------
# Follower count cleaning (company pages sometimes appear as author)
# ------------------------------------------------------------
import re
_FOLLOWER_SEG_PATTERN = re.compile(r"\b\d[\d\s\.,]*\s*(k|m)?\s*(abonn[eé]s?|followers)\b", re.IGNORECASE)
_FOLLOWER_FULL_PATTERN = re.compile(r"^\s*\d[\d\s\.,]*\s*(k|m)?\s*(abonn[eé]s?|followers)\s*$", re.IGNORECASE)

# ------------------------------------------------------------
# Permalink canonicalisation & content hash helpers
# ------------------------------------------------------------
_ACTIVITY_ID_PATTERNS = [
    re.compile(r"urn:li:activity:(\d+)", re.IGNORECASE),
    re.compile(r"/activity/(\d+)", re.IGNORECASE),
    # posts slug sometimes ends with -<digits>
    re.compile(r"-(\d{8,})$"),
]

def _canonicalize_permalink(url: str | None) -> str | None:
    if not url:
        return url
    # Drop query, fragment, trailing slash
    base = url.split('?', 1)[0].split('#', 1)[0].rstrip('/')
    for pat in _ACTIVITY_ID_PATTERNS:
        m = pat.search(base)
        if m:
            act = m.group(1)
            return f"https://www.linkedin.com/feed/update/urn:li:activity:{act}"
    return base

def _compute_content_hash(author: str | None, text: str | None) -> str:
    import hashlib
    a = (author or '').strip().lower()
    t = (text or '')
    # Normalise whitespace & case
    t = _re.sub(r"\s+", " ", t).strip().lower()
    # Collapse long digit sequences to # to stabilise minor counters (views, likes)
    t = _re.sub(r"\d{2,}", "#", t)
    blob = f"{a}||{t}".encode('utf-8', errors='ignore')
    return hashlib.sha1(blob).hexdigest()[:20]

def _dedupe_repeated_author(name: str) -> str:
    if not name:
        return name
    toks = name.split()
    if len(toks) % 2 == 0 and len(toks) >= 4:
        half = len(toks)//2
        if toks[:half] == toks[half:]:
            return " ".join(toks[:half])
    # Remove network level markers like "3e et +"
    name = _re.sub(r"\b\d+e?\s+et\s*\+\b", "", name, flags=re.IGNORECASE)
    # Remove residual double spaces
    name = _re.sub(r"\s+", " ", name).strip()
    return name

def _strip_follower_segment(value: str) -> str:
    """Remove follower count fragments from an extracted string.

    Examples:
        "Entreprise • 32 474 abonnés" -> "Entreprise"
        "32 474 abonnés" -> "" (will become Unknown for author)
    """
    if not value:
        return value
    raw = value.strip()
    # Split on separators and remove pure follower tokens
    seps = [" • ", " · ", " | ", " - ", " – ", " — "]
    changed = False
    for sep in seps:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            filtered = [p for p in parts if not _FOLLOWER_FULL_PATTERN.match(p)]
            if filtered and len(filtered) != len(parts):
                raw = sep.join(filtered)
                changed = True
    # If entire string is a follower pattern -> blank
    if _FOLLOWER_FULL_PATTERN.match(raw):
        return ""
    # Remove inline follower segment at end (no separator case)
    if _FOLLOWER_SEG_PATTERN.search(raw):
        # Only strip if pattern appears after some non-digit letters (avoid killing company names with digits inside intentionally)
        raw = _FOLLOWER_SEG_PATTERN.sub("", raw).strip()
    return raw.strip()


async def _scroll_and_wait(page: Any, ctx: AppContext) -> None:
    """Perform one scroll iteration and wait for lazy content.

    Increments scroll metric. For now: simple window.scrollBy heuristic.
    """
    try:
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
    except Exception:  # pragma: no cover - ignore minor scrolling errors
        pass
    SCRAPE_SCROLL_ITERATIONS.inc()
    await page.wait_for_timeout(ctx.settings.scroll_wait_ms)


async def extract_posts(page: Any, keyword: str, max_items: int, ctx: AppContext) -> list[Post]:
    """Extract posts with iterative scrolling until conditions satisfied.

    Stops when either:
      - collected >= max_items OR
      - collected >= min_posts_target and no growth after last scroll OR
      - max_scroll_steps reached
    """
    posts: list[Post] = []
    seen_ids: set[str] = set()
    last_count = 0
    # Vérification basique d'authentification (indices de page de connexion)
    try:
        body_html = (await page.content()).lower()
        if any(marker in body_html for marker in ["se connecter", "join now", "créez votre profil", "s’inscrire"]):
            ctx.logger.warning("auth_suspect", detail="Texte suggérant une page non authentifiée")
    except Exception:
        pass

    # Adaptive scroll: decide dynamic max based on recent productivity
    dynamic_max_scroll = ctx.settings.max_scroll_steps
    try:
        if ctx.settings.adaptive_scroll_enabled and hasattr(ctx, "_recent_density"):
            dens = getattr(ctx, "_recent_density") or []
            if dens:
                avg = sum(dens)/len(dens)
                # If average posts per scroll low -> increase depth, else reduce
                if avg < 1.5:
                    dynamic_max_scroll = min(ctx.settings.adaptive_scroll_max, ctx.settings.max_scroll_steps + 2)
                elif avg > 3:
                    dynamic_max_scroll = max(ctx.settings.adaptive_scroll_min, ctx.settings.max_scroll_steps - 1)
    except Exception:
        pass
    for step in range(dynamic_max_scroll + 1):
        elements: list[Any] = []
        for selector in POST_CONTAINER_SELECTORS:
            try:
                found = await page.query_selector_all(selector)
                if found:
                    if step == 0:
                        ctx.logger.info("post_container_selector_match", selector=selector, count=len(found))
                    elements.extend(found)
            except Exception:
                continue
        if step == 0 and not elements:
            try:
                await page.wait_for_timeout(1200)
            except Exception:
                pass
        for el in elements:
            if len(posts) >= max_items:
                break
            try:
                author_el = await el.query_selector(AUTHOR_SELECTOR)
                text_el = await el.query_selector(TEXT_SELECTOR)
                date_el = await el.query_selector(DATE_SELECTOR)
                media_el = await el.query_selector(MEDIA_INDICATOR_SELECTOR)
                company_val: Optional[str] = None
                for csel in COMPANY_SELECTORS:
                    try:
                        c_el = await el.query_selector(csel)
                        if c_el:
                            raw_company = await c_el.inner_text()
                            if raw_company:
                                company_val = utils.normalize_whitespace(raw_company).strip()
                                if company_val:
                                    break
                    except Exception:
                        continue

                # ---------------------------
                # AUTHOR & COMPANY BLOCK
                # ---------------------------
                author = (await author_el.inner_text()) if author_el else "Unknown"
                if author:
                    author = utils.normalize_whitespace(author).strip()
                    for sep in [" •", "·", "Verified", "Vérifié"]:
                        if sep in author:
                            author = author.split(sep, 1)[0].strip()
                    if author.endswith("Premium"):
                        author = author.replace("Premium", "").strip()
                # Strip follower count segments wrongly captured as author (company pages)
                if author and _FOLLOWER_SEG_PATTERN.search(author.lower()):
                    cleaned = _strip_follower_segment(author)
                    author = cleaned or "Unknown"
                # Fallbacks for author when direct selector fails or yields generic text
                if not author or author.lower() == "unknown":
                    try:
                        meta_link = await el.query_selector("a.update-components-actor__meta-link")
                        if meta_link:
                            # Prefer aria-label as it often contains the full name
                            aria = await meta_link.get_attribute("aria-label")
                            if aria:
                                # Heuristic: cut before bullet or 'Vérifié'
                                cut = aria
                                for sep in [" •", "·", "Vérifié", "Verified", "•"]:
                                    if sep in cut:
                                        cut = cut.split(sep, 1)[0]
                                        break
                                cut = utils.normalize_whitespace(cut).strip()
                                if cut:
                                    author = cut
                            if (not author or author.lower() == "unknown"):
                                txt = await meta_link.inner_text()
                                if txt:
                                    txt = utils.normalize_whitespace(txt).strip()
                                    if txt:
                                        author = txt
                    except Exception:
                        pass
                if not author or author.lower() == "unknown":
                    try:
                        # Another structure: title span contains the name
                        title_span = await el.query_selector("span.update-components-actor__title span[dir='ltr']")
                        if title_span:
                            txt = await title_span.inner_text()
                            if txt:
                                author = utils.normalize_whitespace(txt).strip()
                    except Exception:
                        pass
                # Heuristic: if no company identified via selectors, attempt to derive from author string patterns
                # Patterns we encounter: "Nom • Rôle chez Entreprise", "Nom - Entreprise", "Nom | Entreprise"
                if not company_val and author and author != "Unknown":
                    for sep in ["•", "-", "|", "·"]:
                        if sep in author:
                            parts = [p.strip() for p in author.split(sep) if p.strip()]
                            # Remove trivial role-like suffixes (e.g. 'LL.M', 'PhD') before taking last
                            if len(parts) >= 2:
                                derived_company = parts[-1]
                                # Reject if identical to (cleaned) author name first token(s)
                                base_name = parts[0].lower()
                                if derived_company.lower() == base_name:
                                    continue
                                role_markers = ("juriste","avocat","counsel","lawyer","associate","stagiaire","intern","paralegal","legal","notaire")
                                # If derived segment is just a role marker, skip
                                if any(derived_company.lower().startswith(rm) for rm in role_markers):
                                    continue
                                if 2 < len(derived_company) <= 80 and not derived_company.lower().startswith("chez "):
                                    company_val = derived_company
                                    break
                # Strip follower counts from extracted company blocks
                if company_val and _FOLLOWER_SEG_PATTERN.search(company_val.lower()):
                    company_val = _strip_follower_segment(company_val) or None
                # Capture actor description (often contains role + company) for later derivation
                actor_description: Optional[str] = None
                try:
                    desc_el = await el.query_selector("span.update-components-actor__description")
                    if desc_el:
                        raw_desc = await desc_el.inner_text()
                        if raw_desc:
                            actor_description = utils.normalize_whitespace(raw_desc).strip()
                except Exception:
                    actor_description = None

                # If still no company, try to parse from actor description/body using patterns like '@ Company' or 'chez Company' or ' at Company'
                if not company_val:
                    candidates = []
                    if actor_description:
                        candidates.append(actor_description)
                    # text_norm available after text extraction below; we defer adding it until computed
                text_raw = (await text_el.inner_text()) if text_el else ""
                text_norm = utils.normalize_whitespace(text_raw)
                if not company_val and text_norm:
                    candidates.append(text_norm)
                if not company_val and candidates:
                    comp = None
                    for blob in candidates:
                        # Normalize blob for parsing
                        blob_clean = blob.replace(" at ", " chez ")
                        for marker in ["@ ", "chez "]:
                            if marker in blob_clean:
                                tail = blob_clean.split(marker, 1)[1].strip()
                                for stop in [" |", " -", ",", " •", "  "]:
                                    if stop in tail:
                                        tail = tail.split(stop, 1)[0].strip()
                                if 2 <= len(tail) <= 80:
                                    comp = tail
                                    break
                        if comp:
                            break
                    if comp:
                        # Avoid author duplication
                        if not author or comp.lower() != author.lower():
                            company_val = comp
                published_raw = (await date_el.get_attribute("datetime")) if date_el else None
                published_iso = None
                if published_raw:
                    published_iso = published_raw
                else:
                    txt_for_date = ""
                    if date_el:
                        try:
                            txt_for_date = await date_el.inner_text()
                        except Exception:
                            txt_for_date = ""
                    if not txt_for_date:
                        try:
                            subdesc = await el.query_selector("span.update-components-actor__sub-description")
                            if subdesc:
                                txt_for_date = await subdesc.inner_text()
                        except Exception:
                            pass
                    dt = utils.parse_possible_date(txt_for_date)
                    if dt:
                        published_iso = dt.isoformat()

                language = utils.detect_language(text_norm, ctx.settings.default_lang)
                # Provisional id; may be overridden by permalink-based id later
                provisional_pid = utils.make_post_id(keyword, author, published_iso or text_norm[:30])
                if provisional_pid in seen_ids:
                    continue
                seen_ids.add(provisional_pid)
                recruitment_score = utils.compute_recruitment_signal(text_norm)
                permalink = None
                permalink_source = None
                # 1. Sélecteurs directs
                try:
                    for sel_link in PERMALINK_LINK_SELECTORS:
                        l = await el.query_selector(sel_link)
                        if l:
                            href = await l.get_attribute("href") or ""
                            if href:
                                if href.startswith('/'):
                                    href = "https://www.linkedin.com" + href
                                if '?' in href:
                                    href = href.split('?', 1)[0]
                                permalink = href
                                permalink_source = f"selector:{sel_link}"
                                break
                except Exception:
                    pass
                # 2. Parent anchor du time
                if not permalink and date_el:
                    try:
                        parent_link = await date_el.evaluate("el => el.closest('a') ? el.closest('a').href : null")  # type: ignore
                        if parent_link:
                            if '?' in parent_link:
                                parent_link = parent_link.split('?', 1)[0]
                            if parent_link.startswith('/'):
                                parent_link = "https://www.linkedin.com" + parent_link
                            if parent_link:
                                permalink = parent_link
                                permalink_source = "time:closest"
                    except Exception:
                        pass
                # 3. Fallback: any anchor in container pointing to feed/update or activity
                if not permalink:
                    try:
                        a_el = await el.query_selector("a[href*='feed/update'], a[href*='activity']")
                        if a_el:
                            href = await a_el.get_attribute("href")
                            if href:
                                if '?' in href:
                                    href = href.split('?', 1)[0]
                                if href.startswith('/'):
                                    href = "https://www.linkedin.com" + href
                                permalink = href
                                permalink_source = "container:any-anchor"
                    except Exception:
                        pass
                # 3. Fallback URN
                if not permalink:
                    try:
                        urn = await el.get_attribute("data-urn") or ""
                        if "urn:li:activity:" in urn:
                            activity_id = urn.split("urn:li:activity:")[-1].strip()
                            if activity_id and activity_id.isdigit():
                                permalink = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"
                                permalink_source = "constructed_activity_id"
                    except Exception:
                        pass
                # 4. Last resort: scan inner HTML for any activity URN pattern if still missing
                if not permalink:
                    try:
                        html_blob = await el.inner_html()
                        if html_blob and "urn:li:activity:" in html_blob:
                            import re as _re_local
                            m_act = _re_local.search(r"urn:li:activity:(\d+)", html_blob)
                            if m_act:
                                activity_id = m_act.group(1)
                                permalink = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}"
                                permalink_source = "html_scan_activity_id"
                    except Exception:
                        pass
                if permalink_source:
                    ctx.logger.debug("permalink_resolved", source=permalink_source)
                if recruitment_score >= ctx.settings.recruitment_signal_threshold:
                    SCRAPE_RECRUITMENT_POSTS.inc()
                # Normalize permalink (remove trailing slash) to avoid duplicate logical posts
                if permalink:
                    permalink = _canonicalize_permalink(permalink)
                final_id = utils.make_post_id(permalink) if permalink else provisional_pid
                # Final author cleanup (after potential permalink resolution for stability)
                if author:
                    author = _dedupe_repeated_author(author)
                post = Post(
                    id=final_id,
                    keyword=keyword,
                    author=author,
                    author_profile=actor_description,
                    company=company_val,
                    text=text_norm,
                    language=language,
                    published_at=published_iso,
                    collected_at=datetime.now(timezone.utc).isoformat(),
                    # scores removed
                    permalink=permalink,
                    raw={"published_raw": published_raw, "recruitment_threshold": ctx.settings.recruitment_signal_threshold},
                )
                # Enforce strict filters: language FR, recruitment intent, author/permalink presence
                keep = True
                reject_reason = None
                try:
                    if ctx.settings.filter_language_strict and language.lower() != (ctx.settings.default_lang or "fr").lower():
                        keep = False; reject_reason = "language"
                    # Domain filter: require at least one legal keyword when enabled
                    if keep and getattr(ctx.settings, 'filter_legal_domain_only', False):
                        tl = (text_norm or "").lower()
                        legal_markers = (
                            "juriste","avocat","legal","counsel","paralegal","notaire","droit","fiscal","conformité","compliance","secrétaire général","secretaire general","contentieux","litige","corporate law","droit des affaires"
                        )
                        if not any(m in tl for m in legal_markers):
                            keep = False; reject_reason = reject_reason or "non_domain"
                    if ctx.settings.filter_recruitment_only and recruitment_score < ctx.settings.recruitment_signal_threshold:
                        if keep: keep = False; reject_reason = reject_reason or "recruitment"
                    if ctx.settings.filter_require_author_and_permalink and (not post.author or post.author.lower() == "unknown" or not post.permalink):
                        if keep: keep = False; reject_reason = reject_reason or "missing_core_fields"
                    # Exclude job-seeker / availability self-promotion posts
                    if keep and getattr(ctx.settings, 'filter_exclude_job_seekers', True):
                        tl = (text_norm or "").lower()
                        job_markers = (
                            "recherche d'emploi", "recherche d\u2019emploi", "cherche un stage", "cherche un emploi",
                            "à la recherche d'une opportunité", "a la recherche d'une opportunité",
                            "disponible immédiatement", "disponible immediatement", "open to work", "#opentowork",
                            "je suis à la recherche", "je suis a la recherche", "contactez-moi pour", "merci de me contacter",
                            "mobilité géographique", "mobilite geographique", "reconversion professionnelle"
                        )
                        if any(m in tl for m in job_markers):
                            keep = False; reject_reason = reject_reason or "job_seeker"
                    # France-only heuristic
                    if keep and getattr(ctx.settings, 'filter_france_only', True):
                        tl = (text_norm or "").lower()
                        fr_positive = ("france","paris","idf","ile-de-france","lyon","marseille","bordeaux","lille","toulouse","nice","nantes","rennes")
                        foreign_negative = ("hiring in uk","remote us","canada","usa","australia","dubai","switzerland","swiss","belgium","belgique","luxembourg","portugal","espagne","spain","germany","deutschland","italy","singapore")
                        if any(f in tl for f in foreign_negative) and not any(p in tl for p in fr_positive):
                            keep = False; reject_reason = reject_reason or "not_fr"
                except Exception:
                    pass
                if keep:
                    # Last sanitation: if company is identical to author, drop company to allow later normalization to fill
                    if post.company and post.author and post.company.lower() == post.author.lower():
                        post.company = None
                    posts.append(post)
                else:
                    try:
                        SCRAPE_FILTERED_POSTS.labels(reject_reason or "other").inc()
                    except Exception:
                        pass
            except Exception as exc:  # pragma: no cover
                ctx.logger.warning("extract_post_failed", error=str(exc))
        # Stopping conditions
        if len(posts) >= max_items:
            break
        if len(posts) >= ctx.settings.min_posts_target and len(posts) == last_count:
            # No growth after scroll beyond target
            break
        last_count = len(posts)
        if step < dynamic_max_scroll:
            await _scroll_and_wait(page, ctx)
    if len(posts) < ctx.settings.min_posts_target:
        SCRAPE_EXTRACTION_INCOMPLETE.inc()
    # Update moving density (posts per scroll step) for adaptive tuning
    try:
        if ctx.settings.adaptive_scroll_enabled:
            dens_list = getattr(ctx, "_recent_density", [])
            scrolls = max(1, min(dynamic_max_scroll, step + 1))
            dens_list.append(len(posts)/scrolls)
            win = ctx.settings.adaptive_scroll_window
            if len(dens_list) > win:
                dens_list = dens_list[-win:]
            setattr(ctx, "_recent_density", dens_list)
    except Exception:
        pass
    return posts


# ------------------------------------------------------------
# Job processing
# ------------------------------------------------------------
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(max=10),  # older tenacity signature (no multiplier)
    retry=retry_if_exception_type(ExtractionError),
    reraise=True,
)
async def process_keyword(keyword: str, ctx: AppContext, *, first_keyword: bool = False) -> list[Post]:
    logger = ctx.logger.bind(keyword=keyword, step="process_keyword")
    # Optional tracing (no hard dependency)
    span_ctx = None
    tracer = None
    try:  # pragma: no cover - optional path
        from opentelemetry import trace  # type: ignore

        tracer = trace.get_tracer("scraper")
        span_ctx = tracer.start_as_current_span("process_keyword", attributes={"keyword": keyword})
        span_ctx.__enter__()
    except Exception:
        span_ctx = None
    try:
        # Mock mode short-circuit (generate synthetic posts without browser)
        if ctx.settings.playwright_mock_mode:
            logger.info("mock_mode_active")
            now_iso = datetime.now(timezone.utc).isoformat()
            synthetic: list[Post] = []
            # Respect explicit max_mock_posts (tests rely on this) even if global per-keyword limit is higher
            limit = min(int(getattr(ctx.settings, 'max_mock_posts', 5) or 5), ctx.settings.max_posts_per_keyword)

            # Domain-specific recruitment roles (legal & fiscal)
            roles = [
                "avocat collaborateur","avocat associé","avocat counsel","paralegal","legal counsel","juriste",
                "responsable juridique","directeur juridique","notaire stagiaire","notaire associé","notaire salarié",
                "notaire assistant","clerc de notaire","rédacteur d’actes","responsable fiscal","directeur fiscal",
                "comptable taxateur","formaliste"
            ]
            contrats = ["CDI","CDD","Stage","Alternance","Freelance"]
            urgences = [
                "prise de poste immédiate","démarrage sous 30 jours","urgence recrutement","création de poste",
                "remplacement départ retraite","renforcement d’équipe"
            ]
            # Templates with placeholders {role}
            templates = [
                "Nous sommes à la recherche d’un {role} ({contrat}) pour renforcer notre équipe ({urgence}).",
                "Vous souhaitez rejoindre notre étude en tant que {role} ({contrat}) ? Postulez ! ({urgence})",
                "Opportunité: poste de {role} ouvert ({contrat}). {urgence}. Contactez-nous.",
                "Dans le cadre de notre croissance, nous recrutons un(e) {role} ({contrat}) motivé(e) – {urgence}.",
                "Rejoignez une équipe dynamique : poste {role} ({contrat}) à pourvoir ({urgence}).",
                "Annonce: création de poste {role} ({contrat}) – {urgence} (profil rigoureux & esprit d’équipe).",
                "Talents juridiques : votre profil de {role} ({contrat}) nous intéresse ! ({urgence})",
                "Envie d’évoluer ? Poste {role} ({contrat}) avec responsabilités transverses – {urgence}.",
            ]

            import random
            for i in range(limit):
                role = roles[(i + hash(keyword)) % len(roles)]
                template = templates[i % len(templates)]
                contrat = contrats[(i * 3 + len(keyword)) % len(contrats)]
                urgence = urgences[(i * 5 + hash(role)) % len(urgences)]
                text = template.format(role=role, contrat=contrat, urgence=urgence)
                # Slight enrichment referencing keyword occasionally
                if i % 2 == 0 and keyword.lower() not in text.lower():
                    text += f" (#{keyword})"
                lang = "fr"
                pid = utils.make_post_id(keyword, f"legal-mock-{i}-{role}", now_iso)
                rscore = utils.compute_recruitment_signal(text)
                if rscore >= ctx.settings.recruitment_signal_threshold:
                    SCRAPE_RECRUITMENT_POSTS.inc()
                synthetic.append(
                    Post(
                        id=pid,
                        keyword=keyword,
                        author="demo_recruteur",
                        author_profile=None,
                        company=None,
                        text=text,
                        language=lang,
                        published_at=now_iso,
                        collected_at=now_iso,
                        # keep score only in memory (not persisted)
                        score=rscore,
                        permalink=f"https://www.linkedin.com/feed/update/{pid}",
                        raw={"mode": "mock", "role": role, "contrat": contrat, "urgence": urgence},
                    )
                )
            logger.info("mock_posts_generated", count=len(synthetic), domain="legal_recruitment")
            SCRAPE_MOCK_POSTS_EXTRACTED.inc(len(synthetic))
            return synthetic

        # Non-mock direct invocation (legacy tests) returns empty list instead of raising
        if not ctx.settings.playwright_mock_mode:
            return []
        return []
    finally:
        if span_ctx is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                span_ctx.__exit__(None, None, None)


async def process_job(keywords: Iterable[str], ctx: AppContext) -> int:
    # Filter out blacklisted keywords (case-insensitive)
    try:
        bl_raw = getattr(ctx.settings, 'blacklisted_keywords_raw', '') or ''
        blacklist = {b.strip().lower() for b in bl_raw.split(';') if b.strip()}
    except Exception:
        blacklist = set()
    key_list = [k for k in list(keywords) if k and (k.strip().lower() not in blacklist)]
    all_new: list[Post] = []
    unknown_count = 0
    # Optional tracing span
    job_span = None
    try:  # pragma: no cover
        from opentelemetry import trace  # type: ignore
        tracer = trace.get_tracer("scraper")
        job_span = tracer.start_as_current_span("process_job", attributes={"keywords.count": len(key_list)})
        job_span.__enter__()
    except Exception:
        job_span = None
    # Reuse prepared keyword list
    iterable_keywords = key_list
    try:
        with SCRAPE_DURATION_SECONDS.time():  # histogram timing
            # Fast first cycle optimization: provide user with quick initial results then restore full settings
            fast_cycle_applied = False
            original_max_posts = ctx.settings.max_posts_per_keyword
            original_scroll_steps = ctx.settings.max_scroll_steps
            if getattr(ctx.settings, 'fast_first_cycle', False) and not getattr(ctx, '_fast_cycle_done', False) and not ctx.settings.playwright_mock_mode:
                # Apply conservative lightweight values to reduce initial latency (avoid long scrolling on first launch)
                try:
                    ctx.settings.max_posts_per_keyword = max(5, min(12, ctx.settings.max_posts_per_keyword))  # cap first fetch
                    ctx.settings.max_scroll_steps = max(2, min(3, ctx.settings.max_scroll_steps))
                    fast_cycle_applied = True
                    ctx.logger.debug("fast_first_cycle_applied", max_posts=ctx.settings.max_posts_per_keyword, scroll_steps=ctx.settings.max_scroll_steps)
                except Exception:
                    pass
            if ctx.settings.playwright_mock_mode:
                for idx, kw in enumerate(iterable_keywords):
                    if idx > 0 and ctx.settings.per_keyword_delay_ms > 0:
                        await asyncio.sleep(ctx.settings.per_keyword_delay_ms / 1000.0)
                    posts = await process_keyword(kw, ctx, first_keyword=(idx == 0))
                    all_new.extend(posts)
            else:
                real_posts = await process_keywords_batched(iterable_keywords, ctx)
                all_new.extend(real_posts)
            # Restore original settings after lightweight first cycle
            if fast_cycle_applied:
                try:
                    ctx.settings.max_posts_per_keyword = original_max_posts
                    ctx.settings.max_scroll_steps = original_scroll_steps
                    setattr(ctx, '_fast_cycle_done', True)
                    ctx.logger.debug("fast_first_cycle_restored", max_posts=original_max_posts, scroll_steps=original_scroll_steps)
                except Exception:
                    pass
            # Cross-keyword deduplication: prefer permalink; else author+published_at; else author+text snippet
            deduped: list[Post] = []
            seen_keys: set[str] = set()
            for p in all_new:
                # Canonical permalink key first
                if p.permalink:
                    key = f"perma|{_canonicalize_permalink(p.permalink)}"
                elif p.published_at and p.author:
                    key = f"authdate|{p.author}|{p.published_at}"
                else:
                    # Use stable content hash (same logic as storage) to reduce dupes when date missing
                    ch = _compute_content_hash(p.author, p.text)
                    key = f"authtext|{p.author}|{ch}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(p)
            # Apply legal classification & quota policy
            classified: list[Post] = []
            # Build dynamic legal keywords list (override/extend if provided)
            provided = []
            try:
                if ctx.settings.legal_keywords_override:
                    provided = [k.strip().lower() for k in ctx.settings.legal_keywords_override.split(';') if k.strip()]
            except Exception:
                provided = []
            # simple cap tracking per UTC day
            from datetime import date
            today = date.today().isoformat()
            if getattr(ctx, 'legal_daily_date', None) != today:
                setattr(ctx, 'legal_daily_date', today)
                setattr(ctx, 'legal_daily_count', 0)
            daily_count = getattr(ctx, 'legal_daily_count', 0)
            cap = ctx.settings.legal_daily_post_cap
            for p in deduped:
                # Only classify if French (existing filters may already narrow) – rely on stored language
                lc = classify_legal_post(p.text, language=p.language, intent_threshold=ctx.settings.legal_intent_threshold)
                LEGAL_INTENT_CLASSIFICATIONS_TOTAL.labels(lc.intent).inc()
                if lc.intent != 'recherche_profil':
                    LEGAL_POSTS_DISCARDED_TOTAL.labels('intent').inc()
                    # Track daily discarded by intent
                    try:
                        ctx.legal_daily_discard_intent = getattr(ctx, 'legal_daily_discard_intent', 0) + 1  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    continue
                if not lc.location_ok:
                    LEGAL_POSTS_DISCARDED_TOTAL.labels('location').inc()
                    try:
                        ctx.legal_daily_discard_location = getattr(ctx, 'legal_daily_discard_location', 0) + 1  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    continue
                # Enforce daily cap
                if daily_count >= cap:
                    LEGAL_DAILY_CAP_REACHED.inc()
                    break
                # Attach classification fields
                # Company duplicate reduction: if company repeats twice like 'ACME ACME' keep single
                if getattr(p, 'company', None):
                    import re as _re_local
                    comp = p.company.strip()
                    toks = comp.split()
                    if len(toks) % 2 == 0 and toks[:len(toks)//2] == toks[len(toks)//2:]:
                        p.company = " ".join(toks[:len(toks)//2])
                    # Collapse consecutive duplicate words
                    p.company = _re_local.sub(r"\b(\w+)(\s+\1)+\b", r"\1", p.company, flags=_re_local.IGNORECASE)
                setattr(p, 'intent', lc.intent)
                setattr(p, 'relevance_score', lc.relevance_score)
                setattr(p, 'confidence', lc.confidence)
                setattr(p, 'keywords_matched', lc.keywords_matched)
                setattr(p, 'location_ok', lc.location_ok)
                classified.append(p)
                daily_count += 1
            setattr(ctx, 'legal_daily_count', daily_count)
            LEGAL_POSTS_TOTAL.inc(len(classified))
            all_new = classified
            # Count unknown authors
            for p in all_new:
                if p.author == "Unknown":
                    unknown_count += 1
            await store_posts(ctx, all_new)

        SCRAPE_JOBS_TOTAL.labels(status="success").inc()
        SCRAPE_POSTS_EXTRACTED.inc(len(all_new))
        # -----------------------------
        # Daily quota tracking logic
        # -----------------------------
        try:
            from datetime import date
            today = date.today().isoformat()
            if ctx.daily_post_date != today:
                ctx.daily_post_date = today
                ctx.daily_post_count = 0
            ctx.daily_post_count += len(all_new)
        except Exception:
            pass
        await update_meta(ctx, len(all_new))
        await update_meta_job_stats(ctx, len(all_new), unknown_count)
        if broadcast and EventType:  # best-effort SSE
            try:
                await broadcast({
                    "type": EventType.JOB_COMPLETE,
                    "posts": len(all_new),
                    "unknown_authors": unknown_count,
                })
                # Quota progression event
                try:
                    target = ctx.settings.daily_post_target
                    soft = getattr(ctx.settings, 'daily_post_soft_target', max(1, int(target*0.8)))
                    collected = getattr(ctx, 'daily_post_count', 0)
                    await broadcast({
                        "type": EventType.QUOTA,
                        "collected": collected,
                        "soft": soft,
                        "target": target,
                        "mode": "cooldown" if collected >= target else ("accelerated" if collected < soft else "normal"),
                    })
                except Exception:
                    pass
            except Exception:
                pass
        return len(all_new)
    finally:
        if job_span is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                job_span.__exit__(None, None, None)


# ------------------------------------------------------------
# Redis queue consumption
# ------------------------------------------------------------
async def pop_job(ctx: AppContext) -> Optional[dict[str, Any]]:
    if not ctx.redis:
        return None
    # Simple blocking pop (BLPOP) with 5s timeout
    try:
        data = await ctx.redis.blpop(ctx.settings.redis_queue_key, timeout=5)
        if data is None:
            return None
        _key, payload = data
        return json.loads(payload)
    except Exception as exc:  # pragma: no cover
        ctx.logger.error("queue_pop_failed", error=str(exc))
        return None


# ------------------------------------------------------------
# Locking
# ------------------------------------------------------------
@contextlib.asynccontextmanager
async def run_with_lock(ctx: AppContext):
    lock = FileLock(ctx.settings.lock_file)
    try:
        lock.acquire(timeout=1)
        yield
    except Timeout:
        ctx.logger.warning("lock_busy", lock=ctx.settings.lock_file)
        yield  # skip run but allow graceful loop
    finally:
        if lock.is_locked:
            with contextlib.suppress(Exception):
                lock.release()


# ------------------------------------------------------------
# Main worker loop
# ------------------------------------------------------------
async def worker_loop() -> None:
    ctx = await get_context()
    logger = ctx.logger.bind(component="worker")
    logger.info("worker_started")
    # Risk mitigation state
    if not hasattr(ctx, "_risk_auth_suspect"):
        setattr(ctx, "_risk_auth_suspect", 0)
    if not hasattr(ctx, "_risk_empty_runs"):
        setattr(ctx, "_risk_empty_runs", 0)

    async def _post_cycle_risk_adjust(last_new: int, auth_suspect: bool):
        try:
            if auth_suspect:
                ctx._risk_auth_suspect += 1  # type: ignore[attr-defined]
            else:
                ctx._risk_auth_suspect = max(0, ctx._risk_auth_suspect - 1)  # type: ignore[attr-defined]
            if last_new == 0:
                ctx._risk_empty_runs += 1  # type: ignore[attr-defined]
            else:
                ctx._risk_empty_runs = max(0, ctx._risk_empty_runs - 1)  # type: ignore[attr-defined]
            # If thresholds exceeded -> cooldown pause
            if (ctx._risk_auth_suspect >= ctx.settings.risk_auth_suspect_threshold or  # type: ignore[attr-defined]
                ctx._risk_empty_runs >= ctx.settings.risk_empty_keywords_threshold):  # type: ignore[attr-defined]
                import random
                cooldown = random.randint(ctx.settings.risk_cooldown_min_seconds, ctx.settings.risk_cooldown_max_seconds)
                logger.warning("risk_cooldown", seconds=cooldown, auth_suspect=ctx._risk_auth_suspect, empty_runs=ctx._risk_empty_runs)
                # Broadcast risk cooldown event (non-blocking)
                if broadcast and EventType:
                    try:
                        await broadcast({"type": EventType.RISK_COOLDOWN, "seconds": cooldown, "auth_suspect": ctx._risk_auth_suspect, "empty_runs": ctx._risk_empty_runs})  # type: ignore[arg-type]
                    except Exception:
                        pass
                await asyncio.sleep(cooldown)
        except Exception:
            pass

    def _recent_auth_suspect_flag() -> bool:
        # Heuristic: if auth_suspect counter >0 treat as signal for now
        try:
            return getattr(ctx, "_risk_auth_suspect", 0) > 0
        except Exception:
            return False

    # If no redis available, single-run mode over configured keywords.
    if not ctx.redis:
        # Human-like continuous mode
        if ctx.settings.human_mode_enabled:
            import random, datetime
            logger.info("human_mode_enabled", start=ctx.settings.human_active_hours_start, end=ctx.settings.human_active_hours_end)
            import collections, time as _time
            window = collections.deque()  # timestamps of cycle completions
            while True:
                if not ctx.settings.scraping_enabled:
                    logger.info("scraping_disabled_wait")
                    await asyncio.sleep(5)
                    continue
                local_hour = datetime.datetime.now().hour
                in_active = ctx.settings.human_active_hours_start <= local_hour < ctx.settings.human_active_hours_end
                # Soft reset daily quota at day boundary
                try:
                    today = datetime.date.today().isoformat()
                    if ctx.daily_post_date != today:
                        ctx.daily_post_date = today
                        ctx.daily_post_count = 0
                except Exception:
                    pass
                # run a cycle
                async with run_with_lock(ctx):
                    try:
                        new = await process_job(ctx.settings.keywords, ctx)
                        logger.info("human_cycle_complete", new=new, hour=local_hour)
                    except Exception as exc:  # pragma: no cover
                        logger.error("human_cycle_failed", error=str(exc))
                # record completion
                now_ts = _time.time()
                window.append(now_ts)
                # drop entries older than 1 hour
                one_hour_ago = now_ts - 3600
                while window and window[0] < one_hour_ago:
                    window.popleft()
                # if cap exceeded, enforce a longer cooldown
                if len(window) >= max(1, ctx.settings.human_max_cycles_per_hour):
                    extra = 600  # 10 minutes cooldown when cap hit
                    logger.debug("human_hourly_cap_reached", cycles=len(window), cooldown=extra)
                    await asyncio.sleep(extra)
                # decide next pause
                if in_active:
                    # Adaptive pacing relative to daily target within remaining active window
                    try:
                        target = ctx.settings.daily_post_target
                        soft_target = getattr(ctx.settings, 'daily_post_soft_target', max(1, int(target*0.8)))
                        collected = getattr(ctx, 'daily_post_count', 0)
                        now = datetime.datetime.now()
                        # Remaining active minutes today
                        end_hour = ctx.settings.human_active_hours_end
                        remaining_minutes = max(1, (end_hour - now.hour - (1 if now.minute>0 else 0)) * 60 + (60 - now.minute)) if now.hour < end_hour else 1
                        remaining_needed = max(0, target - collected)
                        # If already met target -> elongate pauses significantly (cooldown mode)
                        if remaining_needed <= 0:
                            pause = random.randint(900, 1500)  # 15–25 min
                        elif collected < soft_target:
                            # Below soft threshold: accelerate (shorter pauses)
                            pause = random.randint(120, 300)
                        else:
                            # Desired cycles left = estimate posts per cycle (~avg) safeguard default 8
                            avg_posts = max(4, min(20, int(collected / max(1, len(window))) if window else 8))
                            cycles_needed = max(1, int(remaining_needed / avg_posts))
                            # Spread cycles across remaining time (convert minutes to seconds)
                            ideal_spacing = int((remaining_minutes * 60) / cycles_needed)
                            # Clamp spacing bounds (anti-ban jitter integrated)
                            base_min = max(60, ctx.settings.human_min_cycle_pause_seconds)
                            base_max = max(240, ctx.settings.human_max_cycle_pause_seconds)
                            # If we are behind (remaining_needed big vs time), reduce spacing; if ahead, increase
                            pause = int(min(max(ideal_spacing + random.randint(-30, 45), base_min), max(base_max, ideal_spacing * 1.5)))
                            # Random long break probability preserved when not behind schedule
                            if remaining_needed < target * 0.4 and random.random() < ctx.settings.human_long_break_probability:
                                pause = random.randint(ctx.settings.human_long_break_min_seconds, ctx.settings.human_long_break_max_seconds)
                        logger.debug("adaptive_human_pause", seconds=pause, collected=collected, target=target, remaining_needed=remaining_needed)
                        await asyncio.sleep(pause)
                    except Exception:
                        pause = random.randint(max(45, ctx.settings.human_min_cycle_pause_seconds), max(180, ctx.settings.human_max_cycle_pause_seconds))
                        await asyncio.sleep(pause)
                else:
                    # outside active hours: long cool-downs
                    if ctx.settings.human_night_mode:
                        pause = random.randint(ctx.settings.human_night_pause_min_seconds, ctx.settings.human_night_pause_max_seconds)
                        logger.debug("human_night_pause", seconds=pause)
                        await asyncio.sleep(pause)
                    else:
                        await asyncio.sleep(300)
        else:
            # Autonomous periodic mode if interval > 0
            if ctx.settings.autonomous_worker_interval_seconds > 0:
                logger.info("autonomous_mode_enabled", interval=ctx.settings.autonomous_worker_interval_seconds)
                while True:
                    if ctx.settings.scraping_enabled:
                        async with run_with_lock(ctx):
                            try:
                                new = await process_job(ctx.settings.keywords, ctx)
                                logger.info("autonomous_cycle_complete", new=new)
                                await _post_cycle_risk_adjust(new, auth_suspect=False)
                            except Exception as exc:  # pragma: no cover
                                logger.error("autonomous_cycle_failed", error=str(exc))
                    else:
                        logger.info("scraping_disabled_wait")
                    # Adaptive interval shrink if far from daily target during active hours window 9-18 by default
                    try:
                        import datetime as _dt, random
                        now = _dt.datetime.now()
                        target = ctx.settings.daily_post_target
                        soft_target = getattr(ctx.settings, 'daily_post_soft_target', max(1, int(target*0.8)))
                        collected = getattr(ctx, 'daily_post_count', 0)
                        active_start, active_end = 9, 18
                        base_interval = ctx.settings.autonomous_worker_interval_seconds
                        if active_start <= now.hour < active_end:
                            remaining = max(1, target - collected)
                            hours_left = max(0.25, active_end - now.hour - now.minute/60.0)
                            # posts/hour needed
                            pph_needed = remaining / hours_left if hours_left > 0 else remaining
                            # Rough per-cycle yield guess (8) to derive desired interval
                            est_per_cycle = 8
                            if collected < soft_target:
                                # Force more frequent cycles early in the day until soft target reached
                                desired_interval = 300
                            else:
                                desired_interval = int(min(base_interval, max(300, (est_per_cycle / max(1, pph_needed)) * 3600))) if remaining > 0 else int(base_interval * random.uniform(1.2, 1.8))
                            sleep_next = max(180, min(base_interval, desired_interval))
                        else:
                            sleep_next = int(base_interval * 1.5)
                    except Exception:
                        sleep_next = ctx.settings.autonomous_worker_interval_seconds
                    await asyncio.sleep(sleep_next)
            else:
                if ctx.settings.scraping_enabled:
                    async with run_with_lock(ctx):
                        new = await process_job(ctx.settings.keywords, ctx)
                        await _post_cycle_risk_adjust(new, auth_suspect=False)
                else:
                    logger.info("scraping_disabled")
        return

    # Continuous loop: poll queue
    # Concurrency: simple semaphore for processing jobs concurrently if future expansion uses parallel tasks.
    semaphore = asyncio.Semaphore(ctx.settings.concurrency_limit)

    async def _handle_job(job_keywords: list[str]):
        async with semaphore:
            async with run_with_lock(ctx):
                try:
                    count = await process_job(job_keywords, ctx)
                    logger.info("job_done", keywords=job_keywords, new=count)
                except Exception as exc:  # pragma: no cover
                    SCRAPE_JOBS_TOTAL.labels(status="error").inc()
                    SCRAPE_JOB_FAILURES.inc()
                    logger.error("job_failed", error=str(exc))

    active_tasks: set[asyncio.Task] = set()

    while True:
        if not ctx.settings.scraping_enabled:
            logger.info("scraping_disabled_wait")
            await asyncio.sleep(5)
            continue
        job = await pop_job(ctx)
        if not job:
            # Idle wait with human jitter
            try:
                import random
                jitter = random.randint(ctx.settings.human_jitter_min_ms, ctx.settings.human_jitter_max_ms)/1000.0
            except Exception:
                jitter = ctx.settings.job_poll_interval
            await asyncio.sleep(max(jitter, ctx.settings.job_poll_interval))
            continue
        keywords = job.get("keywords") or ctx.settings.keywords
        if not isinstance(keywords, list):
            logger.warning("invalid_job_keywords", job=job)
            continue
        # Update queue depth metric
        if ctx.redis:
            try:
                depth = await ctx.redis.llen(ctx.settings.redis_queue_key)
                SCRAPE_QUEUE_DEPTH.set(depth)
            except Exception:  # pragma: no cover
                pass
        # Launch job task
        t = asyncio.create_task(_handle_job(keywords))
        active_tasks.add(t)
        t.add_done_callback(active_tasks.discard)
        # Small cooldown to avoid burst loops
        try:
            import random
            await asyncio.sleep(0.5 + random.random()*0.8)
        except Exception:
            await asyncio.sleep(1)


# Entry point
if __name__ == "__main__":  # pragma: no cover
    asyncio.run(worker_loop())
