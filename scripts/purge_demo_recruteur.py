"""Purge uniquement les posts de démonstration `demo_recruteur`.

Usage:
  python scripts/purge_demo_recruteur.py [--force]

Effets:
- Mongo: delete_many({keyword: 'demo_recruteur'})
- SQLite: DELETE FROM posts WHERE keyword='demo_recruteur'
- CSV fallback: réécrit le CSV sans ces lignes (si fichier présent)

Prerequis: même variables d'environnement que l'app (MONGO_URI, SQLITE_PATH, etc.).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import csv
import sys
from pathlib import Path as _Path

# Ensure project root on sys.path when executed directly from scripts directory
PROJECT_ROOT = _Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scraper.bootstrap import get_context


def _ask_confirm():
    answer = input("Confirmer la suppression des posts 'demo_recruteur' (oui/non)? ").strip().lower()
    return answer in ("oui", "o", "yes", "y")


async def purge_demo(ctx, force: bool):
    target_kw = "demo_recruteur"
    # Mongo
    if ctx.mongo_client:
        try:
            db = ctx.mongo_client[ctx.settings.mongo_db]
            res = await db[ctx.settings.mongo_collection_posts].delete_many({"keyword": target_kw})
            ctx.logger.info("purge_demo_mongo_ok", deleted=res.deleted_count)
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("purge_demo_mongo_failed", error=str(exc))
    # SQLite
    if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
        import sqlite3
        try:
            conn = sqlite3.connect(ctx.settings.sqlite_path)
            with conn:
                cur = conn.execute("DELETE FROM posts WHERE keyword=?", (target_kw,))
                deleted = cur.rowcount if cur.rowcount is not None else 0
            ctx.logger.info("purge_demo_sqlite_ok", path=ctx.settings.sqlite_path, deleted=deleted)
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("purge_demo_sqlite_failed", error=str(exc))
    # CSV: filter rewrite
    csv_path = Path(ctx.settings.csv_fallback_file)
    if csv_path.exists():
        try:
            tmp_path = csv_path.with_suffix(".tmp.csv")
            kept = 0
            with csv_path.open("r", encoding="utf-8", newline="") as f_in, tmp_path.open("w", encoding="utf-8", newline="") as f_out:
                reader = csv.DictReader(f_in)
                fieldnames = reader.fieldnames
                if not fieldnames:
                    fieldnames = ["id","keyword","author","author_profile","company","text","published_at","collected_at","permalink"]
                writer = csv.DictWriter(f_out, fieldnames=fieldnames)
                writer.writeheader()
                for row in reader:
                    if row.get("keyword") == target_kw:
                        continue
                    writer.writerow(row)
                    kept += 1
            tmp_path.replace(csv_path)
            ctx.logger.info("purge_demo_csv_ok", file=str(csv_path), kept=kept)
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("purge_demo_csv_failed", error=str(exc))

    print("Purge 'demo_recruteur' terminée.")


async def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Ne pas demander de confirmation")
    args = p.parse_args()
    ctx = await get_context()
    if not args.force and not _ask_confirm():
        print("Abandon.")
        return
    await purge_demo(ctx, force=args.force)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
