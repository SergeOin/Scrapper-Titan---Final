"""Purge toutes les données de posts (Mongo, SQLite, CSV) + reset meta.

Usage:
  python scripts/purge_data.py [--force]

Par défaut demande confirmation interactive.

Effets:
- Mongo: supprime tous les documents des collections posts & meta (sauf autres docs non liés)
- SQLite: TRUNCATE logique (DELETE FROM posts)
- CSV fallback: supprime le fichier exports/fallback_posts.csv

Prerequis: même variables d'environnement que l'app (MONGO_URI, SQLITE_PATH, etc.).
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
    # Mongo
    if ctx.mongo_client:
        try:
            db = ctx.mongo_client[ctx.settings.mongo_db]
            await db[ctx.settings.mongo_collection_posts].delete_many({})
            await db[ctx.settings.mongo_collection_meta].delete_many({"_id": "global"})
            ctx.logger.info("purge_mongo_ok")
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("purge_mongo_failed", error=str(exc))
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
            ctx.logger.info("purge_csv_ok", file=str(csv_path))
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("purge_csv_failed", error=str(exc))

    print("Purge terminée.")


async def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Ne pas demander de confirmation interactive")
    args = p.parse_args()
    ctx = await get_context()
    if not args.force and not _ask_confirm():
        print("Abandon.")
        return
    await purge(ctx, force=args.force)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
