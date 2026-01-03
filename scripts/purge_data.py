"""Purge toutes les données de posts (SQLite, CSV) + reset meta.

Usage:
  python scripts/purge_data.py [--force]

Par défaut demande confirmation interactive.

Effets:
- SQLite: TRUNCATE logique (DELETE FROM posts)
- CSV fallback: supprime le fichier exports/fallback_posts.csv

Prerequis: même variables d'environnement que l'app (SQLITE_PATH, etc.).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import sys
from pathlib import Path as _Path

# Ensure project root on sys.path when executed directly from scripts directory
PROJECT_ROOT = _Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scraper.bootstrap import get_context


def _ask_confirm():
    answer = input("CONFIRMER la suppression de toutes les données (oui/non)? ").strip().lower()
    return answer in ("oui", "o", "yes", "y")


async def purge(ctx, force: bool):
    # SQLite
    if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
        import sqlite3
        try:
            conn = sqlite3.connect(ctx.settings.sqlite_path)
            with conn:
                # Remove posts and any flags so UI state (favoris/corbeille) starts clean
                try:
                    conn.execute("DELETE FROM post_flags")
                except Exception:
                    pass
                conn.execute("DELETE FROM posts")
                try:
                    conn.execute("DELETE FROM meta")
                except Exception:
                    pass
                try:
                    conn.execute("VACUUM")
                except Exception:
                    pass
            ctx.logger.info("purge_sqlite_ok", path=ctx.settings.sqlite_path)
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("purge_sqlite_failed", error=str(exc))
    # CSV
    csv_path = Path(ctx.settings.csv_fallback_file)
    if csv_path.exists():
        try:
            csv_path.unlink()
            ctx.logger.info("purge_csv_ok", path=str(csv_path))
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("purge_csv_failed", error=str(exc))
    ctx.logger.info("purge_complete")


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Purge all post data")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()
    if not args.force and not _ask_confirm():
        print("Annulé.")
        return
    ctx = await get_context()
    await purge(ctx, args.force)


if __name__ == "__main__":
    asyncio.run(main())
