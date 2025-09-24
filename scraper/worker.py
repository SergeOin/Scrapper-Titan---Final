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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

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
    get_context,
)
from . import utils
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
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=ctx.settings.playwright_headless_scrape)
        # IMPORTANT: storage_state must be applied on a BrowserContext, not directly on a Page
        context = await browser.new_context(
            storage_state=ctx.settings.storage_state if os.path.exists(ctx.settings.storage_state) else None
        )
        page = await context.new_page()
        # Ensure authentication before iterating keywords
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
        # Close browser
        try:
            await browser.close()
        except Exception:
            pass
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
        async with async_playwright() as pw:
            recovery = await _recover_browser(pw, ctx, logger)
            if recovery is None:
                logger.warning("skip_batch_recovery_failed", batch=batch)
                continue
            browser, page = recovery
            try:
                for idx, keyword in enumerate(batch):
                    if ctx.settings.adaptive_pause_every > 0 and results and (len(results) // ctx.settings.max_posts_per_keyword) % ctx.settings.adaptive_pause_every == 0 and (len(results) // ctx.settings.max_posts_per_keyword) != 0:
                        # Rough heuristic: each keyword contributes up to max_posts_per_keyword posts
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
                    # Geo-bias the search to France to improve locality of results
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
                        # Attempt screenshot for diagnostics
                        try:
                            screenshot_path = Path(ctx.settings.screenshot_dir) / f"error_{keyword.replace(' ','_')}.png"
                            await page.screenshot(path=str(screenshot_path))
                            logger.info("keyword_error_screenshot", path=str(screenshot_path))
                        except Exception:
                            pass
            finally:
                # Diagnostic screenshot at end of batch
                try:
                    if not page.is_closed():
                        end_shot = Path(ctx.settings.screenshot_dir) / f"batch_{batch_index//batch_size + 1}_end.png"
                        await page.screenshot(path=str(end_shot))
                        logger.info("batch_screenshot", path=str(end_shot))
                except Exception:
                    pass
                with contextlib.suppress(Exception):
                    await browser.close()
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
    # Safety net: if mock mode is disabled, drop any mock/demo posts accidentally present
    try:
        if not ctx.settings.playwright_mock_mode:
            posts = [p for p in posts if (p.author or '').lower() != 'demo_recruteur' and (not p.raw or p.raw.get('mode') != 'mock')]
            if not posts:
                return
    except Exception:
        pass
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
            _store_sqlite(ctx.settings.sqlite_path, posts)
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


def _store_sqlite(path: str, posts: list[Post]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        # If legacy table exists with score columns, migrate to new layout without them.
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
            search_norm TEXT
            )"""
        )
        # Detect legacy columns
        try:
            cur = conn.execute("PRAGMA table_info(posts)")
            cols = [r[1] for r in cur.fetchall()]
            if "score" in cols or "recruitment_score" in cols:
                # Perform lightweight migration: create temp, copy subset, drop old, rename
                conn.execute("CREATE TABLE IF NOT EXISTS posts_new (id TEXT PRIMARY KEY, keyword TEXT, author TEXT, author_profile TEXT, company TEXT, permalink TEXT, text TEXT, language TEXT, published_at TEXT, collected_at TEXT, raw_json TEXT, search_norm TEXT)")
                # Copy only needed columns if they exist
                copy_cols_src = [c for c in ["id","keyword","author","author_profile","company","permalink","text","language","published_at","collected_at","raw_json","search_norm"] if c in cols]
                copy_cols_dst = ["id","keyword","author","author_profile","company","permalink","text","language","published_at","collected_at","raw_json","search_norm"]
                conn.execute(f"INSERT OR IGNORE INTO posts_new ({','.join(copy_cols_dst)}) SELECT {','.join(copy_cols_src)} FROM posts")
                conn.execute("DROP TABLE posts")
                conn.execute("ALTER TABLE posts_new RENAME TO posts")
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
        except Exception:
            pass
        rows = []
        for p in posts:
            try:
                s_norm = utils.build_search_norm(p.text, p.author, getattr(p, 'company', None), p.keyword)
            except Exception:
                s_norm = None
            rows.append((
                p.id,
                p.keyword,
                p.author,
                p.author_profile,
                getattr(p, 'company', None),
                getattr(p, 'permalink', None),
                p.text,
                p.language,
                p.published_at,
                p.collected_at,
                json.dumps(p.raw, ensure_ascii=False),
                s_norm,
            ))
        conn.executemany("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)


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

    for step in range(ctx.settings.max_scroll_steps + 1):
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

                author = (await author_el.inner_text()) if author_el else "Unknown"
                if author:
                    author = utils.normalize_whitespace(author).strip()
                    for sep in [" •", "·", "Verified", "Vérifié"]:
                        if sep in author:
                            author = author.split(sep, 1)[0].strip()
                    if author.endswith("Premium"):
                        author = author.replace("Premium", "").strip()
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
                # Heuristic: if no company identified via selectors, attempt to derive from author string patterns ("Nom • Entreprise" or "Nom - Entreprise")
                if not company_val and author and author != "Unknown":
                    for sep in ["•", "-", "|", "·"]:
                        if sep in author:
                            parts = [p.strip() for p in author.split(sep) if p.strip()]
                            if len(parts) >= 2:
                                # Assume first part is person name, last part company label
                                # Keep full author as original; set company separately
                                derived_company = parts[-1]
                                # Avoid setting company if obviously a role rather than org (simple length/keyword heuristic)
                                if len(derived_company) > 2 and not derived_company.lower().startswith("chez "):
                                    company_val = derived_company
                                break
                # If still no company, try to parse from actor description/body using patterns like '@ Company' or 'chez Company' or ' at Company'
                if not company_val:
                    try:
                        desc_el = await el.query_selector("span.update-components-actor__description")
                        desc_txt = utils.normalize_whitespace(await desc_el.inner_text()) if desc_el else ""
                    except Exception:
                        desc_txt = ""
                    candidates = []
                    if desc_txt:
                        candidates.append(desc_txt)
                    # text_norm is available after text extraction, but we can compute it now
                    text_raw = (await text_el.inner_text()) if text_el else ""
                    text_norm = utils.normalize_whitespace(text_raw)
                    if text_norm:
                        candidates.append(text_norm)
                    comp = None
                    for blob in candidates:
                        for marker in ["@ ", "chez ", " at "]:
                            if marker in blob:
                                tail = blob.split(marker, 1)[1].strip()
                                for stop in [" |", " -", ",", " •", "  "]:
                                    if stop in tail:
                                        tail = tail.split(stop, 1)[0].strip()
                                if 2 <= len(tail) <= 80:
                                    comp = tail
                                    break
                        if comp:
                            break
                    if comp:
                        company_val = comp
                text_raw = (await text_el.inner_text()) if text_el else ""
                text_norm = utils.normalize_whitespace(text_raw)
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
                if permalink_source:
                    ctx.logger.debug("permalink_resolved", source=permalink_source)
                if recruitment_score >= ctx.settings.recruitment_signal_threshold:
                    SCRAPE_RECRUITMENT_POSTS.inc()
                final_id = utils.make_post_id(permalink) if permalink else provisional_pid
                post = Post(
                    id=final_id,
                    keyword=keyword,
                    author=author,
                    author_profile=None,
                    company=company_val,
                    text=text_norm,
                    language=language,
                    published_at=published_iso,
                    collected_at=datetime.now(timezone.utc).isoformat(),
                    # scores removed
                    permalink=permalink,
                    raw={"published_raw": published_raw},
                )
                # Enforce strict filters: language FR, recruitment intent, author/permalink presence
                keep = True
                try:
                    if ctx.settings.filter_language_strict and language.lower() != (ctx.settings.default_lang or "fr").lower():
                        keep = False
                    if ctx.settings.filter_recruitment_only and recruitment_score < ctx.settings.recruitment_signal_threshold:
                        keep = False
                    if ctx.settings.filter_require_author_and_permalink and (not post.author or post.author.lower() == "unknown" or not post.permalink):
                        keep = False
                except Exception:
                    pass
                if keep:
                    posts.append(post)
            except Exception as exc:  # pragma: no cover
                ctx.logger.warning("extract_post_failed", error=str(exc))
        # Stopping conditions
        if len(posts) >= max_items:
            break
        if len(posts) >= ctx.settings.min_posts_target and len(posts) == last_count:
            # No growth after scroll beyond target
            break
        last_count = len(posts)
        if step < ctx.settings.max_scroll_steps:
            await _scroll_and_wait(page, ctx)
    if len(posts) < ctx.settings.min_posts_target:
        SCRAPE_EXTRACTION_INCOMPLETE.inc()
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
            limit = min(ctx.settings.max_mock_posts, ctx.settings.max_posts_per_keyword)

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

        # In refactored flow this function is only used for mock mode now.
        if not ctx.settings.playwright_mock_mode:
            raise RuntimeError("process_keyword direct call only valid in mock mode now")
        return []  # Should never reach here for mock path (handled above)
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
            if ctx.settings.playwright_mock_mode:
                for idx, kw in enumerate(iterable_keywords):
                    if idx > 0 and ctx.settings.per_keyword_delay_ms > 0:
                        await asyncio.sleep(ctx.settings.per_keyword_delay_ms / 1000.0)
                    posts = await process_keyword(kw, ctx, first_keyword=(idx == 0))
                    all_new.extend(posts)
            else:
                real_posts = await process_keywords_batched(iterable_keywords, ctx)
                all_new.extend(real_posts)
            # Cross-keyword deduplication: prefer permalink; else author+published_at; else author+text snippet
            deduped: list[Post] = []
            seen_keys: set[str] = set()
            for p in all_new:
                if p.permalink:
                    key = f"perma|{p.permalink}"
                elif p.published_at and p.author:
                    key = f"authdate|{p.author}|{p.published_at}"
                else:
                    key = f"authtext|{p.author}|{p.text[:80]}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(p)
            all_new = deduped
            # Count unknown authors
            for p in all_new:
                if p.author == "Unknown":
                    unknown_count += 1
            await store_posts(ctx, all_new)

        SCRAPE_JOBS_TOTAL.labels(status="success").inc()
        SCRAPE_POSTS_EXTRACTED.inc(len(all_new))
        await update_meta(ctx, len(all_new))
        await update_meta_job_stats(ctx, len(all_new), unknown_count)
        if broadcast and EventType:  # best-effort SSE
            try:
                await broadcast({
                    "type": EventType.JOB_COMPLETE,
                    "posts": len(all_new),
                    "unknown_authors": unknown_count,
                })
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

    # If no redis available, single-run mode over configured keywords.
    if not ctx.redis:
        # Autonomous periodic mode if interval > 0
        if ctx.settings.autonomous_worker_interval_seconds > 0:
            logger.info("autonomous_mode_enabled", interval=ctx.settings.autonomous_worker_interval_seconds)
            while True:
                if ctx.settings.scraping_enabled:
                    async with run_with_lock(ctx):
                        try:
                            new = await process_job(ctx.settings.keywords, ctx)
                            logger.info("autonomous_cycle_complete", new=new)
                        except Exception as exc:  # pragma: no cover
                            logger.error("autonomous_cycle_failed", error=str(exc))
                else:
                    logger.info("scraping_disabled_wait")
                await asyncio.sleep(ctx.settings.autonomous_worker_interval_seconds)
        else:
            if ctx.settings.scraping_enabled:
                async with run_with_lock(ctx):
                    await process_job(ctx.settings.keywords, ctx)
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
            # Idle wait
            await asyncio.sleep(ctx.settings.job_poll_interval)
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
        await asyncio.sleep(1)


# Entry point
if __name__ == "__main__":  # pragma: no cover
    asyncio.run(worker_loop())
