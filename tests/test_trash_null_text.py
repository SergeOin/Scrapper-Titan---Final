import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from scraper import bootstrap
from server.main import app


@pytest.mark.asyncio
async def test_corbeille_handles_null_text(tmp_path):
    # Force mock mode to bypass LinkedIn session requirement
    ctx = await bootstrap.bootstrap(force=True)
    ctx.settings.playwright_mock_mode = True  # type: ignore[attr-defined]

    # Create sqlite DB with minimal schema used by _fetch_deleted_posts
    db_path = tmp_path / 'trash_null_text.sqlite3'
    ctx.settings.sqlite_path = str(db_path)  # type: ignore[attr-defined]

    conn = sqlite3.connect(str(db_path))
    with conn:
        conn.execute(
            """
            CREATE TABLE posts (
                id TEXT PRIMARY KEY,
                keyword TEXT,
                author TEXT,
                company TEXT,
                text TEXT,
                published_at TEXT,
                collected_at TEXT,
                permalink TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE post_flags (
                post_id TEXT PRIMARY KEY,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                favorite_at TEXT,
                deleted_at TEXT
            )
            """
        )
        # Insert a post with NULL text and mark as deleted
        conn.execute(
            "INSERT INTO posts(id, keyword, author, company, text, published_at, collected_at, permalink) VALUES(?,?,?,?,?,?,?,?)",
            ("p1", "kw", "Auteur", "Entreprise", None, None, None, None),
        )
        conn.execute(
            "INSERT INTO post_flags(post_id, is_favorite, is_deleted, favorite_at, deleted_at) VALUES(?,?,?,?,datetime('now'))",
            ("p1", 0, 1, None),
        )

    client = TestClient(app)
    r = client.get('/corbeille')
    assert r.status_code == 200
    assert 'Corbeille' in r.text
