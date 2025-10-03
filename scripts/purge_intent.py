"""Purge posts by intent label.

Usage (PowerShell):
  python scripts/purge_intent.py --intent recherche_profil

Options:
  --intent <value>   Intent to delete (recherche_profil|autre)
  --dry-run          Only count matching posts, do not delete
  --mongo-only       Do not touch SQLite fallback
  --sqlite-only      Skip Mongo

The intent field is stored directly in Mongo documents but only inside raw_json for SQLite.
For SQLite we perform a LIKE match (best-effort) on raw_json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from scraper.bootstrap import get_context


async def purge_mongo(ctx, intent: str, dry: bool) -> int:
    if not ctx.mongo_client:
        return 0
    coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
    query = {"intent": intent}
    if dry:
        return await coll.count_documents(query)
    res = await coll.delete_many(query)
    return getattr(res, "deleted_count", 0) or 0


def purge_sqlite(ctx, intent: str, dry: bool) -> int:
    path = ctx.settings.sqlite_path
    if not path or not Path(path).exists():
        return 0
    conn = sqlite3.connect(path)
    with conn:
        # intent is inside raw_json -> LIKE based filter
        like_pattern = f'%"intent": "{intent}"%'
        if dry:
            cur = conn.execute("SELECT COUNT(*) FROM posts WHERE raw_json LIKE ?", (like_pattern,))
            return int(cur.fetchone()[0] or 0)
        cur = conn.execute("SELECT id FROM posts WHERE raw_json LIKE ?", (like_pattern,))
        ids = [r[0] for r in cur.fetchall()]
        if not ids:
            return 0
        # Delete rows and associated flags
        placeholders = ",".join(["?"] * len(ids))
        conn.execute(f"DELETE FROM posts WHERE id IN ({placeholders})", ids)
        try:
            conn.execute(f"DELETE FROM post_flags WHERE post_id IN ({placeholders})", ids)
        except Exception:
            pass
        return len(ids)


async def main():
    parser = argparse.ArgumentParser(description="Purge posts by intent")
    parser.add_argument("--intent", required=True, choices=["recherche_profil", "autre"], help="Intent label to purge")
    parser.add_argument("--dry-run", action="store_true", help="Only count matches")
    parser.add_argument("--mongo-only", action="store_true")
    parser.add_argument("--sqlite-only", action="store_true")
    args = parser.parse_args()

    ctx = await get_context()
    deleted_mongo = 0
    deleted_sqlite = 0
    if not args.sqlite_only:
        deleted_mongo = await purge_mongo(ctx, args.intent, args.dry_run)
    if not args.mongo_only:
        deleted_sqlite = purge_sqlite(ctx, args.intent, args.dry_run)
    result = {
        "intent": args.intent,
        "dry_run": args.dry_run,
        "deleted_mongo" if not args.sqlite_only else "count_mongo": deleted_mongo,
        "deleted_sqlite" if not args.mongo_only else "count_sqlite": deleted_sqlite,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
