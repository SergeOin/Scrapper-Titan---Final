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
import sys
import contextlib
import json
import os
import sqlite3
import time
import re as _re  # local lightweight regex (avoid repeated imports)
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
    SCRAPE_STORAGE_ATTEMPTS,
    SCRAPE_QUEUE_DEPTH,
    SCRAPE_JOB_FAILURES,
    SCRAPE_STEP_DURATION,
    SCRAPE_RATE_LIMIT_TOKENS,
    SCRAPE_SCROLL_ITERATIONS,
    SCRAPE_EXTRACTION_INCOMPLETE,
    SCRAPE_RECRUITMENT_POSTS,
    SCRAPE_FILTERED_POSTS,
    get_context,
)
from .core.orchestrator import run_orchestrator, select_mode
from .core.extract import extract_posts  # migrated extraction logic
from .core.errors import log_playwright_failure
from .core.storage import store_posts_sqlite
from .core.ids import canonical_permalink, content_hash
from .core.maintenance import purge_and_vacuum
from . import utils
from .runtime import JobResult, RuntimePost
from .runtime import mock as runtime_mock
from .runtime.pipeline import finalize_job_result
try:
    from server.events import broadcast, EventType  # type: ignore
except Exception:  # pragma: no cover
    broadcast = None  # type: ignore
    EventType = None  # type: ignore

# Event loop policy is now fixed early in sitecustomize.py (remove redundant enforcement here)

# Delay Playwright import until after policy enforcement.
try:  # Optional heavy import lazy usage
    from playwright.async_api import async_playwright, Page, Browser
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore
    Page = Any  # type: ignore
    Browser = Any  # type: ignore

except Exception:
    pass  # Any import-time issues ignored (sync fallback handled elsewhere)

# ... existing code continues ...

# ------------------------------------------------------------
# Lightweight recovery & navigation helpers (previously lost in refactor)
# ------------------------------------------------------------
@dataclass
class PlaywrightSessionHandle:
    browser: Any | None
    context: Any
    page: Any

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            if hasattr(self.page, "is_closed") and not self.page.is_closed():
                await self.page.close()
        with contextlib.suppress(Exception):
            await self.context.close()
        if self.browser and self.browser is not self.context:
            with contextlib.suppress(Exception):
                await self.browser.close()


async def _hydrate_context_from_storage(context, storage_state_data: Optional[dict[str, Any]], logger) -> bool:  # type: ignore[no-untyped-def]
    if not storage_state_data:
        return False
    cookies = storage_state_data.get("cookies") or []
    normalized = []
    for raw in cookies:
        try:
            name = raw["name"]
            value = raw["value"]
        except KeyError:
            continue
        domain = raw.get("domain") or ".linkedin.com"
        path = raw.get("path") or "/"
        same_site = raw.get("sameSite")
        if isinstance(same_site, str):
            low = same_site.lower()
            if low in ("no_restriction", "none"):
                same_site = "None"
            elif low == "lax":
                same_site = "Lax"
            elif low == "strict":
                same_site = "Strict"
            else:
                same_site = None
        cookie = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "secure": bool(raw.get("secure", True)),
            "httpOnly": bool(raw.get("httpOnly", False)),
        }
        if same_site:
            cookie["sameSite"] = same_site
        expires = raw.get("expires")
        if isinstance(expires, (int, float)):
            cookie["expires"] = expires
        normalized.append(cookie)
    if not normalized:
        return False
    try:
        await context.add_cookies(normalized)
        logger.debug("storage_state_cookies_applied", count=len(normalized))
        return True
    except Exception as exc:  # pragma: no cover - diagnostic only
        logger.warning("storage_state_cookie_apply_failed", error=str(exc))
        return False


async def _recover_browser(pw, ctx: AppContext, logger):  # type: ignore[no-untyped-def]
    """Attempt to launch a Chromium browser and return a ready PlaywrightSessionHandle."""

    launch_args = [
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-extensions",
        "--disable-gpu",
    ]
    headless = bool(ctx.settings.playwright_headless_scrape)
    user_data_dir = None
    storage_state_data: Optional[dict[str, Any]] = None
    storage_state_path = Path(ctx.settings.storage_state)
    if storage_state_path.exists():
        try:
            storage_state_data = json.loads(storage_state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            if not getattr(ctx, "_storage_state_parse_warned", False):
                logger.warning("storage_state_parse_failed", path=str(storage_state_path), error=str(exc))
                setattr(ctx, "_storage_state_parse_warned", True)
    else:
        if not getattr(ctx, "_storage_state_missing_warned", False):
            logger.warning("storage_state_missing", path=str(storage_state_path))
            setattr(ctx, "_storage_state_missing_warned", True)
    try:
        browser = await pw.chromium.launch(headless=headless, args=launch_args)  # type: ignore[attr-defined]
        context = await browser.new_context()
        await _hydrate_context_from_storage(context, storage_state_data, logger)
        page = await context.new_page()
        return PlaywrightSessionHandle(browser=browser, context=context, page=page)
    except Exception as first_exc:  # pragma: no cover - fallback path
        logger.warning("browser_primary_launch_failed", error=str(first_exc))
        try:
            log_playwright_failure("launch_primary", first_exc)
        except Exception:
            pass
        # Persistent recovery
        with contextlib.suppress(Exception):
            from tempfile import mkdtemp
            user_data_dir = Path(mkdtemp(prefix="pw_ud_"))
        try:
            context = await pw.chromium.launch_persistent_context(  # type: ignore[attr-defined]
                user_data_dir=str(user_data_dir), headless=headless, args=launch_args
            )
            await _hydrate_context_from_storage(context, storage_state_data, logger)
            page = context.pages[0] if context.pages else await context.new_page()
            logger.info("browser_recovered_persistent")
            return PlaywrightSessionHandle(browser=None, context=context, page=page)
        except Exception as second_exc:
            logger.error("browser_recovery_failed", error=str(second_exc))
            try:
                log_playwright_failure("launch_recovery", second_exc)
            except Exception:
                pass
            with contextlib.suppress(Exception):
                if user_data_dir:
                    import shutil
                    shutil.rmtree(user_data_dir, ignore_errors=True)
            return None


async def _attempt_navigation(page, url: str, ctx: AppContext, logger) -> bool:  # type: ignore[no-untyped-def]
    """Navigate with limited retries and simple readiness heuristics."""
    max_nav = 2
    for attempt in range(1, max_nav + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Basic heuristic: presence of search or feed container
            with contextlib.suppress(Exception):
                await page.wait_for_selector("main, div.scaffold-layout__main, div.feed-shared-update-v2", timeout=5_000)
            return True
        except Exception as exc:  # pragma: no cover - transient nav errors
            logger.warning("navigation_retry", attempt=attempt, url=url, error=str(exc))
            if attempt < max_nav:
                await asyncio.sleep(1.2 * attempt)
            else:
                return False
    return False

async def process_keywords_batched(all_keywords: list[str], ctx: AppContext) -> list[Post]:
    if async_playwright is None:
        raise RuntimeError("Playwright not installed.")
    logger = ctx.logger.bind(component="batched_session")
    if getattr(ctx, "quota_exceeded", False):
        logger.info("quota_skip_keywords", reason="daily_limit_reached")
        return []
    batch_size = max(1, ctx.settings.keywords_session_batch_size)
    results: list[Post] = []
    # Split keywords into batches
    for batch_index in range(0, len(all_keywords), batch_size):
        batch = all_keywords[batch_index: batch_index + batch_size]
        logger.info("batch_start", batch_index=batch_index//batch_size + 1, size=len(batch))
        # Wrapper with explicit retries + loop policy fallback for Playwright launch
        launch_attempts = 0
        max_attempts = 2  # 1) selector (par défaut), 2) proactor fallback
        last_error: Optional[str] = None
        while launch_attempts < max_attempts:
            try:
                launch_attempts += 1
                if os.name == "nt":
                    pol = asyncio.get_event_loop_policy().__class__.__name__
                    # Allow optional explicit selector forcing via env
                    if os.getenv("WORKER_FORCE_SELECTOR") in ("1","true","yes","on") and sys.platform.startswith("win") and "Selector" not in pol:
                        try:
                            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
                            pol2 = asyncio.get_event_loop_policy().__class__.__name__
                            logger.warning("event_loop_policy_forced_selector_worker", previous=pol, new=pol2)
                            pol = pol2
                        except Exception as e:  # pragma: no cover
                            logger.warning("event_loop_policy_selector_force_failed", error=str(e), previous=pol)
                    # If still Selector and no explicit force, try upgrading to Proactor before Playwright
                    if os.getenv("WORKER_FORCE_SELECTOR") not in ("1","true","yes","on") and "Selector" in pol:
                        try:
                            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]
                            pol3 = asyncio.get_event_loop_policy().__class__.__name__
                            logger.info("event_loop_policy_upgraded_proactor", previous=pol, new=pol3)
                            pol = pol3
                        except Exception as e:  # pragma: no cover
                            logger.warning("event_loop_policy_upgrade_failed", error=str(e), previous=pol)
                    logger.info("playwright_launch_attempt", attempt=launch_attempts, policy=pol)
                handle: PlaywrightSessionHandle | None = None
                async with async_playwright() as pw:
                    # Apply a timeout to recovery to avoid hanging indefinitely if Chromium crashes silently
                    timeout_seconds = int(os.environ.get("PLAYWRIGHT_RECOVER_TIMEOUT_SECONDS", "15"))
                    try:
                        handle = await asyncio.wait_for(_recover_browser(pw, ctx, logger), timeout=timeout_seconds)
                    except asyncio.TimeoutError:
                        logger.error("browser_launch_timeout", timeout_seconds=timeout_seconds)
                        handle = None
                    if handle is None:
                        logger.warning("skip_batch_recovery_failed", batch=batch)
                        break
                    page = handle.page
                    try:
                        for idx, keyword in enumerate(batch):
                            if ctx.settings.adaptive_pause_every > 0 and results and (len(results) // ctx.settings.max_posts_per_keyword) % ctx.settings.adaptive_pause_every == 0 and (len(results) // ctx.settings.max_posts_per_keyword) != 0:
                                logger.info("adaptive_pause", seconds=ctx.settings.adaptive_pause_seconds)
                                await asyncio.sleep(ctx.settings.adaptive_pause_seconds)
                            if page.is_closed():
                                logger.warning("page_closed_detected", action="attempt_recovery")
                                if handle:
                                    with contextlib.suppress(Exception):
                                        await handle.close()
                                handle = await _recover_browser(pw, ctx, logger)
                                if handle is None:
                                    logger.error("page_recovery_failed", keyword=keyword)
                                    break
                                page = handle.page
                            if ctx.token_bucket:
                                await ctx.token_bucket.consume(1)
                                SCRAPE_RATE_LIMIT_TOKENS.set(ctx.token_bucket.tokens)
                            try:
                                search_url = f"https://www.linkedin.com/search/results/content/?keywords={keyword}"
                                ok = await _attempt_navigation(page, search_url, ctx, logger)
                                if not ok:
                                    logger.warning("navigation_gave_up", keyword=keyword)
                                    continue
                                # Log final URL + attempt lightweight root readiness
                                try:
                                    current_url = page.url
                                except Exception:
                                    current_url = "<unknown>"
                                logger.info("navigation_arrived", keyword=keyword, url=current_url)
                                # Wait for a generic root container (non-fatal)
                                root_wait_ms = int(os.environ.get("PLAYWRIGHT_ROOT_WAIT_MS", "4000"))
                                with contextlib.suppress(Exception):
                                    await page.wait_for_selector("main, div.scaffold-layout__main, div.feed-shared-update-v2", timeout=root_wait_ms)
                                posts = await extract_posts(page, keyword, ctx.settings.max_posts_per_keyword, ctx)
                                logger.info("keyword_extracted", keyword=keyword, count=len(posts))
                                results.extend(posts)
                            except Exception as exc:
                                logger.warning("keyword_failed", keyword=keyword, error=str(exc))
                        # Diagnostic fin de batch
                        if not page.is_closed():
                            with contextlib.suppress(Exception):
                                end_shot = Path(ctx.settings.screenshot_dir) / f"batch_{batch_index//batch_size + 1}_end.png"
                                await page.screenshot(path=str(end_shot))
                                logger.info("batch_screenshot", path=str(end_shot))
                    finally:
                        if handle:
                            with contextlib.suppress(Exception):
                                await handle.close()
                            handle = None
                last_error = None  # success
                break
            except NotImplementedError as ne:
                last_error = str(ne)
                logger.error("playwright_not_implemented", attempt=launch_attempts, error=last_error)
                try:
                    log_playwright_failure("not_implemented", last_error or "")
                except Exception:
                    pass
                if os.name == "nt" and launch_attempts < max_attempts:
                    # Force Selector loop then retry once
                    try:
                        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
                        logger.warning("event_loop_policy_recover_selector")
                    except Exception as exc:
                        logger.warning("event_loop_policy_recover_failed", error=str(exc))
                    await asyncio.sleep(0.6)
                    continue
                break
            except Exception as exc:
                last_error = str(exc)
                logger.error("playwright_launch_failed", attempt=launch_attempts, error=last_error)
                try:
                    log_playwright_failure("launch_failed", last_error or "")
                except Exception:
                    pass
                if launch_attempts < max_attempts:
                    await asyncio.sleep(1.0)
                    continue
                break
        if last_error:
            logger.error("playwright_launch_unrecoverable", error=last_error, action="aborting_batch")
            break
        logger.info("batch_complete", batch=batch)
    return results


async def _enforce_post_rate(ctx: AppContext, posts_added: int) -> None:
    """Ensure we respect configured posts/ minute cap by sleeping if needed."""
    if posts_added <= 0:
        return
    max_per_min = getattr(ctx.settings, "post_rate_max_per_minute", 0) or 0
    if max_per_min <= 0:
        return
    horizon = 60.0
    window = ctx.post_rate_window
    for _ in range(posts_added):
        while True:
            now = time.monotonic()
            while window and now - window[0] > horizon:
                window.popleft()
            if len(window) < max_per_min:
                window.append(now)
                break
            wait = horizon - (now - window[0])
            if wait <= 0:
                window.popleft()
                continue
            try:
                ctx.logger.info(
                    "post_rate_throttle",
                    wait_seconds=round(wait, 2),
                    window=len(window),
                    max_per_min=max_per_min,
                )
            except Exception:
                pass
            await asyncio.sleep(wait)

# ------------------------------------------------------------
# Data model (lightweight) - re-used from runtime package
# ------------------------------------------------------------
Post = RuntimePost


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
        total_rows = None
        try:
            if ctx.settings.sqlite_path and os.path.exists(ctx.settings.sqlite_path):
                _conn_chk = sqlite3.connect(ctx.settings.sqlite_path)
                with _conn_chk:
                    r = _conn_chk.execute("SELECT COUNT(*) FROM posts").fetchone()
                    if r:
                        total_rows = int(r[0])
        except Exception:
            total_rows = None
        logger.info("sqlite_inserted", path=ctx.settings.sqlite_path, inserted=len(posts), total_rows=total_rows)
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
        rows = []
        seen_hashes = set()
        for p in posts:
            try:
                s_norm = utils.build_search_norm(p.text, p.author, getattr(p, 'company', None), p.keyword)
            except Exception:
                s_norm = None
            try:
                chash = content_hash(p.author, p.text)
            except Exception:
                chash = None
            # Ensure batch-level uniqueness to avoid INSERT OR IGNORE skipping later rows when same text/author
            if chash and chash in seen_hashes:
                # Skip duplicate content hash within same batch to leverage unique index semantics
                continue
            if chash:
                seen_hashes.add(chash)
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
                chash,
            ))
        conn.executemany("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
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
        try:
            from datetime import datetime as _dt, timezone as _tz
            now_iso = _dt.now(_tz.utc).isoformat()
            fav_rows = []
            for p in posts:
                try:
                    threshold = 0.05
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
            try:
                mock_posts = runtime_mock.generate_posts(keyword, ctx)
                logger.info("mock_posts_generated", count=len(mock_posts))
                return mock_posts
            except Exception as exc:
                logger.error("mock_generation_failed", error=str(exc))
                return []
        return []
    finally:
        if span_ctx is not None:  # pragma: no cover
            with contextlib.suppress(Exception):
                span_ctx.__exit__(None, None, None)


async def process_job(keywords: Iterable[str], ctx: AppContext) -> int:
    """Unified job orchestration using core.orchestrator.

    Steps:
      1. Filter blacklist
      2. Fast-first cycle tuning (optional)
      3. Orchestrator dispatch (mock / sync / async)
      4. Global dedup (permalink > author+published_at > content hash)
      5. Storage (reuse legacy store_posts path for compatibility)
      6. Meta + SSE events
    """
    # 1. Filtrer blacklist
    try:
        bl_raw = getattr(ctx.settings, 'blacklisted_keywords_raw', '') or ''
        blacklist = {b.strip().lower() for b in bl_raw.split(';') if b.strip()}
    except Exception:
        blacklist = set()
    kw_list = [k for k in list(keywords) if k and k.strip().lower() not in blacklist]
    # 2. Fast-first cycle
    fast_cycle_applied = False
    original_max_posts = ctx.settings.max_posts_per_keyword
    original_scroll_steps = ctx.settings.max_scroll_steps
    if (getattr(ctx.settings, 'fast_first_cycle', False) and not getattr(ctx, '_fast_cycle_done', False)
            and not ctx.settings.playwright_mock_mode):
        with contextlib.suppress(Exception):
            ctx.settings.max_posts_per_keyword = max(5, min(12, ctx.settings.max_posts_per_keyword))
            ctx.settings.max_scroll_steps = max(2, min(3, ctx.settings.max_scroll_steps))
            fast_cycle_applied = True
            ctx.logger.debug("fast_first_cycle_applied", max_posts=ctx.settings.max_posts_per_keyword, scroll_steps=ctx.settings.max_scroll_steps)
    # 3. Orchestrateur
    mode = select_mode(ctx)
    with SCRAPE_DURATION_SECONDS.time():
        force_playwright_disabled = os.environ.get("FORCE_PLAYWRIGHT_DISABLED", "0").lower() in ("1","true","yes","on")
        if force_playwright_disabled:
            ctx.logger.warning("playwright_forced_disabled", env="FORCE_PLAYWRIGHT_DISABLED", note="no fallback mock mode available")
            posts_dicts: list[dict[str, Any]] = []
        else:
            posts_dicts = await run_orchestrator(kw_list, ctx, async_batch_callable=process_keywords_batched)
        if not posts_dicts and mode == 'async':
            ctx.logger.warning("playwright_empty_result", reason="no_posts_returned", mock_mode="disabled")
        # 4. Déduplication (extrait vers runtime.dedup)
        from scraper.runtime.dedup import deduplicate  # import local pour éviter coût si mock simple
        deduped = deduplicate(posts_dicts)
        # 5. Materialisation Post
        materialized: list[Post] = []
        for d in deduped:
            with contextlib.suppress(Exception):
                pid = d.get('id') or utils.make_post_id(d.get('keyword'), d.get('author'), d.get('published_at'))
                materialized.append(Post(
                    id=pid,
                    keyword=d.get('keyword') or '',
                    author=d.get('author') or 'Unknown',
                    author_profile=d.get('author_profile'),
                    company=d.get('company'),
                    text=d.get('text') or '',
                    language=d.get('language') or ctx.settings.default_lang,
                    published_at=d.get('published_at'),
                    collected_at=d.get('collected_at') or datetime.now(timezone.utc).isoformat(),
                    permalink=d.get('permalink'),
                    raw=d.get('raw') or {},
                ))
        from datetime import date
        today_iso = date.today().isoformat()
        if ctx.daily_post_date != today_iso:
            ctx.daily_post_date = today_iso
            ctx.daily_post_count = 0
            ctx.quota_exceeded = False
        hard_limit = getattr(ctx.settings, "daily_post_hard_limit", 0) or 0
        if hard_limit > 0:
            remaining = max(hard_limit - ctx.daily_post_count, 0)
            if remaining <= 0 and materialized:
                ctx.logger.warning("daily_quota_reached_skip", limit=hard_limit)
                materialized = []
                ctx.quota_exceeded = True
            elif 0 < remaining < len(materialized):
                ctx.logger.info(
                    "daily_quota_clamped",
                    keep=remaining,
                    drop=len(materialized) - remaining,
                    limit=hard_limit,
                )
                materialized = materialized[:remaining]
                if remaining == 0:
                    ctx.quota_exceeded = True
        stored_count = len(materialized)
        if stored_count:
            await store_posts(ctx, materialized)
            await _enforce_post_rate(ctx, stored_count)
        unknown = sum(1 for p in materialized if p.author == 'Unknown')
        SCRAPE_JOBS_TOTAL.labels(status="success").inc()
        if stored_count:
            SCRAPE_POSTS_EXTRACTED.inc(stored_count)
        with contextlib.suppress(Exception):
            today = today_iso
            if ctx.daily_post_date != today:
                ctx.daily_post_date = today
                ctx.daily_post_count = 0
                ctx.quota_exceeded = False
            ctx.daily_post_count += stored_count
            if hard_limit > 0 and ctx.daily_post_count >= hard_limit:
                ctx.quota_exceeded = True
        await update_meta(ctx, len(materialized))
        await update_meta_job_stats(ctx, len(materialized), unknown)
        if broadcast and EventType:
            with contextlib.suppress(Exception):
                await broadcast({"type": EventType.JOB_COMPLETE, "posts": len(materialized), "unknown_authors": unknown})
                with contextlib.suppress(Exception):
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
        if fast_cycle_applied:
            with contextlib.suppress(Exception):
                ctx.settings.max_posts_per_keyword = original_max_posts
                ctx.settings.max_scroll_steps = original_scroll_steps
                setattr(ctx, '_fast_cycle_done', True)
        return len(materialized)

    # ===== Unreachable Legacy Block Notice (Sprint 1 Annotation) =====
    # NOTE: The code below this return is legacy and never executes because
    # of the early `return len(materialized)` above. It will be removed or
    # refactored in Sprint 2 when extracting the runtime/pipeline modules.
    # Do NOT add new logic here; place new orchestration code before the
    # return or in dedicated future modules. (Ref: docs/ARCHITECTURE_CURRENT.md)
    # ==================================================================
    # Filter out blacklisted keywords (case-insensitive)
    try:
        bl_raw = getattr(ctx.settings, 'blacklisted_keywords_raw', '') or ''
        blacklist = {b.strip().lower() for b in bl_raw.split(';') if b.strip()}
    except Exception:
        blacklist = set()
    key_list = [k for k in list(keywords) if k and (k.strip().lower() not in blacklist)]
    all_new: list[Post] = []
    unknown_count = 0
    job_started_at = datetime.now(timezone.utc)
    job_mode = "mock" if ctx.settings.playwright_mock_mode else "async"
    result: JobResult | None = None
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
                # Option 1: explicit force disable (environment switch)
                force_disable = os.environ.get("FORCE_PLAYWRIGHT_DISABLED", "0").lower() in ("1","true","yes","on")
                if force_disable:
                    try:
                        if not ctx.settings.playwright_mock_mode:
                            setattr(ctx.settings, "playwright_mock_mode", True)
                        ctx.logger.warning("playwright_forced_disabled", reason="env_FLAG", env="FORCE_PLAYWRIGHT_DISABLED")
                        job_mode = "mock"
                    except Exception:
                        pass
                real_posts: list[Post] = []
                if not ctx.settings.playwright_mock_mode:
                    # Branch: forced sync mode
                    if should_force_sync():
                        ctx.logger.warning("playwright_force_sync_mode", reason="env_PLAYWRIGHT_FORCE_SYNC")
                        job_mode = "sync"
                        try:
                            sync_dicts = await run_sync_playwright(iterable_keywords, ctx)
                            # Convert thin dict representation into Post objects (may be empty while scaffold)
                            for d in sync_dicts:
                                try:
                                    p = Post(
                                        id=d.get('id') or utils.make_post_id(d.get('keyword','sync'), d.get('author','sync'), d.get('published_at') or datetime.now(timezone.utc).isoformat()),
                                        keyword=d.get('keyword',''),
                                        author=d.get('author','Unknown'),
                                        author_profile=None,
                                        company=d.get('company'),
                                        text=d.get('text',''),
                                        language=d.get('language', ctx.settings.default_lang),
                                        published_at=d.get('published_at'),
                                        collected_at=datetime.now(timezone.utc).isoformat(),
                                        permalink=d.get('permalink'),
                                        raw={"mode":"sync_fallback"}
                                    )
                                    real_posts.append(p)
                                except Exception:
                                    continue
                        except Exception as exc:
                            ctx.logger.error("playwright_sync_failed", error=str(exc))
                    else:
                        try:
                            real_posts = await process_keywords_batched(iterable_keywords, ctx)
                        except NotImplementedError as ne:  # belt & suspenders (should be caught deeper but we want certainty)
                            from .core.errors import log_playwright_failure
                            log_playwright_failure("not_implemented", ne)
                            if not getattr(ctx, '_logged_notimpl', False):
                                ctx.logger.error("playwright_global_not_implemented", error=str(ne))
                                setattr(ctx, '_logged_notimpl', True)
                        except Exception as exc:
                            # Collapse repeated unexpected errors into a single summarized log after threshold
                            err_sig = type(exc).__name__
                            counter = getattr(ctx, '_playwright_err_counts', {})
                            count = counter.get(err_sig, 0) + 1
                            counter[err_sig] = count
                            setattr(ctx, '_playwright_err_counts', counter)
                            if count <= 3:
                                ctx.logger.error("playwright_unexpected_error", error=str(exc), occurrence=count)
                            elif count == 4:
                                ctx.logger.error("playwright_unexpected_error_suppressed", error=err_sig, occurrences=count, note="further identical errors suppressed")
                            if count <= 3 or count % 10 == 0:
                                try:
                                    from .core.errors import log_playwright_failure
                                    log_playwright_failure("unexpected", exc)
                                except Exception:
                                    pass
                            # else: suppress to reduce noise
                # Automatic fallback to mock mode if Playwright produced nothing AND auto flag enabled
                if (not real_posts) and (not ctx.settings.playwright_mock_mode):
                    auto_flag = os.environ.get("AUTO_ENABLE_MOCK_ON_PLAYWRIGHT_FAILURE", "1").lower() in ("1","true","yes","on")
                    if auto_flag:
                        try:
                            setattr(ctx.settings, "playwright_mock_mode", True)
                            ctx.logger.warning("auto_mock_mode_enabled", reason="playwright_empty_or_failed", keywords=len(iterable_keywords))
                            job_mode = "mock"
                        except Exception:
                            pass
                        # Generate synthetic posts now that mock mode enabled
                        synthetic: list[Post] = []
                        for idx, kw in enumerate(iterable_keywords):
                            if idx > 0 and ctx.settings.per_keyword_delay_ms > 0:
                                await asyncio.sleep(ctx.settings.per_keyword_delay_ms / 1000.0)
                            try:
                                posts = await process_keyword(kw, ctx, first_keyword=(idx == 0))
                                synthetic.extend(posts)
                            except Exception as exc:  # pragma: no cover
                                ctx.logger.error("mock_generation_failed", keyword=kw, error=str(exc))
                        real_posts = synthetic
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

            result = finalize_job_result(all_new, ctx, mode=job_mode, started_at=job_started_at)
            all_new = result.posts
            unknown_count = result.unknown_authors
            job_mode = result.mode
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
                    "mode": result.mode if result else job_mode,
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
    # Launch periodic maintenance (purge + optional vacuum) in background
    async def _maintenance_task():
        interval_sec = max(300, int(ctx.settings.vacuum_interval_hours * 3600))  # guard minimum 5 min
        while True:
            try:
                if ctx.settings.purge_max_age_days > 0 and ctx.settings.sqlite_path:
                    stats = purge_and_vacuum(
                        ctx.settings.sqlite_path,
                        ctx.settings.purge_max_age_days,
                        do_vacuum=True,
                        logger=logger,
                    )
                    logger.debug("maintenance_cycle", purged=stats.get("purged"), vacuum=stats.get("vacuum"))
                else:
                    logger.debug("maintenance_skip", reason="disabled_or_missing_path")
            except Exception as exc:  # pragma: no cover
                logger.warning("maintenance_error", error=str(exc))
            await asyncio.sleep(interval_sec)

    try:
        asyncio.create_task(_maintenance_task())
    except Exception:  # pragma: no cover
        logger.warning("maintenance_task_not_started")
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
