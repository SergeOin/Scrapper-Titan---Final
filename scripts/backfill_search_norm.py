"""Backfill accent-insensitive search_norm for existing SQLite rows and ensure indices.

Usage (PowerShell):
  python scripts/backfill_search_norm.py
  # or specify a custom DB path
  python scripts/backfill_search_norm.py --db .\\fallback.sqlite3
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Optional

import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scraper.utils import build_search_norm


def backfill(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    updated = 0
    with conn:
        # Ensure column exists
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
            if "search_norm" not in cols:
                conn.execute("ALTER TABLE posts ADD COLUMN search_norm TEXT")
        except Exception:
            pass
        # Create helpful indices
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_posts_permalink ON posts(permalink) WHERE permalink IS NOT NULL")
        except Exception:
            pass
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_posts_author_published ON posts(author, published_at) WHERE author IS NOT NULL AND published_at IS NOT NULL")
        except Exception:
            pass
        # Iterate rows missing search_norm or with empty value
        cur = conn.execute("SELECT id, text, author, company, keyword FROM posts WHERE search_norm IS NULL OR LENGTH(search_norm) = 0")
        rows = cur.fetchall()
        for (pid, text, author, company, keyword) in rows:
            norm = build_search_norm(text, author, company, keyword)
            conn.execute("UPDATE posts SET search_norm = ? WHERE id = ?", (norm, pid))
            updated += 1
    return updated


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fallback.sqlite3", help="SQLite database path")
    args = ap.parse_args(argv)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return
    n = backfill(db_path)
    print(f"backfill_search_norm_done updated={n} path={db_path}")


if __name__ == "__main__":
    main()
