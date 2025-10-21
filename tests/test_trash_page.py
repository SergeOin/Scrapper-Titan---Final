import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from scraper import bootstrap
from server.main import app


@pytest.mark.asyncio
async def test_corbeille_ok_when_no_posts_table(tmp_path):
    # Bootstrap context and force mock mode to bypass LinkedIn session dependency
    ctx = await bootstrap.bootstrap(force=True)
    ctx.settings.playwright_mock_mode = True  # type: ignore[attr-defined]

    # Point to an empty sqlite file (no 'posts' table)
    db_path = tmp_path / 'empty.sqlite3'
    db_path.write_bytes(b'')
    ctx.settings.sqlite_path = str(db_path)  # type: ignore[attr-defined]

    # Sanity: the file exists but has no schema
    conn = sqlite3.connect(str(db_path))
    with conn:
        # Do not create posts table here on purpose
        pass

    client = TestClient(app)
    r = client.get('/corbeille')
    assert r.status_code == 200
    assert 'Corbeille' in r.text
