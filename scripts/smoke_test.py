"""Smoke test for the LinkedIn scraper project.

Goals:
- Run in mock mode (PLAYWRIGHT_MOCK_MODE=1) so no real browser access required.
- Force a scrape job for a small keyword list.
- Print summary: number of posts stored (Mongo or SQLite fallback), last_run, unknown authors metrics.

Usage (PowerShell):
  $Env:PLAYWRIGHT_MOCK_MODE='1'
  $Env:SCRAPE_KEYWORDS='python;data'
  python scripts/smoke_test.py

Exit codes:
  0 success (>=1 post extracted in mock)
  2 run ok but 0 posts (unexpected in mock)
  3 unhandled exception
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.bootstrap import get_context  # noqa: E402
from scraper.worker import process_job  # noqa: E402


async def _run():
    ctx = await get_context()
    ctx.logger.info("smoke_test_start", keywords=ctx.settings.keywords, mock=ctx.settings.playwright_mock_mode)
    try:
        await process_job(ctx.settings.keywords, ctx)
    except Exception as exc:  # pragma: no cover - just in case
        ctx.logger.error("smoke_test_failed", error=str(exc))
        return 3

    # Fetch meta
    last_run = None
    posts_count = None
    unknown = None
    if ctx.mongo_client:
        try:
            mcoll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_meta]
            doc = await mcoll.find_one({"_id": "global"})
            if doc:
                last_run = doc.get("last_run")
                posts_count = doc.get("posts_count")
                unknown = doc.get("last_job_unknown_authors")
        except Exception as exc:
            ctx.logger.warning("smoke_meta_fail", error=str(exc))
    # SQLite fallback simple count
    if posts_count is None and ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
        import sqlite3
        try:
            conn = sqlite3.connect(ctx.settings.sqlite_path)
            with conn:
                c = conn.execute("SELECT COUNT(*) FROM posts").fetchone()
                if c:
                    posts_count = c[0]
        except Exception:
            pass

    ctx.logger.info("smoke_test_summary", last_run=last_run, posts=posts_count, unknown_authors=unknown)
    if posts_count and posts_count > 0:
        return 0
    return 2


def main():
    code = asyncio.run(_run())
    if code == 0:
        print("SMOKE TEST OK")
    elif code == 2:
        print("SMOKE TEST COMPLETED BUT NO POSTS (unexpected in mock mode)")
    else:
        print("SMOKE TEST FAILED")
    raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover
    main()
