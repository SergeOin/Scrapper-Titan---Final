"""FastAPI route definitions for dashboard + API endpoints.

Endpoints:
- GET /              : Render dashboard (HTML)
- POST /trigger       : Enqueue a scraping job (keywords optional)
- GET /api/posts      : JSON listing with pagination
- GET /health         : Simple liveness check
- GET /metrics        : Prometheus metrics

Auth (optional): Basic auth if INTERNAL_AUTH_USER and INTERNAL_AUTH_PASS_HASH set.
"""
from __future__ import annotations

from functools import lru_cache
import contextlib
import io
from typing import Any, Optional
from pathlib import Path
import sqlite3
import json as _json
from datetime import datetime, timezone

import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Form, Query, Body
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from passlib.hash import bcrypt
import asyncio
import signal

from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from scraper.bootstrap import get_context
from scraper.utils import normalize_for_search as _normalize_for_search  # type: ignore
from scraper.session import session_status, login_via_playwright  # type: ignore
from scraper.bootstrap import _save_runtime_state  # type: ignore
from scraper.bootstrap import API_RATE_LIMIT_REJECTIONS
from .events import sse_event_iter, broadcast, EventType  # type: ignore
from fastapi.responses import RedirectResponse

router = APIRouter()

# Jinja templates setup (single dashboard page)
templates = Jinja2Templates(directory="server/templates")

# Register custom Jinja filters
def _fmt_date(value: Optional[str]):  # value expected ISO string
    if not value:
        return ""
    try:
        # Attempt parse ISO
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return value

templates.env.filters['fmt_date'] = _fmt_date

# ------------------------------------------------------------
# Optional internal auth dependency
# ------------------------------------------------------------
async def get_auth_context():
    ctx = await get_context()
    return ctx


def _auth_enabled(ctx) -> bool:
    return bool(ctx.settings.internal_auth_user and ctx.settings.internal_auth_pass_hash)


async def require_auth(request: Request, ctx=Depends(get_auth_context)):
    if not _auth_enabled(ctx):
        return  # Auth disabled
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("basic "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    import base64

    try:
        encoded = auth_header.split()[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        user, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    if user != ctx.settings.internal_auth_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if not bcrypt.verify(password, ctx.settings.internal_auth_pass_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return


# ------------------------------------------------------------
# LinkedIn session requirement for protected views
# ------------------------------------------------------------
async def require_linkedin_session(ctx=Depends(get_auth_context)):
    st = await session_status(ctx)
    if not st.valid:
        # Not logged-in: redirect to login page with an explicit reason
        raise HTTPException(status_code=302, headers={"Location": "/login?reason=session_expired"})
    return


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
@lru_cache(maxsize=1)
def _default_limit() -> int:
    return 20


def _sanitize_query(q: Optional[str]) -> Optional[str]:
    if q is None:
        return None
    q2 = q.strip()
    if not q2:
        return None
    # Clamp length to avoid heavy regex/LIKE
    return q2[:200]


def _normalize_sort(sort_by: Optional[str], sort_dir: Optional[str]) -> tuple[str, int]:
    allowed = {
        "collected_at": "collected_at",
        "published_at": "published_at",
        "author": "author",
        "company": "company",
        "keyword": "keyword",
    }
    field = allowed.get((sort_by or "").lower(), "collected_at")
    direction = -1 if (sort_dir or "").lower() == "desc" or not sort_dir else (1 if sort_dir.lower() == "asc" else -1)
    return field, direction


def _ensure_post_flags(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS post_flags (
        post_id TEXT PRIMARY KEY,
        is_favorite INTEGER NOT NULL DEFAULT 0,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        favorite_at TEXT,
        deleted_at TEXT
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_post_flags_deleted ON post_flags(is_deleted, deleted_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_post_flags_favorite ON post_flags(is_favorite, favorite_at)")


def _flags_for_ids(conn: sqlite3.Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    _ensure_post_flags(conn)
    placeholders = ",".join(["?"] * len(ids))
    rows = conn.execute(
        f"SELECT post_id, is_favorite, is_deleted, deleted_at FROM post_flags WHERE post_id IN ({placeholders})",
        ids,
    ).fetchall()
    return {
        row[0]: {
            "is_favorite": int(row[1] or 0),
            "is_deleted": int(row[2] or 0),
            "deleted_at": row[3],
        }
        for row in rows
    }


def _update_post_flags(ctx, post_id: str, *, favorite: Optional[bool] = None, deleted: Optional[bool] = None) -> dict[str, Any]:
    path = ctx.settings.sqlite_path
    if not path:
        raise HTTPException(status_code=400, detail="SQLite non configuré")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    with conn:
        _ensure_post_flags(conn)
        row = conn.execute(
            "SELECT post_id, is_favorite, is_deleted, favorite_at, deleted_at FROM post_flags WHERE post_id = ?",
            (post_id,),
        ).fetchone()
        current_favorite = int(row[1]) if row else 0
        current_deleted = int(row[2]) if row else 0
        favorite_at = row[3] if row else None
        deleted_at = row[4] if row else None
        now_iso = datetime.now(timezone.utc).isoformat()
        if favorite is not None:
            current_favorite = 1 if favorite else 0
            favorite_at = now_iso if current_favorite else None
        if deleted is not None:
            current_deleted = 1 if deleted else 0
            deleted_at = now_iso if current_deleted else None
        conn.execute(
            "INSERT INTO post_flags(post_id, is_favorite, is_deleted, favorite_at, deleted_at) VALUES(?,?,?,?,?)\n             ON CONFLICT(post_id) DO UPDATE SET is_favorite=excluded.is_favorite, is_deleted=excluded.is_deleted, favorite_at=excluded.favorite_at, deleted_at=excluded.deleted_at",
            (post_id, current_favorite, current_deleted, favorite_at, deleted_at),
        )
        updated = conn.execute(
            "SELECT post_id, is_favorite, is_deleted, deleted_at FROM post_flags WHERE post_id = ?",
            (post_id,),
        ).fetchone()
    if not updated:
        return {
            "post_id": post_id,
            "is_favorite": current_favorite,
            "is_deleted": current_deleted,
            "deleted_at": deleted_at,
        }
    return {
        "post_id": updated[0],
        "is_favorite": int(updated[1] or 0),
        "is_deleted": int(updated[2] or 0),
        "deleted_at": updated[3],
    }


def _count_deleted(ctx) -> int:
    path = ctx.settings.sqlite_path
    if not path or not Path(path).exists():
        return 0
    conn = sqlite3.connect(path)
    with conn:
        _ensure_post_flags(conn)
        row = conn.execute("SELECT COUNT(*) FROM post_flags WHERE is_deleted = 1").fetchone()
        return int(row[0]) if row else 0


def _fetch_deleted_posts(ctx) -> list[dict[str, Any]]:
    path = ctx.settings.sqlite_path
    if not path or not Path(path).exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows: list[dict[str, Any]] = []
    with conn:
        _ensure_post_flags(conn)
        query = (
            "SELECT p.id as _id, p.keyword, p.author, p.company, p.text, p.published_at, p.collected_at, p.permalink, "
            "COALESCE(f.is_favorite, 0) AS is_favorite, COALESCE(f.deleted_at, datetime('now')) AS deleted_at "
            "FROM posts p JOIN post_flags f ON f.post_id = p.id WHERE f.is_deleted = 1 "
            "ORDER BY f.deleted_at DESC"
        )
        for r in conn.execute(query):
            rows.append(dict(r))
    return rows

async def fetch_posts(ctx, skip: int, limit: int, q: Optional[str] = None, sort_by: Optional[str] = None, sort_dir: Optional[str] = None) -> list[dict[str, Any]]:
    q = _sanitize_query(q)
    sort_field, sort_direction = _normalize_sort(sort_by, sort_dir)
    # Mongo path
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
            # Always exclude legacy demo content
            mf: dict[str, Any] = {"author": {"$ne": "demo_recruteur"}, "keyword": {"$ne": "demo_recruteur"}}
            if q:
                mf["$or"] = [
                    {"text": {"$regex": q, "$options": "i"}},
                    {"author": {"$regex": q, "$options": "i"}},
                    {"company": {"$regex": q, "$options": "i"}},
                    {"keyword": {"$regex": q, "$options": "i"}},
                ]
            # Exclude raw + legacy score fields
            cursor = coll.find(mf, {"raw": 0, "score": 0, "recruitment_score": 0}).sort(sort_field, sort_direction).skip(skip).limit(limit)
            return [doc async for doc in cursor]
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("posts_query_failed", error=str(exc))
    # SQLite fallback
    rows: list[dict[str, Any]] = []
    try:
        if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
            conn = sqlite3.connect(ctx.settings.sqlite_path)
            conn.row_factory = sqlite3.Row
            with conn:
                # Ensure company column exists (migration-lite)
                try:
                    conn.execute("ALTER TABLE posts ADD COLUMN company TEXT")
                except Exception:
                    pass
                _ensure_post_flags(conn)
                base_q = (
                    "SELECT p.id as _id, p.keyword, p.author, p.author_profile, p.company, p.text, p.published_at, p.collected_at, "
                    "p.permalink, COALESCE(f.is_favorite,0) AS is_favorite, COALESCE(f.is_deleted,0) AS is_deleted "
                    "FROM posts p LEFT JOIN post_flags f ON f.post_id = p.id"
                )
                params: list[Any] = []
                # Base WHERE to exclude demo rows
                where_clauses = ["LOWER(p.author) <> 'demo_recruteur'", "LOWER(p.keyword) <> 'demo_recruteur'", "COALESCE(f.is_deleted,0) = 0"]
                if q:
                    # Prefer accent-insensitive search if search_norm exists
                    try:
                        # Check if search_norm column exists once per connection
                        cols = [r[1] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
                        if "search_norm" in cols:
                            # Prefer search_norm; for legacy rows where it's NULL, fallback to LIKE on original fields
                            where_clauses.append("(p.search_norm LIKE ? OR (p.search_norm IS NULL AND (p.text LIKE ? OR p.author LIKE ? OR p.company LIKE ? OR p.keyword LIKE ?)))")
                            qn = _normalize_for_search(q)
                            pat_norm = f"%{qn}%"
                            pat_raw = f"%{q}%"
                            params.extend([pat_norm, pat_raw, pat_raw, pat_raw, pat_raw])
                        else:
                            where_clauses.append("(p.text LIKE ? OR p.author LIKE ? OR p.company LIKE ? OR p.keyword LIKE ?)")
                            pat = f"%{q}%"
                            params.extend([pat, pat, pat, pat])
                    except Exception:
                        where_clauses.append("(p.text LIKE ? OR p.author LIKE ? OR p.company LIKE ? OR p.keyword LIKE ?)")
                        pat = f"%{q}%"
                        params.extend([pat, pat, pat, pat])
                if where_clauses:
                    base_q += " WHERE " + " AND ".join(where_clauses)
                # Order by requested field
                sqlite_field = f"p.{sort_field}"
                dir_sql = "ASC" if sort_direction == 1 else "DESC"
                base_q += f" ORDER BY COALESCE(f.is_favorite,0) DESC, {sqlite_field} {dir_sql} LIMIT ? OFFSET ?"
                params.extend([limit, skip])
                for r in conn.execute(base_q, params):
                    item = dict(r)
                    item["is_favorite"] = int(item.get("is_favorite", 0) or 0)
                    item["is_deleted"] = int(item.get("is_deleted", 0) or 0)
                    rows.append(item)
    except Exception as exc:  # pragma: no cover
        ctx.logger.warning("sqlite_fallback_query_failed", error=str(exc))

    # Apply flag annotations for mongo path or legacy rows
    try:
        if rows and ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
            conn = sqlite3.connect(ctx.settings.sqlite_path)
            with conn:
                ids = [str(item.get("_id")) for item in rows if item.get("_id")]
                flags = _flags_for_ids(conn, ids)
            reorder_needed = bool(rows) and "is_favorite" not in rows[0]
            filtered: list[dict[str, Any]] = []
            for item in rows:
                pid = str(item.get("_id")) if item.get("_id") else None
                flag = flags.get(pid) if pid else None
                if flag:
                    item["is_favorite"] = flag["is_favorite"]
                    item["is_deleted"] = flag["is_deleted"]
                    if flag["is_deleted"]:
                        continue
                else:
                    item.setdefault("is_favorite", 0)
                    item.setdefault("is_deleted", 0)
                filtered.append(item)
            if reorder_needed:
                favorites = [itm for itm in filtered if itm.get("is_favorite")]
                others = [itm for itm in filtered if not itm.get("is_favorite")]
                rows = favorites + others
            else:
                rows = filtered
    except Exception as exc:  # pragma: no cover
        ctx.logger.debug("flags_annotation_failed", error=str(exc))
    return rows


async def count_posts(ctx, q: Optional[str] = None) -> int:
    q = _sanitize_query(q)
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
            mf: dict[str, Any] = {"author": {"$ne": "demo_recruteur"}, "keyword": {"$ne": "demo_recruteur"}}
            if q:
                mf["$or"] = [
                    {"text": {"$regex": q, "$options": "i"}},
                    {"author": {"$regex": q, "$options": "i"}},
                    {"company": {"$regex": q, "$options": "i"}},
                    {"keyword": {"$regex": q, "$options": "i"}},
                ]
            return await coll.count_documents(mf)
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("posts_count_failed", error=str(exc))
            return 0
    # SQLite fallback
    try:
        if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
            conn = sqlite3.connect(ctx.settings.sqlite_path)
            with conn:
                # Exclude demo content unconditionally
                base_where = ["LOWER(p.author) <> 'demo_recruteur'", "LOWER(p.keyword) <> 'demo_recruteur'", "COALESCE(f.is_deleted,0) = 0"]
                params: list[Any] = []
                if q:
                    try:
                        cols = [r[1] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
                        if "search_norm" in cols:
                            qn = _normalize_for_search(q)
                            pat_norm = f"%{qn}%"
                            pat_raw = f"%{q}%"
                            base_where.append("(p.search_norm LIKE ? OR (p.search_norm IS NULL AND (p.text LIKE ? OR p.author LIKE ? OR p.company LIKE ? OR p.keyword LIKE ?)))")
                            params.extend([pat_norm, pat_raw, pat_raw, pat_raw, pat_raw])
                        else:
                            base_where.append("(p.text LIKE ? OR p.author LIKE ? OR p.company LIKE ? OR p.keyword LIKE ?)")
                            pat = f"%{q}%"
                            params.extend([pat, pat, pat, pat])
                    except Exception:
                        base_where.append("(p.text LIKE ? OR p.author LIKE ? OR p.company LIKE ? OR p.keyword LIKE ?)")
                        pat = f"%{q}%"
                        params.extend([pat, pat, pat, pat])
                query = (
                    "SELECT COUNT(*) FROM posts p LEFT JOIN post_flags f ON f.post_id = p.id"
                    + (" WHERE " + " AND ".join(base_where) if base_where else "")
                )
                row = conn.execute(query, params).fetchone()
                return int(row[0]) if row else 0
    except Exception:  # pragma: no cover
        return 0
    return 0


async def fetch_meta(ctx) -> dict[str, Any]:
    meta = {
        "last_run": None,
        "posts_count": 0,
        "scraping_enabled": ctx.settings.scraping_enabled,
        "pending_jobs": None,
        "keywords": ", ".join(ctx.settings.keywords),
    }
    # Mongo authoritative if present
    if ctx.mongo_client:
        try:
            mcoll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_meta]
            doc = await mcoll.find_one({"_id": "global"})
            if doc:
                meta.update({
                    "last_run": doc.get("last_run"),
                    "posts_count": doc.get("posts_count", 0),
                    "scraping_enabled": doc.get("scraping_enabled", meta["scraping_enabled"]),
                })
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("meta_query_failed", error=str(exc))
    else:
        # Approximate posts_count from SQLite if Mongo absent
        try:
            if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
                conn = sqlite3.connect(ctx.settings.sqlite_path)
                with conn:
                    _ensure_post_flags(conn)
                    c = conn.execute(
                        "SELECT COUNT(*) FROM posts p LEFT JOIN post_flags f ON f.post_id = p.id "
                        "WHERE LOWER(p.author) <> 'demo_recruteur' AND LOWER(p.keyword) <> 'demo_recruteur' AND COALESCE(f.is_deleted,0) = 0"
                    ).fetchone()
                    if c:
                        meta["posts_count"] = c[0]
        except Exception:  # pragma: no cover
            pass
    if ctx.redis:
        try:
            meta["pending_jobs"] = await ctx.redis.llen(ctx.settings.redis_queue_key)
        except Exception:  # pragma: no cover
            meta["pending_jobs"] = None
    return meta


# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(default_factory=_default_limit, ge=1, le=200),
    q: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query(None),
    ctx=Depends(get_auth_context),
    # min_score removed
    _auth=Depends(require_auth),  # enforce auth if enabled
    _ls=Depends(require_linkedin_session),  # require linkedin session
):
    skip = (page - 1) * limit
    posts = await fetch_posts(ctx, skip=skip, limit=limit, q=q, sort_by=sort_by, sort_dir=sort_dir)
    meta = await fetch_meta(ctx)
    trash_count = _count_deleted(ctx)
    # Compute naive total pages if meta count known
    if _sanitize_query(q):
        total = await count_posts(ctx, q)
    else:
        total = meta.get("posts_count", 0) or 0
    total_pages = max(1, (total // limit) + (1 if total % limit else 0)) if total else page
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "posts": posts,
            "meta": meta,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "q": _sanitize_query(q) or "",
            "autonomous_interval": ctx.settings.autonomous_worker_interval_seconds,
            "sort_by": (sort_by or "collected_at"),
            "sort_dir": (sort_dir or "desc"),
            "mock_mode": ctx.settings.playwright_mock_mode,
            "trash_count": trash_count,
        },
    )


def _format_iso_for_export(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value or ""


@router.get("/export/excel")
async def export_excel(
    page: int = Query(1, ge=1),
    limit: int = Query(1000, ge=1, le=5000),
    q: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query(None),
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
    _ls=Depends(require_linkedin_session),
):
    # Clamp limit defensively
    limit = min(limit, 5000)
    skip = (page - 1) * limit
    posts = await fetch_posts(ctx, skip=skip, limit=limit, q=q, sort_by=sort_by, sort_dir=sort_dir)
    rows: list[dict[str, Any]] = []
    for post in posts:
        rows.append({
            "Keyword": post.get("keyword", ""),
            "Auteur": post.get("author", ""),
            "Entreprise": post.get("company") or "",
            "Texte": post.get("text") or "",
            "Publié le": _format_iso_for_export(post.get("published_at")),
            "Collecté le": _format_iso_for_export(post.get("collected_at")),
            "Lien": post.get("permalink") or "",
        })
    columns = ["Keyword", "Auteur", "Entreprise", "Texte", "Publié le", "Collecté le", "Lien"]
    df = pd.DataFrame(rows, columns=columns)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Posts")
    buffer.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"linkedin_posts_{timestamp}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


_local_queue: asyncio.Queue[list[str]] | None = None
_local_worker_task: asyncio.Task | None = None


async def _local_worker(ctx):  # pragma: no cover (runtime behavior)
    logger = ctx.logger.bind(component="local_queue_worker")
    logger.info("local_worker_started")
    assert _local_queue is not None
    while True:
        kws = await _local_queue.get()
        try:
            from scraper.worker import process_job  # local import
            await process_job(kws, ctx)
            logger.info("local_job_complete", keywords=kws)
        except Exception as exc:
            logger.error("local_job_failed", error=str(exc))
        finally:
            _local_queue.task_done()


async def ensure_local_worker(ctx):
    global _local_queue, _local_worker_task
    if _local_queue is None:
        _local_queue = asyncio.Queue()
    if _local_worker_task is None or _local_worker_task.done():
        _local_worker_task = asyncio.create_task(_local_worker(ctx))


async def stop_local_worker():  # called from lifespan shutdown
    global _local_worker_task
    if _local_worker_task and not _local_worker_task.done():  # pragma: no cover
        _local_worker_task.cancel()
        with contextlib.suppress(Exception):
            await _local_worker_task


@router.post("/trigger")
async def trigger_scrape(
    request: Request,
    keywords: Optional[str] = Form(None),
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
):
    # Optional trigger token enforcement
    if ctx.settings.trigger_token:
        supplied = request.headers.get("X-Trigger-Token")
        if not supplied or supplied != ctx.settings.trigger_token:
            raise HTTPException(status_code=401, detail="Invalid trigger token")
    # Allow trigger in tests even if scraping is disabled; otherwise, enforce flag.
    import os
    if not ctx.settings.scraping_enabled and os.environ.get("PYTEST_CURRENT_TEST") is None:
        raise HTTPException(status_code=400, detail="Scraping désactivé")
    kws = ctx.settings.keywords
    if keywords:
        kws = [k.strip() for k in keywords.split(";") if k.strip()]
    payload = {"keywords": kws, "ts": datetime.now(timezone.utc).isoformat()}
    if ctx.redis:
        try:
            await ctx.redis.rpush(ctx.settings.redis_queue_key, json_dumps(payload))
            ctx.logger.info("job_enqueued", keywords=kws)
            return Response(status_code=202)
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("enqueue_failed", error=str(exc))
            raise HTTPException(status_code=500, detail="Queue indisponible")
    # No redis: enqueue locally and ensure single worker
    await ensure_local_worker(ctx)
    assert _local_queue is not None
    await _local_queue.put(kws)
    ctx.logger.warning("local_queue_enqueued", size=_local_queue.qsize())
    return Response(status_code=204)


@router.get("/api/posts")
async def api_posts(
    page: int = Query(1, ge=1),
    limit: int = Query(default_factory=_default_limit, ge=1, le=200),
    q: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query(None),
    ctx=Depends(get_auth_context),
    # min_score removed
    _auth=Depends(require_auth),
    _ls=Depends(require_linkedin_session),
):
    skip = (page - 1) * limit
    posts = await fetch_posts(ctx, skip=skip, limit=limit, q=q, sort_by=sort_by, sort_dir=sort_dir)
    return {"page": page, "limit": limit, "items": posts}


@router.post("/api/posts/{post_id}/favorite")
async def api_toggle_favorite(
    post_id: str,
    payload: dict[str, Any] = Body(...),
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
    _ls=Depends(require_linkedin_session),
):
    favorite = bool(payload.get("favorite", True))
    flags = _update_post_flags(ctx, post_id, favorite=favorite)
    return {"post_id": post_id, "is_favorite": flags.get("is_favorite", 0)}


@router.post("/api/posts/{post_id}/delete")
async def api_delete_post(
    post_id: str,
    payload: Optional[dict[str, Any]] = Body(None),
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
    _ls=Depends(require_linkedin_session),
):
    mark_deleted = True if payload is None else bool(payload.get("delete", True))
    flags = _update_post_flags(ctx, post_id, deleted=mark_deleted)
    return {
        "post_id": post_id,
        "is_deleted": flags.get("is_deleted", 0),
        "trash_count": _count_deleted(ctx),
    }


@router.post("/api/posts/{post_id}/restore")
async def api_restore_post(
    post_id: str,
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
    _ls=Depends(require_linkedin_session),
):
    flags = _update_post_flags(ctx, post_id, deleted=False)
    return {
        "post_id": post_id,
        "is_deleted": flags.get("is_deleted", 0),
        "trash_count": _count_deleted(ctx),
    }


@router.get("/api/trash/count")
async def api_trash_count(
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
    _ls=Depends(require_linkedin_session),
):
    return {"count": _count_deleted(ctx)}


@router.get("/corbeille", response_class=HTMLResponse)
async def trash_page(
    request: Request,
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
    _ls=Depends(require_linkedin_session),
):
    posts = _fetch_deleted_posts(ctx)
    return templates.TemplateResponse(
        "trash.html",
        {
            "request": request,
            "posts": posts,
            "trash_count": _count_deleted(ctx),
        },
    )


@router.get("/health")
async def health(ctx=Depends(get_auth_context)):
    # Base status
    data: dict[str, Any] = {
        "status": "ok",
        "mongo_connected": bool(ctx.mongo_client),
        "redis_connected": bool(ctx.redis),
    }
    # Mongo ping time + meta
    if ctx.mongo_client:
        import time as _time
        try:
            t0 = _time.perf_counter()
            await ctx.mongo_client.admin.command("ping")
            data["mongo_ping_ms"] = round((_time.perf_counter() - t0) * 1000, 2)
        except Exception as exc:  # pragma: no cover
            data["mongo_ping_ms"] = None
            data["mongo_error"] = str(exc)
    # Meta info (reuse existing helper)
    try:
        meta = await fetch_meta(ctx)
        data.update({
            "last_run": meta.get("last_run"),
            "posts_count": meta.get("posts_count", 0),
            "scraping_enabled": meta.get("scraping_enabled"),
            "keywords_count": len(ctx.settings.keywords),
        })
        lr = meta.get("last_run")
        if lr:
            try:
                dt = datetime.fromisoformat(lr.replace("Z", "+00:00"))
                age = datetime.now(timezone.utc) - dt
                data["last_run_age_seconds"] = int(age.total_seconds())
            except Exception:
                pass
    except Exception:  # pragma: no cover
        pass
    # Queue depth (redis)
    if ctx.redis:
        try:
            depth = await ctx.redis.llen(ctx.settings.redis_queue_key)
            data["queue_depth"] = depth
        except Exception:  # pragma: no cover
            data["queue_depth"] = None
    # Autonomous worker indicator
    data["autonomous_worker"] = ctx.settings.autonomous_worker_interval_seconds > 0
    # Augmented meta stats: last job unknown author metrics if present
    if ctx.mongo_client:
        try:
            mcoll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_meta]
            doc = await mcoll.find_one({"_id": "global"}, {"last_job_unknown_authors":1,"last_job_posts":1,"last_job_unknown_ratio":1})
            if doc:
                data["last_job_unknown_authors"] = doc.get("last_job_unknown_authors")
                data["last_job_posts"] = doc.get("last_job_posts")
                data["last_job_unknown_ratio"] = doc.get("last_job_unknown_ratio")
        except Exception:
            pass
    return data


@router.post("/shutdown")
async def shutdown(request: Request, ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Protected shutdown endpoint.

    Protection layers:
      1. If SHUTDOWN_TOKEN set, require header X-Shutdown-Token or query ?token=
      2. Requires basic auth if internal auth enabled.
    Returns 202 and schedules application shutdown after short delay.
    """
    if not ctx.settings.shutdown_token:
        raise HTTPException(status_code=403, detail="Shutdown token not configured")
    supplied = request.headers.get("X-Shutdown-Token") or request.query_params.get("token")
    if supplied != ctx.settings.shutdown_token:
        raise HTTPException(status_code=401, detail="Invalid shutdown token")
    loop = asyncio.get_running_loop()

    async def _delayed_stop():
        await asyncio.sleep(0.2)
        try:
            # Preferred: call loop.stop(). Uvicorn will handle graceful shutdown.
            loop.stop()
        except Exception:
            pass
    asyncio.create_task(_delayed_stop())
    return JSONResponse({"status": "accepted", "detail": "Shutdown scheduled"}, status_code=202)


@router.get("/metrics")
async def metrics(ctx=Depends(get_auth_context)):
    if not ctx.settings.enable_metrics:
        return Response(status_code=404)
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ------------------------------------------------------------
# Session management endpoints and login page
# ------------------------------------------------------------
@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    reason: Optional[str] = Query(None),
    ctx=Depends(get_auth_context),
):
    st = await session_status(ctx)
    message = None
    if reason == "session_expired":
        message = "Le scraper est arrêté car la session LinkedIn a expiré. Veuillez vous reconnecter."
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "session": st.details,
            "valid": st.valid,
            "reason_message": message,
        },
    )


@router.get("/api/session/status")
async def api_session_status(ctx=Depends(get_auth_context)):
    st = await session_status(ctx)
    return {"valid": st.valid, **st.details}




@router.post("/api/session/login")
async def api_session_login(email: str = Form(...), password: str = Form(...), mfa_code: str | None = Form(None), ctx=Depends(get_auth_context)):
    ok, diag = await login_via_playwright(ctx, email=email, password=password, mfa_code=mfa_code)
    if not ok:
        raise HTTPException(status_code=400, detail=diag)
    return {"ok": True, **diag}


@router.post("/api/session/logout")
async def api_session_logout(ctx=Depends(get_auth_context)):
    """Supprime l'état de session Playwright local pour forcer la reconnexion."""
    removed: list[str] = []
    for p in (ctx.settings.storage_state, ctx.settings.session_store_path):
        try:
            path = Path(p)
            if path.exists():
                path.unlink()
                removed.append(str(path))
        except Exception:
            pass
    return {"ok": True, "removed": removed}


@router.get("/logout")
async def logout_redirect(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Convenience route to logout Playwright session then redirect to login page.

    Does not require an active LinkedIn session (obviously) but enforces internal auth if enabled.
    """
    with contextlib.suppress(Exception):
        await api_session_logout(ctx)  # type: ignore[arg-type]
    return RedirectResponse(url="/login", status_code=302)


@router.post("/toggle")
async def toggle_scraping(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Inverse l'état `scraping_enabled` en mémoire et persiste dans Mongo si disponible.

    Retourne le nouvel état. Note: Ce réglage n'est pas encore persisté dans un fichier de config;
    il sera réinitialisé au redémarrage sur la valeur d'origine des settings d'environnement.
    """
    # Flip in-memory flag
    new_state = not ctx.settings.scraping_enabled
    ctx.settings.scraping_enabled = new_state  # type: ignore[attr-defined]
    # Persist in meta doc si Mongo
    if ctx.mongo_client:
        try:
            mcoll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_meta]
            await mcoll.update_one({"_id": "global"}, {"$set": {"scraping_enabled": new_state}}, upsert=True)
        except Exception as exc:  # pragma: no cover
            ctx.logger.warning("toggle_persist_failed", error=str(exc))
    # File persistence
    try:
        _save_runtime_state({"scraping_enabled": new_state})
    except Exception:  # pragma: no cover
        pass
    ctx.logger.info("scraping_toggled", scraping_enabled=new_state)
    # SSE broadcast (non bloquant best-effort)
    try:
        await broadcast({"type": EventType.TOGGLE, "scraping_enabled": new_state})
    except Exception:
        pass
    return {"scraping_enabled": new_state}


@router.get("/debug/auth")
async def debug_auth(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Diagnostic rapide authentification.

    Retourne:
      - existence fichier storage_state
      - taille fichier
      - paramètres login_initial_wait_seconds
      - mode mock
    """
    path = ctx.settings.storage_state
    exists = Path(path).exists()
    size = None
    if exists:
        try:
            size = Path(path).stat().st_size
        except Exception:
            pass
    return {
        "storage_state_path": path,
        "storage_state_exists": exists,
        "storage_state_size": size,
        "login_initial_wait_seconds": ctx.settings.login_initial_wait_seconds,
        "playwright_mock_mode": ctx.settings.playwright_mock_mode,
    }


@router.get("/debug/last_batch")
async def debug_last_batch(limit: int = 5, ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Return the most recent posts (author/company debug) limited to 'limit'.

    Fields: author, company, keyword, collected_at, published_at, permalink.
    Uses Mongo if available, else SQLite fallback. Does not expose raw text to keep payload small.
    """
    limit = max(1, min(50, limit))
    items: list[dict[str, Any]] = []
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
            cursor = coll.find({}, {"author":1, "company":1, "keyword":1, "collected_at":1, "published_at":1, "permalink":1}).sort("collected_at", -1).limit(limit)
            async for doc in cursor:
                items.append({
                    "author": doc.get("author"),
                    "company": doc.get("company"),
                    "keyword": doc.get("keyword"),
                    "collected_at": doc.get("collected_at"),
                    "published_at": doc.get("published_at"),
                    "permalink": doc.get("permalink"),
                })
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("debug_last_batch_mongo_failed", error=str(exc))
    if not items:
        # SQLite fallback
        try:
            if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
                conn = sqlite3.connect(ctx.settings.sqlite_path)
                conn.row_factory = sqlite3.Row
                with conn:
                    for r in conn.execute("SELECT author, company, keyword, collected_at, published_at, permalink FROM posts ORDER BY collected_at DESC LIMIT ?", (limit,)):
                        items.append(dict(r))
        except Exception as exc:  # pragma: no cover
            ctx.logger.warning("debug_last_batch_sqlite_failed", error=str(exc))
    return {"count": len(items), "items": items}


# Quick JSON dumps wrapper (use orjson if installed via FastAPI config) fallback
try:  # pragma: no cover - simple import gate
    import orjson  # type: ignore

    def json_dumps(o: Any) -> str:  # noqa: D401
        return orjson.dumps(o).decode("utf-8")
except Exception:  # pragma: no cover
    import json  # type: ignore

    def json_dumps(o: Any) -> str:  # type: ignore
        return json.dumps(o, ensure_ascii=False)


@router.get("/stream")
async def stream(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """SSE stream endpoint delivering real-time events.

    Client JS example:
        const es = new EventSource('/stream');
        es.onmessage = ev => { const payload = JSON.parse(ev.data); console.log(payload); };
    """
    from fastapi.responses import StreamingResponse
    return StreamingResponse(sse_event_iter(), media_type="text/event-stream")


@router.get("/api/stats")
async def api_stats(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Return aggregated runtime statistics.

    Combines settings flags + meta document + connectivity info. This endpoint is
    distinct from /health (which is a lightweight liveness + a subset of metrics).
    """
    data: dict[str, Any] = {
        "playwright_mock_mode": ctx.settings.playwright_mock_mode,
        "autonomous_interval": ctx.settings.autonomous_worker_interval_seconds,
        "scraping_enabled": ctx.settings.scraping_enabled,
        "keywords_count": len(ctx.settings.keywords),
        "mongo_connected": bool(ctx.mongo_client),
        "redis_connected": bool(ctx.redis),
    }
    # Meta (posts count, last_run)
    try:
        meta = await fetch_meta(ctx)
        data.update({
            "posts_count": meta.get("posts_count", 0),
            "last_run": meta.get("last_run"),
        })
    except Exception:  # pragma: no cover
        pass
    # Derive last_run_age_seconds
    lr = data.get("last_run")
    if lr:
        try:
            dt = datetime.fromisoformat(str(lr).replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - dt
            data["last_run_age_seconds"] = int(age.total_seconds())
        except Exception:  # pragma: no cover
            pass
    # Queue depth (redis)
    if ctx.redis:
        try:
            depth = await ctx.redis.llen(ctx.settings.redis_queue_key)
            data["queue_depth"] = depth
        except Exception:  # pragma: no cover
            data["queue_depth"] = None
    return data


@router.get("/api/version")
async def api_version(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Return build/version metadata for traceability.

    Values are sourced from environment variables:
        - APP_COMMIT: short or full git SHA injected at build/deploy time
        - BUILD_TIMESTAMP: ISO8601 UTC timestamp of the build
        - RENDER_GIT_COMMIT: (Render) auto-injected git SHA (fallback if APP_COMMIT absent)
        - RENDER_GIT_BRANCH: (Render) git branch name (used as timestamp fallback if none provided)
    Falls back to "unknown" if unset. This endpoint is lightweight and safe to
    poll for debugging or embedding in dashboards.
    """
    import os
    # Prefer explicit APP_COMMIT if you've injected it; otherwise fall back to Render's auto variable.
    commit = os.environ.get("APP_COMMIT") or os.environ.get("RENDER_GIT_COMMIT") or "unknown"
    # BUILD_TIMESTAMP can be provided by your CI; otherwise we expose branch name as a weak proxy.
    ts = os.environ.get("BUILD_TIMESTAMP") or os.environ.get("RENDER_GIT_BRANCH") or "unknown"
    return {
        "app_commit": commit,
        "build_timestamp": ts,
        "playwright_mock_mode": ctx.settings.playwright_mock_mode,
    }
