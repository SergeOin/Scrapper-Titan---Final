import os, sqlite3, asyncio, pytest
from scraper.core.storage import ensure_sqlite_schema

def test_sqlite_indexes(tmp_path):
    path = tmp_path/"idx.sqlite3"
    ensure_sqlite_schema(str(path))
    con = sqlite3.connect(str(path))
    with con:
        rows = con.execute("PRAGMA index_list(posts)").fetchall()
    names = {r[1] for r in rows}
    assert 'idx_posts_keyword' in names
    assert 'idx_posts_published' in names
    assert 'idx_posts_keyword_published' in names
