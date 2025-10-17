from __future__ import annotations
import time
import sqlite3
from pathlib import Path
import sys, os
from datetime import datetime, timezone

# Ensure project root on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import os
# Prefer SQLite-only to avoid noisy local connection attempts
os.environ.setdefault("DISABLE_MONGO", "1")
os.environ.setdefault("DISABLE_REDIS", "1")
from scraper.bootstrap import get_context  # type: ignore

WINDOW_MINUTES = int(os.environ.get("THROUGHPUT_WINDOW_MINUTES", "10"))
TOTAL_MINUTES = int(os.environ.get("THROUGHPUT_TOTAL_MINUTES", "30"))
SLEEP_SECONDS = WINDOW_MINUTES * 60


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_since_iso(minutes_back: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_back)).isoformat()


def count_since(conn: sqlite3.Connection, since_iso: str) -> int:
    try:
        return conn.execute("select count(*) from posts where collected_at >= ?", (since_iso,)).fetchone()[0]
    except Exception:
        return -1


def main() -> int:
    import asyncio
    ctx = asyncio.run(get_context())
    db_path = Path(ctx.settings.sqlite_path)
    print(f"[monitor] start={now_iso()} db={db_path} window_min={WINDOW_MINUTES} total_min={TOTAL_MINUTES}")
    if not db_path.exists():
        print("sqlite_missing", db_path)
        return 1
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rounds = max(1, TOTAL_MINUTES // WINDOW_MINUTES)
    for i in range(1, rounds + 1):
        since_iso = get_since_iso(WINDOW_MINUTES)
        total = count_since(conn, since_iso)
        print(f"[monitor] t={now_iso()} window_since={since_iso} total_window={total}")
        sys.stdout.flush()
        if i < rounds:
            time.sleep(SLEEP_SECONDS)
    # Final overall since start
    since_start_iso = get_since_iso(TOTAL_MINUTES)
    overall = count_since(conn, since_start_iso)
    print(f"[monitor] done={now_iso()} overall_since={since_start_iso} total_overall={overall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
