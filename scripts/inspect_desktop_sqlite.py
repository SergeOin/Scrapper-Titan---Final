from __future__ import annotations
import os, sqlite3, json
from pathlib import Path

base = Path(os.environ.get('LOCALAPPDATA', '')) / 'TitanScraper'
db = base / 'fallback.sqlite3'
res = {
    'db_exists': db.exists(),
    'db_path': str(db),
    'posts_count': None,
    'meta': None,
    'error': None,
}
try:
    if db.exists():
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        with conn:
            try:
                c = conn.execute('select count(*) from posts').fetchone()[0]
                res['posts_count'] = int(c)
            except Exception as e:
                res['posts_count'] = f'error: {e}'
            try:
                row = conn.execute("select id, last_run, posts_count from meta where id='global'").fetchone()
                res['meta'] = dict(row) if row else None
            except Exception as e:
                res['meta'] = f'error: {e}'
except Exception as e:
    res['error'] = str(e)

print(json.dumps(res, ensure_ascii=False, indent=2))
