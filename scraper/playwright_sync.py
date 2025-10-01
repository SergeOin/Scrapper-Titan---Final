"""Synchronous Playwright fallback layer executed in a worker thread.

This bypasses asyncio.create_subprocess_exec limitations observed in the
frozen Windows build by moving browser lifecycle to the sync API inside
its own thread. The async code awaits results via run_in_executor.

Environment flag: PLAYWRIGHT_FORCE_SYNC=1 to force usage.
"""
from __future__ import annotations

from typing import Any, List
import concurrent.futures
import threading
import os
import time

_executor: concurrent.futures.ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _ensure_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw-sync")
    return _executor


def _run_sync_task(func, *args, **kwargs):  # noqa: D401
    return func(*args, **kwargs)


def should_force_sync() -> bool:
    return os.environ.get("PLAYWRIGHT_FORCE_SYNC", "0").lower() in ("1","true","yes","on")


def extract_keywords_sync(keywords: List[str], settings, logger) -> list[dict[str, Any]]:
    """Blocking sync extraction of keywords returning list of dict posts (minimal subset).

    This is intentionally lightweight: it only verifies Chromium can launch
    and returns empty list (real extraction logic could be ported later).
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover
        logger.error("playwright_sync_import_failed", error=str(exc))
        return []
    posts: list[dict[str, Any]] = []
    try:
        start = time.time()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=getattr(settings, 'playwright_headless_scrape', True))
            context = browser.new_context()
            page = context.new_page()
            for kw in keywords:
                try:
                    page.goto(f"https://www.linkedin.com/search/results/content/?keywords={kw}", timeout=getattr(settings,'navigation_timeout_ms',15000))
                except Exception as nav_exc:
                    logger.warning("sync_nav_failed", keyword=kw, error=str(nav_exc))
            try:
                browser.close()
            except Exception:
                pass
        elapsed = round(time.time() - start, 2)
        logger.info("playwright_sync_cycle", keywords=len(keywords), elapsed=elapsed)
    except Exception as exc:  # pragma: no cover
        logger.error("playwright_sync_cycle_failed", error=str(exc))
    return posts


async def run_sync_playwright(keywords: list[str], ctx) -> list[dict[str, Any]]:
    """Async wrapper executing sync extraction in dedicated thread."""
    import asyncio
    loop = asyncio.get_running_loop()
    ex = _ensure_executor()
    return await loop.run_in_executor(ex, _run_sync_task, extract_keywords_sync, keywords, ctx.settings, ctx.logger)
