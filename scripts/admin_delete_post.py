from __future__ import annotations
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import sys

# Use project settings to resolve SQLite path
import sys as _sys
from pathlib import Path as _Path
# Ensure project root is on sys.path when running from scripts/
_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from scraper.bootstrap import Settings


def ensure_post_flags(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS post_flags (
            post_id TEXT PRIMARY KEY,
            is_favorite INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            favorite_at TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_post_flags_deleted ON post_flags(is_deleted, deleted_at)")


def main():
    ap = argparse.ArgumentParser(description="Soft-delete posts in SQLite by filters")
    ap.add_argument("--text", help="Exact text match (case-sensitive)")
    ap.add_argument("--author", help="Exact author match", default=None)
    ap.add_argument("--keyword", help="Exact keyword match", default=None)
    ap.add_argument("--db", help="Path to SQLite DB (overrides settings)", default=None)
    args = ap.parse_args()

    settings = Settings()
    db_path = Path(args.db or settings.sqlite_path)
    if not db_path.exists():
        print(f"[admin_delete_post] SQLite not found: {db_path}")
        sys.exit(1)

    where = ["text = ?"]
    params = [args.text]
    if args.author:
        where.append("author = ?")
        params.append(args.author)
    if args.keyword:
        where.append("keyword = ?")
        params.append(args.keyword)

    query = "SELECT id, author, keyword, text, collected_at FROM posts WHERE " + " AND ".join(where)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    with conn:
        ensure_post_flags(conn)
        rows = list(conn.execute(query, params))
        if not rows:
            print("[admin_delete_post] No matches.")
            return
        print(f"[admin_delete_post] Matches: {len(rows)} (db={db_path})")
        now = datetime.now(timezone.utc).isoformat()
        for r in rows:
            pid = r["id"]
            conn.execute(
                """
                INSERT INTO post_flags(post_id, is_favorite, is_deleted, favorite_at, deleted_at)
                VALUES(?, 0, 1, NULL, ?)
                ON CONFLICT(post_id) DO UPDATE SET is_deleted=excluded.is_deleted, deleted_at=excluded.deleted_at
                """,
                (pid, now),
            )
            print(f" - soft-deleted post_id={pid} author={r['author']} keyword={r['keyword']}")
    print("[admin_delete_post] Done.")


if __name__ == "__main__":
    main()
