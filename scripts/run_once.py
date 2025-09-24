"""Run a one-off scraping job without Redis queue.

Usage:
  python scripts/run_once.py --keywords "python;ai"

If --keywords is omitted, uses SCRAPE_KEYWORDS from settings.
"""
from __future__ import annotations

import argparse
import asyncio
import os, sys

# Ensure project root on path for direct execution
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.bootstrap import get_context
from scraper.worker import process_job


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--keywords", help="Semicolon separated keyword list", default=None)
    return p.parse_args()


async def main():
    args = parse_args()
    ctx = await get_context()
    if not ctx.settings.scraping_enabled:
        print("Scraping disabled by SCRAPING_ENABLED=0")
        return
    keywords = ctx.settings.keywords
    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(";") if k.strip()]
    count = await process_job(keywords, ctx)
    print(f"Extracted {count} posts (keywords={keywords})")


if __name__ == "__main__":
    asyncio.run(main())
