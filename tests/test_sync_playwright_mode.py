import asyncio, os, sqlite3
import pytest
from scraper.bootstrap import get_context
from scraper.worker import process_job

@pytest.mark.asyncio
async def test_sync_playwright_placeholder(tmp_path, monkeypatch):
    # Force sync mode (not mock)
    monkeypatch.setenv("PLAYWRIGHT_FORCE_SYNC", "1")
    monkeypatch.setenv("PLAYWRIGHT_MOCK_MODE", "0")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path/"sync.sqlite3"))
    # Ensure placeholder generation on sync branch
    monkeypatch.setenv("PLAYWRIGHT_SYNC_PLACEHOLDER", "1")
    ctx = await get_context()
    count = await process_job(["python"], ctx)
    assert count >= 1
    # Verify row persisted
    con = sqlite3.connect(str(tmp_path/"sync.sqlite3"))
    with con:
        rows = con.execute("SELECT keyword, text FROM posts").fetchall()
    assert any("sync-mode-placeholder" in (r[1] or "") for r in rows)
