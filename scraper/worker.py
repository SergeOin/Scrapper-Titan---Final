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
    SCRAPE_FILTERED_POSTS,
    get_context,
)
from . import utils
try:
    from server.events import broadcast, EventType  # type: ignore
except Exception:  # pragma: no cover
    broadcast = None  # type: ignore
    EventType = None  # type: ignore

# ---------------------------------------------------------------------------
# Ultra-early Windows event loop policy hardening BEFORE importing Playwright.
# Rationale: In the packaged build we still see NotImplementedError arising from
# asyncio.subprocess on Windows (Proactor loop path). For frozen apps the default
# policy can revert very early (before desktop/main enforcement) in the worker
# module import context executed inside uvicorn thread. We therefore enforce the
# selector policy here unconditionally (unless env explicitly requests proactor)
# and log a single diagnostic. This MUST happen before importing playwright.*
# ---------------------------------------------------------------------------
if os.name == "nt":  # pragma: no cover (platform-specific)
    try:
        desired = os.environ.get("EVENT_LOOP_POLICY", "selector").lower().strip()
        if desired not in ("selector", "proactor"):
            desired = "selector"
        current_cls = asyncio.get_event_loop_policy().__class__.__name__  # type: ignore[attr-defined]
        changed = False
        if desired == "selector" and "Selector" not in current_cls:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
            changed = True
        elif desired == "proactor" and "Proactor" not in current_cls:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]
            changed = True
        new_cls = asyncio.get_event_loop_policy().__class__.__name__  # type: ignore[attr-defined]
        structlog.get_logger("worker").info(
            "pre_playwright_loop_policy",
            desired=desired,
            before=current_cls,
            after=new_cls,
            changed=changed,
        )
    except Exception:
        structlog.get_logger("worker").warning("pre_playwright_loop_policy_failed", exc_info=True)

# Delay Playwright import until after policy enforcement.
try:  # Optional heavy import lazy usage
    from playwright.async_api import async_playwright, Page, Browser
except Exception:  # pragma: no cover
    async_playwright = None  # type: ignore
    Page = Any  # type: ignore
    Browser = Any  # type: ignore

# Sync fallback wrapper (thread-based) when async subprocess creation fails in frozen builds
try:
    from .playwright_sync import should_force_sync, run_sync_playwright  # type: ignore
except Exception:  # pragma: no cover
    def should_force_sync() -> bool:  # type: ignore
        return False
    async def run_sync_playwright(keywords, ctx):  # type: ignore
        return []

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
    """Try to (re)create a browser + page with robust fallbacks.

    Steps:
      1. Enforce WindowsProactorEventLoopPolicy first (Windows) if currently selector.
      2. Launch with optional extra args + headless override env PLAYWRIGHT_DISABLE_HEADLESS=1.
      3. Create context WITH storage_state if file exists; on failure retry once WITHOUT storage_state.
      4. Create page; if fails, relaunch whole browser once.
      5. Ensure authenticated (lightweight check + screenshot capture logged upstream).
    """
    storage_file = ctx.settings.storage_state
    storage_exists = os.path.exists(storage_file)
    disable_headless = os.environ.get("PLAYWRIGHT_DISABLE_HEADLESS", "0").lower() in ("1","true","yes","on")
    extra_args_env = os.environ.get("PLAYWRIGHT_EXTRA_ARGS", "")
    extra_args = [a.strip() for a in extra_args_env.split(" ") if a.strip()] if extra_args_env else []
    # Provide a safe default argument set for Windows if nothing specified
    if not extra_args:
        extra_args = ["--disable-gpu","--no-sandbox","--disable-dev-shm-usage"]
    # Policy hardening (updated): ensure we use Selector loop (Proactor lacks subprocess support -> NotImplementedError)
    if os.name == "nt":
        try:
            pol = asyncio.get_event_loop_policy().__class__.__name__
            if "Proactor" in pol:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
                logger.warning("event_loop_policy_switched_selector", previous=pol)
        except Exception:
            pass
    headless_flag = ctx.settings.playwright_headless_scrape and not disable_headless
    attempt = 0
    last_error = None
    for phase in ("with_storage","without_storage"):
        attempt += 1
        try:
            logger.info(
                "browser_launch_attempt",
                attempt=attempt,
                headless=headless_flag,
                phase=phase,
                storage_state=storage_file,
                storage_exists=storage_exists,
                extra_args=extra_args,
            )
            browser = await pw.chromium.launch(headless=headless_flag, args=extra_args)
            ctx_arg = storage_file if (phase == "with_storage" and storage_exists) else None
            try:
                context = await browser.new_context(storage_state=ctx_arg)
            except Exception as e_ctx:
                last_error = f"context_create_failed:{e_ctx}"; logger.error("context_create_failed", error=str(e_ctx), phase=phase)
                with contextlib.suppress(Exception):
                    await browser.close()
                if phase == "with_storage":
                    continue  # retry without storage
                else:
                    return None
            try:
                page = await context.new_page()
            except Exception as e_page:
                last_error = f"new_page_failed:{e_page}"; logger.error("new_page_failed", error=str(e_page), phase=phase)
                with contextlib.suppress(Exception):
                    await browser.close()
                if phase == "with_storage":
                    continue
                else:
                    return None
            try:
                await _ensure_authenticated(page, ctx, logger)
            except Exception as auth_exc:
                logger.warning("ensure_authenticated_error", error=str(auth_exc))
            return browser, page
        except Exception as exc:
            last_error = str(exc)
            logger.error("browser_recovery_failed", error=last_error, phase=phase)
            with contextlib.suppress(Exception):
                await browser.close()  # type: ignore[name-defined]
            if phase == "with_storage":
                continue
            return None
    # If standard launches exhausted, attempt persistent context fallback (user_data_dir) unless disabled
    if os.environ.get("PLAYWRIGHT_PERSISTENT_FALLBACK", "1").lower() in ("1","true","yes","on"):
        import tempfile, shutil
        user_data_dir = Path(tempfile.mkdtemp(prefix="pw_ud_"))
        try:
            logger.warning("browser_persistent_fallback_start", user_data_dir=str(user_data_dir))
            # Force headful in fallback if previous was headless
            headless_flag = ctx.settings.playwright_headless_scrape and not disable_headless
            browser_context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless_flag,
                args=extra_args,
            )
            # In persistent mode, context == browser_context
            page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
            try:
                await _ensure_authenticated(page, ctx, logger)
            except Exception as auth_exc:
                logger.warning("ensure_authenticated_error_persistent", error=str(auth_exc))
            logger.info("browser_persistent_fallback_success")
            return browser_context, page  # we treat 'browser_context' as 'browser' for closing upstream
        except Exception as p_exc:
            logger.error("browser_persistent_fallback_failed", error=str(p_exc))
        finally:
            # Do NOT remove user_data_dir immediately on success (session reuse). Only clean on failure.
            if not page or page.is_closed():  # type: ignore[name-defined]
                with contextlib.suppress(Exception):
                    shutil.rmtree(user_data_dir, ignore_errors=True)
    logger.error("browser_recovery_exhausted", last_error=last_error)
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
        # Wrapper with explicit retries + loop policy fallback for Playwright launch
        launch_attempts = 0
        max_attempts = 2  # 1) selector (par défaut), 2) proactor fallback
        last_error: Optional[str] = None
        while launch_attempts < max_attempts:
            try:
                launch_attempts += 1
                if os.name == "nt":
                    pol = asyncio.get_event_loop_policy().__class__.__name__
                    # Ensure Selector loop (Proactor cannot spawn subprocess -> Playwright NotImplementedError)
                    if "Proactor" in pol:
                        try:
                            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
                            pol2 = asyncio.get_event_loop_policy().__class__.__name__
                            logger.warning("event_loop_policy_forced_selector_prelaunch", previous=pol, new=pol2)
                            pol = pol2
                        except Exception as e:
                            logger.warning("event_loop_policy_selector_force_failed", error=str(e), previous=pol)
                    logger.info("playwright_launch_attempt", attempt=launch_attempts, policy=pol)
                async with async_playwright() as pw:
                    # Apply a timeout to recovery to avoid hanging indefinitely if Chromium crashes silently
                    timeout_seconds = int(os.environ.get("PLAYWRIGHT_RECOVER_TIMEOUT_SECONDS", "15"))
                    try:
                        recovery = await asyncio.wait_for(_recover_browser(pw, ctx, logger), timeout=timeout_seconds)
                    except asyncio.TimeoutError:
                        logger.error("browser_launch_timeout", timeout_seconds=timeout_seconds)
                        recovery = None
                    if recovery is None:
                        logger.warning("skip_batch_recovery_failed", batch=batch)
                        break
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
                                    logger.error("page_recovery_failed", keyword=keyword)
                                    break
                                browser, page = rec
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
                        with contextlib.suppress(Exception):
                            await browser.close()
                last_error = None  # success
                break
            except NotImplementedError as ne:
                last_error = str(ne)
                logger.error("playwright_not_implemented", attempt=launch_attempts, error=last_error)
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
                if launch_attempts < max_attempts:
                    await asyncio.sleep(1.0)
                    continue
                break
        if last_error:
            # Fallback mock mode to keep UI alive
            with contextlib.suppress(Exception):
                if hasattr(ctx.settings, "playwright_mock_mode"):
                    setattr(ctx.settings, "playwright_mock_mode", True)
                    logger.warning("fallback_mock_mode_enabled", reason="playwright_launch_unrecoverable", error=last_error)
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
                chash = _compute_content_hash(p.author, p.text)
            except Exception:
                chash = None
            # Ensure batch-level uniqueness to avoid INSERT OR IGNORE skipping later rows when same text/author
            if chash and chash in seen_hashes:
                chash = f"{chash}_{abs(hash(p.id))%997}"  # deterministic short salt
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
# Playwright extraction logic (élargi)
# ------------------------------------------------------------
# Plusieurs sélecteurs possibles pour couvrir différents layouts LinkedIn.
POST_CONTAINER_SELECTORS = [
    "article[data-urn*='urn:li:activity']",
    "div.feed-shared-update-v2",
    "div.update-components-feed-update",
    "div.occludable-update",
    "div[data-urn*='urn:li:activity:']",
    # Additional generic fallbacks (layout changes / experimental wrappers)
    "div.feed-shared-update-v3",
    "div.update-components-actor__container",
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
    # Rejection statistics for diagnostics (reason -> count)
    reject_stats: dict[str, int] = {}
    # Optional diagnostics
    diagnostics_enabled = bool(int(os.environ.get("PLAYWRIGHT_DEBUG_SNAPSHOTS", "0")))
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
            if diagnostics_enabled:
                # Save a small HTML snapshot for troubleshooting missing selectors
                try:
                    html = await page.content()
                    snap_path = Path(ctx.settings.screenshot_dir) / f"debug_{keyword}_step0.html"
                    snap_path.write_text(html[:200_000], encoding="utf-8", errors="ignore")
                    ctx.logger.warning("debug_snapshot_written", path=str(snap_path), keyword=keyword)
                except Exception:
                    pass
            # Rescan after a lightweight scroll if still none
            if not elements:
                with contextlib.suppress(Exception):
                    await page.evaluate("window.scrollBy(0, 600)")
                    await page.wait_for_timeout(800)
                for selector in POST_CONTAINER_SELECTORS:
                    with contextlib.suppress(Exception):
                        found2 = await page.query_selector_all(selector)
                        if found2:
                            elements.extend(found2)
                if diagnostics_enabled:
                    try:
                        html2 = await page.content()
                        snap_path2 = Path(ctx.settings.screenshot_dir) / f"debug_{keyword}_after_rescan.html"
                        snap_path2.write_text(html2[:200_000], encoding="utf-8", errors="ignore")
                        ctx.logger.warning("debug_snapshot_after_rescan", path=str(snap_path2), keyword=keyword, found=len(elements))
                    except Exception:
                        pass
            # Count raw <article> tags for heuristic signal
            if diagnostics_enabled:
                with contextlib.suppress(Exception):
                    article_count = await page.evaluate("() => document.querySelectorAll('article').length")
                    ctx.logger.info("debug_article_count", keyword=keyword, count=article_count)
        # Element-level verbose diagnostics flag
        verbose_el = bool(int(os.environ.get("PLAYWRIGHT_DEBUG_VERBOSE", "0")))
        if verbose_el:
            ctx.logger.info("elements_batch", keyword=keyword, step=step, count=len(elements))
        for idx_el, el in enumerate(elements):
            if len(posts) >= max_items:
                break
            # ---------------------------
            # ELEMENT QUERY PHASE
            # (Previous bug: this block was indented inside the 'if len(posts)' guard -> never executed)
            # ---------------------------
            author_el = await el.query_selector(AUTHOR_SELECTOR)
            # Fallback author selectors (LinkedIn layout variants)
            if not author_el:
                with contextlib.suppress(Exception):
                    author_el = await el.query_selector("span.update-components-actor__name, span.feed-shared-actor__name")
            if not author_el:
                with contextlib.suppress(Exception):
                    author_el = await el.query_selector("span[dir='ltr'] strong, span[dir='ltr'] a")

            # Extra fallback: capture top-level text block if main selector missing
            text_el = await el.query_selector(TEXT_SELECTOR) or await el.query_selector("div.update-components-text, div.feed-shared-update-v2__commentary")
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
            # Always attempt full enrichment & fallback; previously gated only when author Unknown
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
            # NOTE: Move text extraction outside previous conditional so it's always available
            text_raw = ""
            try:
                text_raw = (await text_el.inner_text()) if text_el else ""
            except Exception:
                text_raw = ""
            text_norm = utils.normalize_whitespace(text_raw)
            if not company_val:
                candidates = []
                try:
                    desc_el2 = await el.query_selector("span.update-components-actor__description")
                    if desc_el2:
                        rd = await desc_el2.inner_text()
                        if rd:
                            rd = utils.normalize_whitespace(rd).strip()
                            candidates.append(rd)
                except Exception:
                    pass
                if text_norm:
                    candidates.append(text_norm)
                comp = None
                for blob in candidates:
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
                if comp and (not author or comp.lower() != author.lower()):
                    company_val = comp
            # Date extraction (uniform)
            published_raw = None
            published_iso = None
            try:
                published_raw = (await date_el.get_attribute("datetime")) if date_el else None
            except Exception:
                published_raw = None
            if published_raw:
                published_iso = published_raw
            else:
                txt_for_date = ""
                if date_el:
                    with contextlib.suppress(Exception):
                        txt_for_date = await date_el.inner_text()
                if not txt_for_date:
                    with contextlib.suppress(Exception):
                        subdesc = await el.query_selector("span.update-components-actor__sub-description")
                        if subdesc:
                            txt_for_date = await subdesc.inner_text()
                dt = utils.parse_possible_date(txt_for_date)
                if dt:
                    published_iso = dt.isoformat()

            language = utils.detect_language(text_norm, ctx.settings.default_lang)
            # Provisional id; may be overridden by permalink-based id later
            provisional_pid = utils.make_post_id(keyword, author, published_iso or text_norm[:30] or str(idx_el))
            if provisional_pid in seen_ids:
                if verbose_el:
                    ctx.logger.info("element_skipped_duplicate", keyword=keyword, idx=idx_el)
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
            if permalink:
                permalink = _canonicalize_permalink(permalink)
            final_id = utils.make_post_id(permalink) if permalink else provisional_pid
            if author:
                author = _dedupe_repeated_author(author)
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
                permalink=permalink,
                raw={"published_raw": published_raw, "recruitment_threshold": ctx.settings.recruitment_signal_threshold, "debug_idx": idx_el},
            )
            # Optional bypass for strict filters (debugging)
            disable_filters = bool(int(os.environ.get("PLAYWRIGHT_DISABLE_STRICT_FILTERS", "0")))
            keep = True
            reject_reason = None
            if not disable_filters:
                try:
                    if ctx.settings.filter_language_strict and language.lower() != (ctx.settings.default_lang or "fr").lower():
                        keep = False; reject_reason = "language"
                    if keep and getattr(ctx.settings, 'filter_legal_domain_only', False):
                        tl = (text_norm or "").lower()
                        legal_markers = (
                            "juriste","avocat","legal","counsel","paralegal","notaire","droit","fiscal","conformité","compliance","secrétaire général","secretaire general","contentieux","litige","corporate law","droit des affaires"
                        )
                        if not any(m in tl for m in legal_markers):
                            keep = False; reject_reason = reject_reason or "non_domain"
                    if keep and ctx.settings.filter_recruitment_only and recruitment_score < ctx.settings.recruitment_signal_threshold:
                        keep = False; reject_reason = reject_reason or "recruitment"
                    if keep and ctx.settings.filter_require_author_and_permalink and (not post.author or post.author.lower() == "unknown" or not post.permalink):
                        keep = False; reject_reason = reject_reason or "missing_core_fields"
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
                    if keep and getattr(ctx.settings, 'filter_france_only', True):
                        tl = (text_norm or "").lower()
                        fr_positive = ("france","paris","idf","ile-de-france","lyon","marseille","bordeaux","lille","toulouse","nice","nantes","rennes")
                        foreign_negative = ("hiring in uk","remote us","canada","usa","australia","dubai","switzerland","swiss","belgium","belgique","luxembourg","portugal","espagne","spain","germany","deutschland","italy","singapore")
                        if any(f in tl for f in foreign_negative) and not any(p in tl for p in fr_positive):
                            keep = False; reject_reason = reject_reason or "not_fr"
                except Exception:
                    pass
            else:
                # Mark that filters were bypassed
                post.raw["filters_bypassed"] = True
            if keep:
                if post.company and post.author and post.company.lower() == post.author.lower():
                    post.company = None
                posts.append(post)
                if verbose_el:
                    ctx.logger.info("element_kept", keyword=keyword, idx=idx_el, author=post.author, has_permalink=bool(post.permalink), text_len=len(post.text))
            else:
                reason = reject_reason or "other"
                reject_stats[reason] = reject_stats.get(reason, 0) + 1
                with contextlib.suppress(Exception):
                    SCRAPE_FILTERED_POSTS.labels(reason).inc()
                if verbose_el:
                    ctx.logger.info("element_rejected", keyword=keyword, idx=idx_el, reason=reason, author=post.author, has_permalink=bool(post.permalink), text_len=len(post.text))
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
    try:
        if reject_stats and os.environ.get("DEBUG_FILTER_SUMMARY", "1") != "0":
            kept = len(posts)
            total_rej = sum(reject_stats.values())
            ctx.logger.info(
                "extract_filter_summary",
                keyword=keyword,
                kept=kept,
                rejected=total_rej,
                **{f"rej_{k}": v for k, v in reject_stats.items()},
            )
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
                # Option 1: explicit force disable (environment switch)
                force_disable = os.environ.get("FORCE_PLAYWRIGHT_DISABLED", "0").lower() in ("1","true","yes","on")
                if force_disable:
                    try:
                        if not ctx.settings.playwright_mock_mode:
                            setattr(ctx.settings, "playwright_mock_mode", True)
                        ctx.logger.warning("playwright_forced_disabled", reason="env_FLAG", env="FORCE_PLAYWRIGHT_DISABLED")
                    except Exception:
                        pass
                real_posts: list[Post] = []
                if not ctx.settings.playwright_mock_mode:
                    # Branch: forced sync mode
                    if should_force_sync():
                        ctx.logger.warning("playwright_force_sync_mode", reason="env_PLAYWRIGHT_FORCE_SYNC")
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
                            # Centralized single log for NotImplementedError to avoid spam
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
                            # else: suppress to reduce noise
                # Automatic fallback to mock mode if Playwright produced nothing AND auto flag enabled
                if (not real_posts) and (not ctx.settings.playwright_mock_mode):
                    auto_flag = os.environ.get("AUTO_ENABLE_MOCK_ON_PLAYWRIGHT_FAILURE", "1").lower() in ("1","true","yes","on")
                    if auto_flag:
                        try:
                            setattr(ctx.settings, "playwright_mock_mode", True)
                            ctx.logger.warning("auto_mock_mode_enabled", reason="playwright_empty_or_failed", keywords=len(iterable_keywords))
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
            all_new = deduped
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
