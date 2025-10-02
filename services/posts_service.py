from __future__ import annotations
from typing import List, Optional, Any
from pathlib import Path
import sqlite3

MOCK_AUTHOR_NAMES = {"demo_recruteur", "demo_visible"}

class PostsService:
    """Unified read access (Mongo first then SQLite) for production posts only."""

    async def list_posts(
        self,
        ctx,
        *,
        skip: int,
        limit: int,
        q: Optional[str] = None,
        sort_field: str = "collected_at",
        sort_direction: int = -1,
    ) -> List[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        # 1. Mongo path
        if ctx.mongo_client:
            try:
                author_filter = {"$nin": [name for name in MOCK_AUTHOR_NAMES]}
                mf: dict[str, Any] = {"author": author_filter, "keyword": author_filter}
                if q:
                    mf.setdefault("$or", []).extend([
                        {"text": {"$regex": q, "$options": "i"}},
                        {"author": {"$regex": q, "$options": "i"}},
                        {"company": {"$regex": q, "$options": "i"}},
                        {"keyword": {"$regex": q, "$options": "i"}},
                    ])
                coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
                proj = {"raw": 0, "score": 0, "recruitment_score": 0}
                cursor = coll.find(mf, proj).sort(sort_field, sort_direction).skip(skip).limit(limit)
                async for doc in cursor:
                    rows.append(doc)
            except Exception:
                rows = []
        # Annotate favorites/deleted flags from SQLite when available
        rows = self._apply_sqlite_flags(ctx, rows, include_deleted=False)

        # 2. SQLite fallback (when Mongo unavailable or empty)
        used_fallback = False
        if (not rows) and ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
            conn = sqlite3.connect(ctx.settings.sqlite_path)
            conn.row_factory = sqlite3.Row
            with conn:
                self._ensure_post_flags(conn)
                base = (
                    "SELECT p.id as _id, p.keyword, p.author, p.author_profile, p.company, p.text, "
                    "p.published_at, p.collected_at, p.permalink, "
                    "COALESCE(f.is_favorite,0) AS is_favorite, COALESCE(f.is_deleted,0) AS is_deleted "
                    "FROM posts p LEFT JOIN post_flags f ON f.post_id = p.id"
                )
                clauses: list[str] = []
                params: list[Any] = []
                placeholders = ",".join(["?"] * len(MOCK_AUTHOR_NAMES))
                clauses.append(f"LOWER(p.author) NOT IN ({placeholders})")
                clauses.append(f"LOWER(p.keyword) NOT IN ({placeholders})")
                params.extend([name.lower() for name in MOCK_AUTHOR_NAMES])
                params.extend([name.lower() for name in MOCK_AUTHOR_NAMES])
                clauses.append("COALESCE(f.is_deleted,0) = 0")
                if q:
                    pat = f"%{q}%"
                    clauses.append("(p.text LIKE ? OR p.author LIKE ? OR p.company LIKE ? OR p.keyword LIKE ?)")
                    params.extend([pat, pat, pat, pat])
                if clauses:
                    base += " WHERE " + " AND ".join(clauses)
                dir_sql = "ASC" if sort_direction == 1 else "DESC"
                base += f" ORDER BY p.{sort_field} {dir_sql} LIMIT ? OFFSET ?"
                params.extend([limit, skip])
                for r in conn.execute(base, params):
                    rows.append(dict(r))
            used_fallback = True
        # Ensure deleted posts filtered & favorites annotated for fallback path
        if used_fallback:
            rows = self._apply_sqlite_flags(ctx, rows, include_deleted=False)
        return rows

    async def count_posts(self, ctx, *, q: Optional[str] = None) -> int:
        if ctx.mongo_client:
            try:
                author_filter = {"$nin": [name for name in MOCK_AUTHOR_NAMES]}
                mf: dict[str, Any] = {"author": author_filter, "keyword": author_filter}
                if q:
                    mf.setdefault("$or", []).extend([
                        {"text": {"$regex": q, "$options": "i"}},
                        {"author": {"$regex": q, "$options": "i"}},
                        {"company": {"$regex": q, "$options": "i"}},
                        {"keyword": {"$regex": q, "$options": "i"}},
                    ])
                coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
                return await coll.count_documents(mf)
            except Exception:
                pass
        try:
            if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
                conn = sqlite3.connect(ctx.settings.sqlite_path)
                with conn:
                    self._ensure_post_flags(conn)
                    clauses: list[str] = []
                    params: list[Any] = []
                    placeholders = ",".join(["?"] * len(MOCK_AUTHOR_NAMES))
                    clauses.append(f"LOWER(p.author) NOT IN ({placeholders})")
                    clauses.append(f"LOWER(p.keyword) NOT IN ({placeholders})")
                    params.extend([name.lower() for name in MOCK_AUTHOR_NAMES])
                    params.extend([name.lower() for name in MOCK_AUTHOR_NAMES])
                    clauses.append("COALESCE(f.is_deleted,0) = 0")
                    if q:
                        clauses.append("(p.text LIKE ? OR p.author LIKE ? OR p.company LIKE ? OR p.keyword LIKE ?)")
                        pat = f"%{q}%"
                        params.extend([pat, pat, pat, pat])
                    base = "SELECT COUNT(*) FROM posts p LEFT JOIN post_flags f ON f.post_id = p.id"
                    if clauses:
                        base += " WHERE " + " AND ".join(clauses)
                    row = conn.execute(base, params).fetchone()
                    count_val = int(row[0]) if row else 0
                    return count_val
        except Exception:
            return 0
        return 0

    # --- internal helpers -------------------------------------------------
    @staticmethod
    def _ensure_post_flags(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS post_flags (
                post_id TEXT PRIMARY KEY,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                favorite_at TEXT,
                deleted_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_post_flags_deleted ON post_flags(is_deleted, deleted_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_post_flags_favorite ON post_flags(is_favorite, favorite_at)")

    def _apply_sqlite_flags(self, ctx, rows: list[dict[str, Any]], include_deleted: bool) -> list[dict[str, Any]]:
        if not rows:
            return rows
        path = getattr(ctx.settings, "sqlite_path", None)
        if not path or not Path(path).exists():
            return rows
        ids: list[str] = []
        for item in rows:
            pid = item.get("_id") or item.get("id")
            if pid is None:
                continue
            ids.append(str(pid))
        if not ids:
            return rows
        try:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            with conn:
                self._ensure_post_flags(conn)
                placeholders = ",".join(["?"] * len(ids))
                flag_rows = conn.execute(
                    f"SELECT post_id, is_favorite, is_deleted FROM post_flags WHERE post_id IN ({placeholders})",
                    ids,
                ).fetchall()
        except Exception:
            return rows
        flag_map = {
            str(row["post_id"]): {
                "is_favorite": int(row["is_favorite"] or 0),
                "is_deleted": int(row["is_deleted"] or 0),
            }
            for row in flag_rows
        }
        filtered: list[dict[str, Any]] = []
        for item in rows:
            pid_raw = item.get("_id") or item.get("id")
            pid = str(pid_raw) if pid_raw is not None else None
            if pid and pid in flag_map:
                flags = flag_map[pid]
                item["is_favorite"] = flags.get("is_favorite", 0)
                item["is_deleted"] = flags.get("is_deleted", 0)
                if not include_deleted and item["is_deleted"]:
                    continue
            else:
                item["is_favorite"] = int(item.get("is_favorite", 0) or 0)
                item["is_deleted"] = int(item.get("is_deleted", 0) or 0)
                if not include_deleted and item["is_deleted"]:
                    continue
            filtered.append(item)
        return filtered
