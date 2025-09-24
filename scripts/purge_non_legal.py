from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

from scraper.bootstrap import get_context


async def main():
    parser = argparse.ArgumentParser(description="Purge SQLite posts that are not legal keywords and/or not French")
    parser.add_argument("--keep-nonfr", action="store_true", help="Do NOT purge non-French posts (keep them)")
    args = parser.parse_args()

    ctx = await get_context()
    sqlite_path = Path(ctx.settings.sqlite_path)
    if not sqlite_path.exists():
        print({"status": "no_sqlite", "path": str(sqlite_path)})
        return

    allowed_keywords = [k.strip().lower() for k in ctx.settings.keywords if k.strip()]
    if not allowed_keywords:
        print({"status": "no_allowed_keywords", "hint": "Set SCRAPE_KEYWORDS to your legal list"})
        return

    removed_non_legal = 0
    removed_non_fr = 0
    with sqlite3.connect(str(sqlite_path)) as conn:
        conn.row_factory = sqlite3.Row
        # 1) Purge non-legal (keyword not in allowed set)
        placeholders = ",".join(["?"] * len(allowed_keywords))
        # Count
        cur = conn.execute(f"SELECT COUNT(*) FROM posts WHERE lower(keyword) NOT IN ({placeholders})", allowed_keywords)
        to_del = cur.fetchone()[0]
        if to_del:
            conn.execute(f"DELETE FROM posts WHERE lower(keyword) NOT IN ({placeholders})", allowed_keywords)
            removed_non_legal = to_del

        # 2) Purge non-French (unless kept)
        if not args.keep_nonfr:
            cur = conn.execute("SELECT COUNT(*) FROM posts WHERE COALESCE(lower(language),'') <> 'fr'")
            to_del_fr = cur.fetchone()[0]
            if to_del_fr:
                conn.execute("DELETE FROM posts WHERE COALESCE(lower(language),'') <> 'fr'")
                removed_non_fr = to_del_fr

        conn.commit()

    print({
        "status": "ok",
        "sqlite": str(sqlite_path),
        "removed_non_legal": removed_non_legal,
        "removed_non_fr": removed_non_fr,
        "kept_language_filter": args.keep_nonfr,
        "allowed_keywords_count": len(allowed_keywords),
    })


if __name__ == "__main__":
    asyncio.run(main())
