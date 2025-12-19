"""Export posts to a CSV file from SQLite.

Usage:
  python scripts/export_csv.py --out exports/export_posts.csv --limit 500

Environment is read via existing Settings (scraper.bootstrap.Settings)

Columns: id,keyword,author,company,text,language,published_at,collected_at,permalink
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sqlite3
from pathlib import Path
from typing import Any

from scraper.bootstrap import get_context

FIELDS = ["_id","keyword","author","company","text","language","published_at","collected_at","permalink"]

async def gather_posts(limit: int) -> list[dict[str, Any]]:
    ctx = await get_context()
    rows: list[dict[str, Any]] = []
    # SQLite storage
    try:
        if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
            conn = sqlite3.connect(ctx.settings.sqlite_path)
            conn.row_factory = sqlite3.Row
            with conn:
                q = "SELECT id as _id, keyword, author, company, text, language, published_at, collected_at, permalink FROM posts ORDER BY collected_at DESC LIMIT ?"
                for r in conn.execute(q, (limit,)):
                    rows.append(dict(r))
    except Exception as exc:  # pragma: no cover
        ctx.logger.error("sqlite_export_failed", error=str(exc))
    return rows

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="exports/export_posts.csv", help="Output CSV path")
    parser.add_argument("--limit", type=int, default=1000, help="Max rows to export")
    args = parser.parse_args()
    rows = await gather_posts(args.limit)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for r in rows:
            w.writerow([r.get(f) or "" for f in FIELDS])
    print(f"Exported {len(rows)} rows to {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
