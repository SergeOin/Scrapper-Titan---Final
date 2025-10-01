"""Maintenance tasks: purge old posts and optional VACUUM."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import sqlite3, os

def purge_and_vacuum(sqlite_path: str, max_age_days: int, do_vacuum: bool, logger) -> dict:
    if not sqlite_path or not os.path.exists(sqlite_path):
        return {"purged": 0, "vacuum": False}
    purged = 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        conn = sqlite3.connect(sqlite_path)
        with conn:
            # posts without published_at: use collected_at
            rows = conn.execute("SELECT id, published_at, collected_at FROM posts").fetchall()
            to_delete = []
            for r in rows:
                pid, pub, col = r
                ts_raw = pub or col
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                except Exception:
                    continue
                if ts < cutoff:
                    to_delete.append(pid)
            if to_delete:
                placeholders = ",".join(["?"]*len(to_delete))
                conn.execute(f"DELETE FROM posts WHERE id IN ({placeholders})", to_delete)
                purged = conn.total_changes
            if purged:
                logger.info("purge_old_posts", purged=purged, days=max_age_days)
            if do_vacuum and purged:
                try:
                    conn.execute("VACUUM")
                    logger.info("sqlite_vacuum_done")
                    vac = True
                except Exception:
                    vac = False
            else:
                vac = False
        conn.close()
    except Exception as exc:
        logger.warning("purge_failed", error=str(exc))
    return {"purged": purged, "vacuum": vac}
