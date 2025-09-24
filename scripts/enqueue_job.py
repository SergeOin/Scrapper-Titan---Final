"""Utility script to enqueue a scrape job into Redis.

Usage:
  python scripts/enqueue_job.py --keywords "python;ai"
If --keywords omitted, the worker will fall back to its configured SCRAPE_KEYWORDS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Sequence

from scraper.bootstrap import bootstrap


async def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Enqueue scrape job")
    parser.add_argument("--keywords", help="Mots-clés séparés par ;", default=None)
    args = parser.parse_args(argv)

    ctx = await bootstrap()
    if not ctx.redis:
        print("Redis non disponible — impossible d'enfiler le job", file=sys.stderr)
        return 1

    payload = {}
    if args.keywords:
        payload["keywords"] = [k.strip() for k in args.keywords.split(";") if k.strip()]
    await ctx.redis.lpush(ctx.settings.redis_queue_key, json.dumps(payload))
    print("Job ajouté dans la queue", payload or '{default keywords}')
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
