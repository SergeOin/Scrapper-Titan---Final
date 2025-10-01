import asyncio, os, sqlite3, time
from datetime import datetime, timezone, timedelta
import pytest

from scraper.bootstrap import get_context, Settings
from scraper.worker import Post, store_posts
from scraper.core.maintenance import purge_and_vacuum
from scraper.utils import compute_recruitment_signal

@pytest.mark.asyncio
async def test_dedup_permalink_sqlite(tmp_path, monkeypatch):
    db = tmp_path/"dedup.sqlite3"
    monkeypatch.setenv("SQLITE_PATH", str(db))
    ctx = await get_context()
    # Two posts same permalink -> only one row after insert
    p1 = Post(id="a1", keyword="k", author="Auth", author_profile=None, text="Hello", language="fr", published_at=datetime.now(timezone.utc).isoformat(), collected_at=datetime.now(timezone.utc).isoformat(), permalink="https://x/perma/1", raw={})
    p2 = Post(id="a2", keyword="k", author="Auth", author_profile=None, text="Hello again", language="fr", published_at=datetime.now(timezone.utc).isoformat(), collected_at=datetime.now(timezone.utc).isoformat(), permalink="https://x/perma/1", raw={})
    await store_posts(ctx, [p1, p2])
    con = sqlite3.connect(str(db))
    with con:
        cnt = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    assert cnt == 1, f"Expected 1 row, got {cnt}"

@pytest.mark.asyncio
async def test_dedup_author_date_sqlite(tmp_path, monkeypatch):
    db = tmp_path/"dedup2.sqlite3"
    monkeypatch.setenv("SQLITE_PATH", str(db))
    ctx = await get_context()
    ts = datetime.now(timezone.utc).isoformat()
    p1 = Post(id="b1", keyword="k", author="Same", author_profile=None, text="Alpha", language="fr", published_at=ts, collected_at=ts, permalink=None, raw={})
    p2 = Post(id="b2", keyword="k", author="Same", author_profile=None, text="Beta", language="fr", published_at=ts, collected_at=ts, permalink=None, raw={})
    await store_posts(ctx, [p1, p2])
    con = sqlite3.connect(str(db))
    with con:
        cnt = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    assert cnt == 1

@pytest.mark.asyncio
async def test_dedup_content_hash_sqlite(tmp_path, monkeypatch):
    db = tmp_path/"dedup3.sqlite3"
    monkeypatch.setenv("SQLITE_PATH", str(db))
    ctx = await get_context()
    # Different ids, same author empty, same content -> single row due to content hash index
    ts = datetime.now(timezone.utc).isoformat()
    p1 = Post(id="c1", keyword="k", author="", author_profile=None, text="Repeated body", language="fr", published_at=None, collected_at=ts, permalink=None, raw={})
    p2 = Post(id="c2", keyword="k", author="", author_profile=None, text="Repeated body", language="fr", published_at=None, collected_at=ts, permalink=None, raw={})
    await store_posts(ctx, [p1, p2])
    con = sqlite3.connect(str(db))
    with con:
        cnt = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    assert cnt == 1

@pytest.mark.asyncio
async def test_recruitment_filter(monkeypatch):
    # Ensure filtering only keeps recruitment posts when enabled
    monkeypatch.setenv("FILTER_RECRUITMENT_ONLY", "1")
    ctx = await get_context()
    thresh = ctx.settings.recruitment_signal_threshold
    good_text = "Nous recrutons un développeur Python en CDI"  # strong recruitment signal
    bad_text = "J'adore coder et partager des astuces."        # low signal
    assert compute_recruitment_signal(good_text) >= thresh
    assert compute_recruitment_signal(bad_text) < thresh

@pytest.mark.asyncio
async def test_purge_and_vacuum(tmp_path, monkeypatch):
    db = tmp_path/"purge.sqlite3"
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setenv("PURGE_MAX_AGE_DAYS", "1")
    ctx = await get_context()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    old_post = Post(id="old", keyword="k", author="A", author_profile=None, text="Ancien", language="fr", published_at=old_ts, collected_at=old_ts, permalink=None, raw={})
    new_post = Post(id="new", keyword="k", author="A", author_profile=None, text="Recent", language="fr", published_at=new_ts, collected_at=new_ts, permalink=None, raw={})
    await store_posts(ctx, [old_post, new_post])
    stats = purge_and_vacuum(str(db), 1, True, ctx.logger)
    con = sqlite3.connect(str(db))
    with con:
        rows = con.execute("SELECT id FROM posts").fetchall()
    ids = {r[0] for r in rows}
    assert "old" not in ids and "new" in ids
    assert stats["purged"] >= 1
