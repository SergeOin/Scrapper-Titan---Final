from __future__ import annotations
import argparse
import sqlite3
from pathlib import Path
import sys, os
from datetime import datetime, timedelta, timezone

# Ensure project root on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import os
# Prefer SQLite-only to avoid noisy local connection attempts
os.environ.setdefault("DISABLE_MONGO", "1")
os.environ.setdefault("DISABLE_REDIS", "1")
from scraper.bootstrap import get_context  # type: ignore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report posts throughput from SQLite fallback.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--since-minutes", type=int, default=10, help="Look back window in minutes (default: 10)")
    g.add_argument("--since-iso", type=str, help="ISO8601 timestamp; count posts with collected_at >= this")
    p.add_argument("--group-by-keyword", action="store_true", help="Show counts grouped by keyword")
    return p.parse_args()


def main():
    args = parse_args()
    since_dt: datetime
    if args.since_iso:
        try:
            since_dt = datetime.fromisoformat(args.since_iso.replace("Z", "+00:00"))
        except Exception:
            print("invalid_since_iso", args.since_iso)
            return 2
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(minutes=args.since_minutes)
    since_iso = since_dt.isoformat()

    ctx = None
    try:
        ctx = asyncio.run(get_context())  # type: ignore[name-defined]
    except NameError:
        import asyncio  # lazy to keep imports tidy above
        ctx = asyncio.run(get_context())

    db_path = Path(ctx.settings.sqlite_path)
    if not db_path.exists():
        print("sqlite_missing", db_path)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    with conn:
        try:
            total = conn.execute("select count(*) from posts where collected_at >= ?", (since_iso,)).fetchone()[0]
        except Exception as e:
            print("query_error", e)
            return 3
        print(f"since={since_iso}")
        print(f"total={total}")
        if args.group_by_keyword:
            try:
                for r in conn.execute("select keyword, count(*) as c from posts where collected_at >= ? group by keyword order by c desc", (since_iso,)):
                    print(f"{r['keyword']}\t{r['c']}")
            except Exception as e:
                print("group_error", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
