#!/usr/bin/env python
"""Generate classifier rejection ratio and intent distribution.

Reads recent posts from Mongo (if available) or SQLite fallback and prints a summary
suitable for adding to a GitHub Issue comment.

Environment overrides:
  - REPORT_LIMIT (default 500)
  - SQLITE_PATH (fallback path)
"""
from __future__ import annotations
import os, json, sqlite3, statistics
from datetime import datetime, timezone
from typing import Any

REPORT_LIMIT = int(os.environ.get("REPORT_LIMIT", "500"))
SQLITE_PATH = os.environ.get("SQLITE_PATH", "fallback.sqlite3")


def _fetch_from_sqlite(limit: int) -> list[dict[str, Any]]:
    if not os.path.exists(SQLITE_PATH):
        return []
    conn = sqlite3.connect(SQLITE_PATH)
    cur = conn.cursor()
    # Try extended columns; fall back gracefully
    cols = [r[1] for r in cur.execute("PRAGMA table_info(posts)").fetchall()]
    sel_cols = [c for c in ["id","intent","relevance_score","confidence","keywords_matched","language","collected_at"] if c in cols]
    if not sel_cols:
        return []
    q = f"SELECT {','.join(sel_cols)} FROM posts ORDER BY collected_at DESC LIMIT ?" if 'collected_at' in cols else f"SELECT {','.join(sel_cols)} FROM posts LIMIT ?"
    rows = cur.execute(q, (limit,)).fetchall()
    result = []
    for r in rows:
        doc = {sel_cols[i]: r[i] for i in range(len(sel_cols))}
        result.append(doc)
    return result


def _summarize(docs: list[dict[str, Any]]) -> dict[str, Any]:
    intents = {}
    scores = []
    for d in docs:
        intent = d.get("intent") or "unknown"
        intents[intent] = intents.get(intent, 0) + 1
        if d.get("relevance_score") is not None:
            try:
                scores.append(float(d["relevance_score"]))
            except Exception:
                pass
    total = sum(intents.values()) or 1
    rejection_ratio = intents.get("autre", 0) / total
    return {
        "total_sample": total,
        "intents": intents,
        "rejection_ratio": round(rejection_ratio, 4),
        "mean_relevance": round(statistics.mean(scores), 4) if scores else None,
        "median_relevance": round(statistics.median(scores), 4) if scores else None,
    }


def main():
    # Attempt Mongo first (optional dependency)
    docs: list[dict[str, Any]] = []
    try:
        from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
        import asyncio
        async def _mongo():
            uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')
            dbname = os.environ.get('MONGO_DB', 'linkedin_scrape')
            coll = os.environ.get('MONGO_COLLECTION_POSTS', 'posts')
            client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=2000)
            # quick ping
            await client.admin.command('ping')
            cursor = client[dbname][coll].find({}, {"intent":1,"relevance_score":1,"confidence":1,"keywords_matched":1,"language":1,"collected_at":1}).sort("collected_at", -1).limit(REPORT_LIMIT)
            return [d async for d in cursor]
        docs = asyncio.run(_mongo())  # type: ignore
    except Exception:
        docs = _fetch_from_sqlite(REPORT_LIMIT)
    summary = _summarize(docs)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": REPORT_LIMIT,
        **summary,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

if __name__ == "__main__":  # pragma: no cover
    main()
