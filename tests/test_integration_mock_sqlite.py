import os, sqlite3, asyncio
from scraper.bootstrap import bootstrap
from scraper.core import mock as mock_core
from scraper.core.storage import store_posts_sqlite

class DummySettings:
    sqlite_path = "test_fallback.sqlite3"
    recruitment_signal_threshold = 0.05

async def _prepare_ctx():
    ctx = await bootstrap(force=True)
    # Force mock mode to avoid Playwright usage
    ctx.settings.playwright_mock_mode = True  # type: ignore
    return ctx

def test_mock_cycle_inserts_sqlite(tmp_path):
    db_path = tmp_path / "fallback.sqlite3"
    os.environ["SQLITE_PATH"] = str(db_path)
    ctx = asyncio.run(bootstrap(force=True))
    ctx.settings.playwright_mock_mode = True  # type: ignore
    posts = mock_core.generate_mock_posts("avocat", 2, ctx.settings, ctx.settings.recruitment_signal_threshold)
    store_posts_sqlite(str(db_path), posts, ctx.logger)
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    with conn:
        row = conn.execute("SELECT COUNT(*) FROM posts").fetchone()
        assert row and row[0] >= 2
    conn.close()
