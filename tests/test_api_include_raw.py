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
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, keyword TEXT, author TEXT, company TEXT, text TEXT, published_at TEXT, collected_at TEXT, permalink TEXT, raw_json TEXT, intent TEXT, relevance_score REAL, confidence REAL, keywords_matched TEXT, location_ok INTEGER)")
        except Exception:
            pass
        # upsert one row
        raw_obj = {"raw": {"sample": True}}
        conn.execute("INSERT OR REPLACE INTO posts (id, keyword, author, company, text, published_at, collected_at, permalink, raw_json, intent, relevance_score, confidence, keywords_matched, location_ok) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("test1","kw","Auteur","Societe","Texte legal avocat recrutement","2025-10-03T08:00:00Z","2025-10-03T08:01:00Z","https://linkedin.com/feed/update/urn:li:activity:123", json.dumps(raw_obj), "recherche_profil", 0.7, 0.8, "avocat;juriste", 1))

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
