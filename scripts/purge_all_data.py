"""Utility script to purge all persisted post data (SQLite + CSV + flags).

Usage (from project root, virtualenv active):
    python scripts/purge_all_data.py

It will:
 1. Delete SQLite file and recreate empty schema file (optional, can skip recreate).
 2. Remove CSV fallback file.
 3. Remove session-related flags (optional) only if --include-session passed.

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
    from scraper.bootstrap import Settings, configure_logging  # type: ignore
except ModuleNotFoundError:
    # Fallback: add project root (parent of scripts/) to sys.path then retry
    import sys as _sys
    from pathlib import Path as _Path
    root = _Path(__file__).resolve().parent.parent
    if str(root) not in _sys.path:
        _sys.path.insert(0, str(root))
    from scraper.bootstrap import Settings, configure_logging  # type: ignore

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
    removed = []
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
        try:
            ss = Path("storage_state.json")
            if ss.exists():
                ss.unlink()
                removed.append("session:storage_state.json")
        except Exception as exc:
            print(f"Session purge error: {exc}")
    if removed:
        print(f"Purged: {', '.join(removed)}")
    else:
        print("Nothing to purge.")
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Purge all post data")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--include-session", action="store_true", help="Also remove session files")
    args = parser.parse_args()
    return asyncio.run(_purge_async(args.include_session, args.yes))


if __name__ == "__main__":
    sys.exit(main())
