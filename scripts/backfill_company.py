"""Backfill missing company field for legacy posts in SQLite.

Heuristics reuse the server.routes _derive_company function to maintain
consistency with display logic. This script is idempotent and only updates
rows where company IS NULL or empty.

Usage (PowerShell):
  python -m scripts.backfill_company
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from scraper.bootstrap import get_context
from server.routes import _derive_company as derive_company  # type: ignore


def main() -> None:
    import asyncio
    asyncio.run(run())


async def run():
    ctx = await get_context()
    path = ctx.settings.sqlite_path
    if not path or not Path(path).exists():
        print("[backfill_company] Aucune base SQLite trouvée.")
        return
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    updated = 0
    scanned = 0
    with conn:
        rows = conn.execute(
            "SELECT id, author, author_profile, text, company FROM posts WHERE (company IS NULL OR TRIM(company)='')"
        ).fetchall()
        for r in rows:
            scanned += 1
            author = r["author"] or ""
            prof = r["author_profile"] or ""
            text = r["text"] or ""
            comp = derive_company(author, prof, text)
            if comp:
                conn.execute("UPDATE posts SET company=? WHERE id=?", (comp, r["id"]))
                updated += 1
    print(f"[backfill_company] Terminé. Lignes scannées={scanned} mises_a_jour={updated}")


if __name__ == "__main__":  # pragma: no cover
    main()
