"""Purge or inspect mock/demo posts in the local SQLite fallback.

Usage:
  python scripts/purge_mock_posts.py            # dry-run (no deletion)
  python scripts/purge_mock_posts.py --purge    # delete posts + orphan flags
  python scripts/purge_mock_posts.py --rename demo_visible   # rename author

It auto-detects the SQLite path via:
  1. ENV SQLITE_PATH
  2. %LOCALAPPDATA%/TitanScraper/fallback.sqlite3 (Windows typical)
  3. ./fallback.sqlite3 (repo root)

Exit code 0 on success, >0 on unexpected error.
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from pathlib import Path

MOCK_NAMES = {"demo_recruteur", "demo_visible"}

def resolve_sqlite() -> Path:
    env = os.getenv("SQLITE_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p
    # Windows typical local appdata
    la = os.getenv("LOCALAPPDATA")
    if la:
        p2 = Path(la) / "TitanScraper" / "fallback.sqlite3"
        if p2.exists():
            return p2
    # Fallback: repo root
    return Path.cwd() / "fallback.sqlite3"

def stats(conn: sqlite3.Connection) -> dict:
    d: dict[str, int] = {"total": 0, "mock": 0, "flags": 0}
    try:
        d["total"] = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    except Exception:
        return d
    try:
        placeholders = ",".join(["?"] * len(MOCK_NAMES))
        d["mock"] = conn.execute(f"SELECT COUNT(*) FROM posts WHERE lower(author) IN ({placeholders})", [n.lower() for n in MOCK_NAMES]).fetchone()[0]
    except Exception:
        pass
    try:
        # flags table optional
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='post_flags'").fetchone():
            d["flags"] = conn.execute("SELECT COUNT(*) FROM post_flags").fetchone()[0]
    except Exception:
        pass
    return d

def purge(conn: sqlite3.Connection) -> tuple[int, int]:
    deleted_posts = 0
    deleted_flags = 0
    try:
        placeholders = ",".join(["?"] * len(MOCK_NAMES))
        deleted_posts = conn.execute(
            f"DELETE FROM posts WHERE lower(author) IN ({placeholders})",
            [n.lower() for n in MOCK_NAMES],
        ).rowcount
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='post_flags'").fetchone():
            deleted_flags = conn.execute(
                "DELETE FROM post_flags WHERE post_id NOT IN (SELECT id FROM posts)"
            ).rowcount
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("[purge] ERROR", e)
    return deleted_posts, deleted_flags

def rename(conn: sqlite3.Connection, new_author: str) -> int:
    try:
        rc = conn.execute(
            "UPDATE posts SET author=? WHERE lower(author) IN (" + ",".join(["?"]*len(MOCK_NAMES)) + ")",
            [new_author] + [n.lower() for n in MOCK_NAMES],
        ).rowcount
        conn.commit()
        return rc
    except Exception as e:
        conn.rollback()
        print("[rename] ERROR", e)
        return 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--purge", action="store_true", help="Delete mock posts + orphan flags")
    parser.add_argument("--rename", metavar="NEW_AUTHOR", help="Rename all mock authors to NEW_AUTHOR")
    args = parser.parse_args()

    db_path = resolve_sqlite()
    print(f"[info] SQLite path: {db_path} (exists={db_path.exists()})")
    if not db_path.exists():
        print("[warn] Database file not found – nothing to do.")
        return

    conn = sqlite3.connect(db_path)
    try:
        before = stats(conn)
        print(f"[before] total={before['total']} mock={before['mock']} flags={before['flags']}")
        if args.rename:
            changed = rename(conn, args.rename)
            after = stats(conn)
            print(f"[rename] changed_rows={changed} -> total={after['total']} mock={after['mock']} flags={after['flags']}")
            return
        if args.purge:
            dp, df = purge(conn)
            after = stats(conn)
            print(f"[purge] deleted_posts={dp} orphan_flags_deleted={df} -> total={after['total']} mock={after['mock']} flags={after['flags']}")
        else:
            print("[dry-run] Use --purge to delete mock posts or --rename NEW_AUTHOR to relabel them.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
