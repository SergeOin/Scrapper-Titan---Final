import os, sqlite3, asyncio
from datetime import datetime, timedelta, timezone
import pytest
from scraper.core.maintenance import purge_and_vacuum
from scraper.bootstrap import get_context
from scraper.worker import Post, store_posts

@pytest.mark.asyncio
async def test_purge_old_posts(tmp_path, monkeypatch):
    db = tmp_path/"purge_cycle.sqlite3"
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setenv("PURGE_MAX_AGE_DAYS", "1")
    ctx = await get_context()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    old_post = Post(id="oldX", keyword="k", author="A", author_profile=None, text="Ancien", language="fr", published_at=old_ts, collected_at=old_ts, permalink=None, raw={})
    new_post = Post(id="newX", keyword="k", author="A", author_profile=None, text="Recent", language="fr", published_at=new_ts, collected_at=new_ts, permalink=None, raw={})
    await store_posts(ctx, [old_post, new_post])
    stats = purge_and_vacuum(str(db), 1, True, ctx.logger)
    con = sqlite3.connect(str(db))
    with con:
        ids = {r[0] for r in con.execute("SELECT id FROM posts").fetchall()}
    assert "oldX" not in ids and "newX" in ids
    assert stats["purged"] >= 1
