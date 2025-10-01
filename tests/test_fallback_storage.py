import os
import asyncio
from pathlib import Path
import sqlite3

import pytest

from scraper.worker import store_posts, Post
from scraper.bootstrap import AppContext, Settings, configure_logging
import structlog

@pytest.mark.asyncio
async def test_store_posts_fallback_sqlite(tmp_path, monkeypatch):
    # Force no mongo client
    settings = Settings()
    settings.sqlite_path = str(tmp_path / 'fallback.sqlite3')  # type: ignore[attr-defined]
    settings.csv_fallback_file = str(tmp_path / 'fb.csv')  # type: ignore[attr-defined]

    configure_logging(settings.log_level, settings)
    logger = structlog.get_logger().bind(test="fallback")
    ctx = AppContext(settings=settings, logger=logger, mongo_client=None, redis=None)

    posts = [
        Post(
            id=f"id-{i}",
            keyword="python",
            author="Author",
            author_profile=None,
            text="Sample text",
            language="fr",
            published_at=None,
            collected_at="2025-09-18T10:00:00Z",
            score=0.5,
            raw={},
        )
        for i in range(3)
    ]

    await store_posts(ctx, posts)

    # Validate sqlite written
    assert Path(settings.sqlite_path).exists()
    conn = sqlite3.connect(settings.sqlite_path)
    with conn:
        cur = conn.execute("SELECT COUNT(*) FROM posts")
        count = cur.fetchone()[0]
    # With new content_hash unique index + batch hash skip, identical author/text collapse to 1 row
    assert count == 1

@pytest.mark.asyncio
async def test_store_posts_fallback_csv(tmp_path, monkeypatch):
    # Simule échec SQLite en pointant vers un chemin invalide (dossier sans permission improbable)
    settings = Settings()
    bad_dir = tmp_path / 'no_such_dir'
    # monkeypatch path to force sqlite error by using a file in a directory we remove then set read-only? Simpler: monkeypatch function
    settings.sqlite_path = str(tmp_path / 'will_not_be_used.sqlite3')  # type: ignore[attr-defined]
    settings.csv_fallback_file = str(tmp_path / 'fallback.csv')  # type: ignore[attr-defined]

    configure_logging(settings.log_level, settings)
    logger = structlog.get_logger().bind(test="fallback_csv")
    ctx = AppContext(settings=settings, logger=logger, mongo_client=None, redis=None)

    from scraper import worker as worker_mod

    def boom(*args, **kwargs):  # pragma: no cover - forced failure path
        raise RuntimeError("forced sqlite failure")

    monkeypatch.setattr(worker_mod, "_store_sqlite", boom)

    posts = [
        Post(
            id=f"cid-{i}",
            keyword="ai",
            author="Author",
            author_profile=None,
            text="TXT",
            language="fr",
            published_at=None,
            collected_at="2025-09-18T10:00:00Z",
            score=0.6,
            raw={},
        )
        for i in range(2)
    ]

    await store_posts(ctx, posts)
    assert Path(settings.csv_fallback_file).exists()
    content = Path(settings.csv_fallback_file).read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1 + 2  # header + rows
