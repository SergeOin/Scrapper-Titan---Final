#!/usr/bin/env python
"""CLI script to recompute recruitment_score across storage backends.

Usage:
  python scripts/recompute_recruitment_scores.py [--force]

--force : overwrite existing non-null scores.

The script will attempt Mongo (if configured), then SQLite fallback, then CSV fallback.
Logs are structured via structlog.
"""
from __future__ import annotations

import argparse
import asyncio
import structlog
import sys, os

# Ensure project root on sys.path when script executed directly (Windows PowerShell may omit)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.maintenance import recompute_all


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Recompute recruitment_score for stored posts")
    p.add_argument("--force", action="store_true", help="Overwrite existing scores")
    return p.parse_args()


async def _main():
    args = parse_args()
    logger = structlog.get_logger().bind(script="recompute_recruitment_scores")
    logger.info("start", force=args.force)
    await recompute_all(force=args.force)
    logger.info("end")


if __name__ == "__main__":
    asyncio.run(_main())
