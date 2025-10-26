import os, sqlite3, json
from pathlib import Path
base = Path(os.environ.get('LOCALAPPDATA','')) / 'TitanScraper'
db = base / 'fallback.sqlite3'
res={"db":str(db),"exists":db.exists(),"sample":[],"deleted":0}
if db.exists():
    conn=sqlite3.connect(str(db)); conn.row_factory=sqlite3.Row
    with conn:
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS post_flags (post_id TEXT PRIMARY KEY, is_favorite INTEGER, is_deleted INTEGER, favorite_at TEXT, deleted_at TEXT)")
        except Exception:
            pass
        try:
            rows=conn.execute("SELECT p.id, p.author, p.company, p.collected_at, COALESCE(f.is_deleted,0) AS del FROM posts p LEFT JOIN post_flags f ON f.post_id=p.id ORDER BY p.collected_at DESC LIMIT 5").fetchall()
            res["sample"]= [dict(r) for r in rows]
            res["deleted"] = sum(1 for r in rows if int(r["del"])==1)
        except Exception as e:
            res["error"]=str(e)
print(json.dumps(res, ensure_ascii=False, indent=2))
