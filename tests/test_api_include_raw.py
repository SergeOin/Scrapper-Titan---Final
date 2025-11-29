import asyncio
import pytest
from httpx import AsyncClient

from server.main import app  # type: ignore
from scraper.bootstrap import get_context

pytestmark = pytest.mark.asyncio

async def _seed_sqlite_with_minimal_post(ctx):
    import sqlite3, json, os
    path = ctx.settings.sqlite_path or 'fallback.sqlite3'
    if not path:
        return
    conn = sqlite3.connect(path)
    with conn:
        # Get existing table schema
        cursor = conn.execute("PRAGMA table_info(posts)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if not columns:
            # Create minimal table if not exists
            conn.execute("""CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY, keyword TEXT, author TEXT, company TEXT, 
                text TEXT, published_at TEXT, collected_at TEXT, permalink TEXT, 
                raw_json TEXT, language TEXT, author_profile TEXT, search_norm TEXT
            )""")
            columns = ['id', 'keyword', 'author', 'company', 'text', 'published_at', 
                      'collected_at', 'permalink', 'raw_json', 'language', 'author_profile', 'search_norm']
        
        # Build insert based on available columns
        raw_obj = {"raw": {"sample": True}}
        base_data = {
            'id': 'test1', 'keyword': 'kw', 'author': 'Auteur', 'company': 'Societe',
            'text': 'Texte legal avocat recrutement CDI Paris',
            'published_at': '2025-10-03T08:00:00Z', 'collected_at': '2025-10-03T08:01:00Z',
            'permalink': 'https://linkedin.com/feed/update/urn:li:activity:123',
            'raw_json': json.dumps(raw_obj), 'language': 'fr', 'author_profile': None, 'search_norm': None
        }
        # Filter to only columns that exist in table
        data = {k: v for k, v in base_data.items() if k in columns}
        cols = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data])
        conn.execute(f"INSERT OR REPLACE INTO posts ({cols}) VALUES ({placeholders})", list(data.values()))

async def test_api_posts_include_raw():
    ctx = await get_context()
    # Ensure sqlite path exists for fallback scenario
    await _seed_sqlite_with_minimal_post(ctx)
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r1 = await ac.get("/api/posts?limit=5&include_raw=0")
        assert r1.status_code == 200
        data1 = r1.json()
        assert "items" in data1
        # Without include_raw classification_debug should be absent
        assert all("classification_debug" not in p for p in data1["items"])
        r2 = await ac.get("/api/posts?limit=5&include_raw=1")
        assert r2.status_code == 200
        data2 = r2.json()
        assert any("classification_debug" in p for p in data2["items"])
        for p in data2["items"]:
            if "classification_debug" in p:
                cd = p["classification_debug"]
                assert "intent" in cd
                assert "relevance_score" in cd
                assert "keywords_matched" in cd
                break
