from __future__ import annotations
import sqlite3
from pathlib import Path
import sys, os

# Ensure project root is on sys.path when invoked from scripts/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.bootstrap import get_context
import asyncio

async def main():
    ctx = await get_context()
    p = Path(ctx.settings.sqlite_path)
    if not p.exists():
        print("sqlite_missing", p)
        return
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    with conn:
        print("db:", p)
        try:
            c = conn.execute("select count(*) from posts").fetchone()[0]
            print("count:", c)
        except Exception as e:
            print("count_error", e)
        print("by_keyword:")
        try:
            for r in conn.execute("select keyword, count(*) as c from posts group by keyword order by c desc limit 20"):
                print(r[0], r[1])
        except Exception as e:
            print("kw_error", e)
        print("samples_demo_like:")
        try:
            q = "%demo%recruteur%"
            for r in conn.execute("select id, keyword, author, company, substr(text,1,80) from posts where lower(keyword) like lower(?) or lower(author) like lower(?) or lower(company) like lower(?) or lower(text) like lower(?) limit 5", (q,q,q,q)):
                print(dict(r))
        except Exception as e:
            print("sample_error", e)

if __name__ == "__main__":
    asyncio.run(main())
