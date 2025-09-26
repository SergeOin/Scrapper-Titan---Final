"""Utility script to purge all persisted post data (Mongo + SQLite + CSV + flags).

Usage (from project root, virtualenv active):
    python scripts/purge_all_data.py

It will:
 1. Drop Mongo collections (posts + meta) if Mongo reachable and not disabled.
 2. Delete SQLite file and recreate empty schema file (optional, can skip recreate).
 3. Remove CSV fallback file.
 4. Remove session-related flags (optional) only if --include-session passed.

Safeguards:
  - Asks for confirmation unless --yes is provided.
  - Refuses to run if environment variable PROTECT_DATA=1.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import asyncio

try:
    from scraper.bootstrap import Settings, configure_logging, init_mongo  # type: ignore
except ModuleNotFoundError:
    # Fallback: add project root (parent of scripts/) to sys.path then retry
    import sys as _sys
    from pathlib import Path as _Path
    root = _Path(__file__).resolve().parent.parent
    if str(root) not in _sys.path:
        _sys.path.insert(0, str(root))
    from scraper.bootstrap import Settings, configure_logging, init_mongo  # type: ignore

SQLITE_DEFAULT = "fallback.sqlite3"
CSV_DEFAULT = "exports/fallback_posts.csv"

async def _purge_async(include_session: bool, yes: bool) -> int:
    settings = Settings()
    configure_logging(settings.log_level, settings)
    # Safeguard
    if os.environ.get("PROTECT_DATA") == "1":
        print("Refusé: PROTECT_DATA=1 est défini.")
        return 2
    if not yes:
        ans = input("Confirmer la purge TOTALE des données (oui/non)? ").strip().lower()
        if ans not in {"o", "oui", "y", "yes"}:
            print("Annulé.")
            return 1
    # Mongo
    removed = []
    try:
        if not settings.disable_mongo:
            from scraper.bootstrap import AsyncIOMotorClient  # type: ignore
            client = await init_mongo(settings, __import__("structlog").get_logger().bind(component="purge"))
            if client:
                db = client[settings.mongo_db]
                await db.drop_collection(settings.mongo_collection_posts)
                await db.drop_collection(settings.mongo_collection_meta)
                removed.append(f"mongo:{settings.mongo_db}.{settings.mongo_collection_posts}")
                removed.append(f"mongo:{settings.mongo_db}.{settings.mongo_collection_meta}")
    except Exception as exc:
        print(f"Mongo purge error: {exc}")
    # SQLite
    try:
        sqlite_path = settings.sqlite_path or SQLITE_DEFAULT
        p = Path(sqlite_path)
        if p.exists():
            p.unlink()
            removed.append(f"sqlite:{sqlite_path}")
    except Exception as exc:
        print(f"SQLite purge error: {exc}")
    # CSV
    try:
        csv_path = Path(settings.csv_fallback_file or CSV_DEFAULT)
        if csv_path.exists():
            csv_path.unlink()
            removed.append(f"csv:{csv_path}")
    except Exception as exc:
        print(f"CSV purge error: {exc}")
    # Flags table is inside SQLite -> already gone
    # Session (optional)
    if include_session:
        for path in [settings.storage_state, settings.session_store_path, 'runtime_state.json']:
            try:
                f = Path(path)
                if f.exists():
                    f.unlink()
                    removed.append(f"session:{path}")
            except Exception:
                pass
    print("Purged:")
    for r in removed:
        print(" -", r)
    if not removed:
        print("Rien à purger (déjà vide).")
    return 0

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Purge all stored scraper data")
    parser.add_argument("--yes", action="store_true", help="Ne pas demander de confirmation")
    parser.add_argument("--include-session", action="store_true", help="Supprimer aussi l'état de session (cookies)")
    args = parser.parse_args()
    rc = asyncio.run(_purge_async(include_session=args.include_session, yes=args.yes))
    sys.exit(rc)

if __name__ == "__main__":
    main()
