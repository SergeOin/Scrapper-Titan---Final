"""Storage abstraction wrappers for Mongo / SQLite / CSV."""
from __future__ import annotations
from pathlib import Path
import json, os, sqlite3
from typing import Any, List
from ..bootstrap import (
    SCRAPE_STORAGE_ATTEMPTS,
)
from .. import utils

def ensure_sqlite_schema(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            keyword TEXT,
            author TEXT,
            author_profile TEXT,
            company TEXT,
            permalink TEXT,
            text TEXT,
            language TEXT,
            published_at TEXT,
            collected_at TEXT,
            raw_json TEXT,
            search_norm TEXT,
            content_hash TEXT
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_keyword ON posts(keyword)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_at)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS post_flags (
            post_id TEXT PRIMARY KEY,
            is_favorite INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            favorite_at TEXT,
            deleted_at TEXT
            )"""
        )
    conn.close()

def store_posts_sqlite(path: str, posts: list[dict[str, Any]], logger):
    if not posts:
        return
    ensure_sqlite_schema(path)
    conn = sqlite3.connect(path)
    with conn:
        rows = []
        for p in posts:
            try:
                s_norm = utils.build_search_norm(p.get('text'), p.get('author'), p.get('company'), p.get('keyword'))
            except Exception:
                s_norm = None
            rows.append((
                p['id'], p.get('keyword'), p.get('author'), p.get('author_profile'), p.get('company'), p.get('permalink'),
                p.get('text'), p.get('language'), p.get('published_at'), p.get('collected_at'), json.dumps(p.get('raw') or {}), s_norm, p.get('content_hash')
            ))
        conn.executemany("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.close()
    SCRAPE_STORAGE_ATTEMPTS.labels("sqlite", "success").inc()
    logger.info("sqlite_inserted", inserted=len(posts), path=path)
