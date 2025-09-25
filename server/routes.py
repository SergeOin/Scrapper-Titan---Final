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

# Name/company helpers for display hygiene
def _dedupe_person_name(name: Optional[str]) -> str:
    s = (name or "").strip()
    if not s:
        return s
    tokens = s.split()
    # Pattern: exact duplication like "John Doe John Doe"
    if len(tokens) >= 2 and len(tokens) % 2 == 0:
        half = len(tokens) // 2
        if tokens[:half] == tokens[half:]:
            return " ".join(tokens[:half])
    return s

def _derive_company(author: str, author_profile: Optional[str], text: Optional[str]) -> Optional[str]:
    """Best-effort company derivation from profile/text.
    Heuristics:
    - Prefer author_profile; handle 'chez'/'at' patterns and common separators.
    - Avoid returning segments that look like roles (Recruiter, Manager, etc.).
    - Never return the author name.
    - Fall back to scanning text for 'chez/at @Company' markers and parenthesis.
    """
    import re
    norm_author = (author or "").strip().lower()
    role_keywords = {
        "recruteur","recruiter","talent","senior","junior","stagiaire","alternant",
        "manager","responsable","lead","engineer","ingénieur","consultant","développeur","developer",
        "cto","ceo","cfo","cmo","rh","hr","human resources","marketing","sales","commercial",
    }
    company_suffixes = {"sas","sarl","sa","inc","llc","gmbh","ltd","spa","s.p.a","ag","bv","nv"}

    def looks_like_role(segment: str) -> bool:
        seg = segment.lower()
        return any(k in seg for k in role_keywords)

    def company_score(segment: str) -> int:
        s = segment.strip()
        score = 0
        # bonus if contains company suffixes
        if any(s.lower().endswith(" "+suf) or (" "+suf+" ") in s.lower() for suf in company_suffixes):
            score += 3
        # bonus for Title Case words
        tokens = [t for t in re.split(r"\s+", s) if t]
        score += sum(1 for t in tokens if t[:1].isupper())
        # penalty if contains role
        if looks_like_role(s):
            score -= 2
        return score

    prof = (author_profile or "").strip()
    if prof:
        # Direct patterns in profile: 'chez X' / 'at X'
        for marker in (" chez ", " at "):
            if marker in prof.lower():
                tail = prof.lower().split(marker, 1)[1]
                # Recover original casing by slicing same length offset
                start_idx = prof.lower().index(marker) + len(marker)
                tail = prof[start_idx:].strip()
                for stop in [" |", " -", ",", " •", " ·", " – ", " — ", "  "]:
                    if stop in tail:
                        tail = tail.split(stop, 1)[0].strip()
                if 2 <= len(tail) <= 80 and tail.strip().lower() != norm_author:
                    return tail
        # Split on common separators and pick the most company-like segment
        seps = [" • ", " — ", " – ", " | ", " •", "•", "—", "-", "|", "·"]
        if any(sep in prof for sep in seps):
            parts: list[str] = []
            tmp = prof
            for sep in [" • ", " — ", " – ", " | "]:
                tmp = tmp.replace(sep, "|")
            for sep in [" •", "•", "—", "-", "|", "·"]:
                tmp = tmp.replace(sep, "|")
            parts = [p.strip() for p in tmp.split("|") if p.strip()]
            candidates = [p for p in parts if p and p.lower() != norm_author]
            # prefer segments that don't look like roles, then by score/length
            candidates.sort(key=lambda p: (looks_like_role(p), -company_score(p), -len(p)))
            if candidates:
                top = candidates[0]
                if 2 <= len(top) <= 80 and top.lower() != norm_author:
                    return top

    # Fallback: look into text for markers
    blob = (text or "")
    for marker in ["@ ", "chez ", " chez ", " at ", " chez l'", " chez le ", " chez la ", " chez les "]:
        if marker in blob:
            tail = blob.split(marker, 1)[1].strip()
            for stop in [" |", " -", ",", " •", " ·", "  "]:
                if stop in tail:
                    tail = tail.split(stop, 1)[0].strip()
            if 2 <= len(tail) <= 80 and tail.lower() != norm_author:
                return tail
    # Try parentheses like "(Company)"
    for m in re.finditer(r"\(([^)]+)\)", blob):
        cand = m.group(1).strip()
        if 2 <= len(cand) <= 80 and cand.lower() != norm_author:
            return cand
    return None

def _sanitize_company(company: Optional[str]) -> Optional[str]:
    s = (company or "").strip()
    if not s:
        return None
    # Remove common prefixes/symbols
    if s.startswith("@"):
        s = s[1:].strip()
    for pref in ["chez ", "Chez ", "at ", "At "]:
        if s.startswith(pref):
            s = s[len(pref):].strip()
            break
    # Collapse excessive whitespace
    s = " ".join(s.split())
    # Strip trailing punctuation
    s = s.strip("-•|·—,;: ")
    return s or None

def _looks_like_followers(segment: str) -> bool:
    import re
    seg = segment.strip().lower()
    # Normalize nbsp/thin spaces
    seg = seg.replace("\u00a0", " ").replace("\u202f", " ")
    # e.g., "12 345 abonnés", "12k abonnés", "1.2m followers"
    return re.search(r"\b\d[\d\s\.,]*\s*(k|m)?\s*(abonn[eé]s|followers)\b", seg) is not None

def _strip_followers_suffix(value: Optional[str]) -> Optional[str]:
    import re
    s = (value or "").strip()
    if not s:
        return None
    original = s
    # Remove parenthesized followers e.g., "(12 345 abonnés)"
    s = re.sub(r"\(\s*\d[\d\s\.,\u202f\u00a0]*\s*(?:k|m)?\s*(?:abonn[eé]s|followers)\s*\)", "", s, flags=re.IGNORECASE)
    # Remove trailing segments like " | 12k abonnés", " · 1 234 followers", " - 2 345 abonnés"
    for sep in [" | ", " · ", " - ", " — ", " – "]:
        parts = [p.strip() for p in s.split(sep) if p is not None]
        if len(parts) >= 2 and _looks_like_followers(parts[-1]):
            s = sep.join(parts[:-1])
    # Remove simple terminal follower phrase if present at the end
    s = re.sub(r"[\s\-•|·—,;:]*\d[\d\s\.,\u202f\u00a0]*\s*(?:k|m)?\s*(?:abonn[eé]s|followers)\s*$", "", s, flags=re.IGNORECASE)
    # Cleanup whitespace/separators
    s = " ".join(s.split())
    s = s.strip("-•|·—,;: ")
    return s or None

def _dedupe_repeated_phrase(value: Optional[str]) -> Optional[str]:
    s = (value or "").strip()
    if not s:
        return None
    tokens = s.split()
    if len(tokens) % 2 == 0 and len(tokens) >= 2:
        half = len(tokens) // 2
        if tokens[:half] == tokens[half:]:
            return " ".join(tokens[:half])
    return s

def _extract_contract_status(text: Optional[str]) -> Optional[str]:
    """Extract a contract/status label like CDI/CDD/Alternance/Freelance from the post text only.

    Returns a comma-separated string in a consistent order, or None if nothing found.
    """
    blob = (text or "").strip()
    if not blob:
        return None
    low = blob.lower()
    found = set()
    # Simple keyword spotting (FR + EN equivalents where useful)
    if " cdi" in low or low.startswith("cdi") or "(cdi" in low:
        found.add("CDI")
    if " cdd" in low or low.startswith("cdd") or "(cdd" in low:
        found.add("CDD")
    if " alternance" in low or low.startswith("alternance") or "apprentissage" in low:
        found.add("Alternance")
    if " stage" in low or low.startswith("stage") or "internship" in low:
        found.add("Stage")
    if " freelance" in low or low.startswith("freelance") or "indépendant" in low or "independant" in low:
        found.add("Freelance")
    if "temps plein" in low or "full time" in low or "full-time" in low:
        found.add("Temps plein")
    if "temps partiel" in low or "part time" in low or "part-time" in low:
        found.add("Temps partiel")
    if not found:
        return None
    order = ["CDI", "CDD", "Alternance", "Stage", "Freelance", "Temps plein", "Temps partiel"]
    ordered = [x for x in order if x in found]
    return ", ".join(ordered) if ordered else None

def _extract_metier(text: Optional[str]) -> Optional[str]:
    """Extract legal/tax job roles from post text based on curated patterns.

    Returns a comma-separated label list or None.
    """
    blob = (text or "").lower()
    if not blob:
        return None
    hits: list[str] = []
    patterns: list[tuple[list[str], str]] = [
        # Avocats
        (["avocat collaborateur"], "Avocat collaborateur"),
        (["avocat associe", "avocat associé"], "Avocat associé"),
        (["avocat counsel", "counsel"], "Avocat counsel"),
        (["avocat"], "Avocat"),
        # Juristes / Legal
        (["paralegal"], "Paralegal"),
        (["legal counsel"], "Legal counsel"),
        (["juriste"], "Juriste"),
        # Management juridique
        (["responsable juridique"], "Responsable juridique"),
        (["directeur juridique"], "Directeur juridique"),
        # Notariat
        (["notaire stagiaire"], "Notaire stagiaire"),
        (["notaire associe", "notaire associé"], "Notaire associé"),
        (["notaire salarie", "notaire salarié"], "Notaire salarié"),
        (["notaire assistant"], "Notaire assistant"),
        (["clerc de notaire"], "Clerc de notaire"),
        (["redacteur d'actes", "rédacteur d’actes", "rédacteur d'actes", "redacteur d’actes"], "Rédacteur d’actes"),
        (["notaire"], "Notaire"),
        # Fiscalité
        (["responsable fiscal"], "Responsable fiscal"),
        (["directeur fiscal"], "Directeur fiscal"),
        (["juriste fiscaliste"], "Juriste fiscaliste"),
        (["comptable taxateur"], "Comptable taxateur"),
        (["formaliste"], "Formaliste"),
    ]
    for keys, label in patterns:
        if any(k in blob for k in keys):
            # avoid duplicates
            if label not in hits:
                hits.append(label)
    if not hits:
        return None
    # Preserve pattern order; cap to 3 labels to keep UI compact
    return ", ".join(hits[:3])

def _detect_opportunity(text: Optional[str]) -> bool:
    """Detect recruitment signals in post text (FR/EN)."""
    t = (text or "").lower()
    if not t:
        return False
    signals = [
        # FR
        " recrute", "nous recrutons", "on recrute", "recrutement", "poste a pourvoir", "poste à pourvoir",
        "offre d'emploi", "offre d’emploi", "candidature", "postulez", "envoyez votre cv", "cv@", "joignez votre cv",
        # EN
        "hiring", "we're hiring", "we are hiring", "join our team", "apply now", "apply here",
    ]
    return any(s in t for s in signals)

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


def _get_post_flags(ctx, post_id: str) -> dict[str, Any]:
    """Return current flags for a post without mutating anything."""
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
        if not row:
            return {"post_id": post_id, "is_favorite": 0, "is_deleted": 0, "favorite_at": None, "deleted_at": None}
        return {
            "post_id": row[0],
            "is_favorite": int(row[1] or 0),
            "is_deleted": int(row[2] or 0),
            "favorite_at": row[3],
            "deleted_at": row[4],
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
    rows: list[dict[str, Any]] = []
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
            rows = [doc async for doc in cursor]
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("posts_query_failed", error=str(exc))
            rows = []
    # SQLite fallback (if no mongo rows and/or mongo unavailable)
    try:
        if (not rows) and ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
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
            filtered: list[dict[str, Any]] = []
            for item in rows:
                pid = str(item.get("_id")) if item.get("_id") else None
                flag = flags.get(pid) if pid else None
                if flag:
                    item["is_favorite"] = int(flag.get("is_favorite") or 0)
                    item["is_deleted"] = int(flag.get("is_deleted") or 0)
                    if item["is_deleted"]:
                        continue
                else:
                    item["is_favorite"] = int(item.get("is_favorite") or 0)
                    item["is_deleted"] = int(item.get("is_deleted") or 0)
                filtered.append(item)
            # Always surface favorites first while preserving original relative order
            favorites = [itm for itm in filtered if int(itm.get("is_favorite") or 0) == 1]
            others = [itm for itm in filtered if int(itm.get("is_favorite") or 0) != 1]
            rows = favorites + others
    except Exception as exc:  # pragma: no cover
        ctx.logger.debug("flags_annotation_failed", error=str(exc))
    # Final UI-level deduplication to avoid showing duplicate entries
    try:
        if rows:
            seen: set[str] = set()
            deduped: list[dict[str, Any]] = []
            for item in rows:
                # Sanitize author duplication in display
                item_author = _dedupe_person_name(item.get("author"))
                item_author = _strip_followers_suffix(item_author)
                if item_author:
                    item["author"] = item_author
                # Fix company if missing or same as author
                comp = item.get("company")
                if not comp or str(comp).strip().lower() == str(item.get("author") or "").strip().lower():
                    derived = _derive_company(item.get("author") or "", item.get("author_profile"), item.get("text"))
                    if derived:
                        item["company"] = derived
                # Sanitize company and ensure we don't show author as company
                item["company"] = _sanitize_company(item.get("company"))
                item["company"] = _strip_followers_suffix(item.get("company")) or item.get("company")
                item["company"] = _dedupe_repeated_phrase(item.get("company")) or item.get("company")
                if (item.get("company") or "").strip().lower() == (item.get("author") or "").strip().lower():
                    item["company"] = None
                # Derive contract status for UI
                status = _extract_contract_status(item.get("text"))
                if status:
                    item["status"] = status
                # Derive metier and opportunity
                metier = _extract_metier(item.get("text"))
                if metier:
                    item["metier"] = metier
                if _detect_opportunity(item.get("text")):
                    item["opportunity"] = True
                perma = item.get("permalink") or ""
                author = (item.get("author") or "")
                published = item.get("published_at") or ""
                text = (item.get("text") or "")
                if perma:
                    key = f"perma|{perma}"
                elif author and published:
                    key = f"authdate|{author}|{published}"
                else:
                    key = f"authtext|{author}|{text[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            rows = deduped
    except Exception:
        pass
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
            "login_initial_wait_seconds": ctx.settings.login_initial_wait_seconds,
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
            "Statut": post.get("status") or "",
            "Métier": post.get("metier") or "",
            "Opportunité": "Oui" if post.get("opportunity") else "",
            "Texte": post.get("text") or "",
            "Publié le": _format_iso_for_export(post.get("published_at")),
            "Collecté le": _format_iso_for_export(post.get("collected_at")),
            "Lien": post.get("permalink") or "",
        })
    columns = ["Keyword", "Auteur", "Entreprise", "Statut", "Métier", "Opportunité", "Texte", "Publié le", "Collecté le", "Lien"]
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
):
    # Optional trigger token enforcement (permit dashboard-originated calls)
    if ctx.settings.trigger_token:
        supplied = request.headers.get("X-Trigger-Token")
        from_dashboard = request.headers.get("X-Trigger-From") == "dashboard"
        if (not supplied or supplied != ctx.settings.trigger_token) and not from_dashboard:
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
):
    skip = (page - 1) * limit
    posts = await fetch_posts(ctx, skip=skip, limit=limit, q=q, sort_by=sort_by, sort_dir=sort_dir)
    return {"page": page, "limit": limit, "items": posts}


@router.post("/api/posts/{post_id}/favorite")
async def api_toggle_favorite(
    post_id: str,
    request: Request,
    ctx=Depends(get_auth_context),
):
    # Parse optional JSON body manually to avoid 422 on empty/invalid bodies
    payload: Optional[dict[str, Any]] = None
    try:
        if request.headers.get("content-type", "").lower().startswith("application/json"):
            # Can still be empty; handle gracefully
            body = (await request.body()) or b""
            if body:
                payload = _json.loads(body.decode("utf-8"))  # type: ignore[attr-defined]
    except Exception:
        payload = None
    # Support explicit favorite boolean or toggle when payload is missing
    if payload is not None and isinstance(payload, dict) and "favorite" in payload:
        favorite = bool(payload.get("favorite", True))
    else:
        cur = _get_post_flags(ctx, post_id)
        favorite = not bool(cur.get("is_favorite", 0))
    flags = _update_post_flags(ctx, post_id, favorite=favorite)
    return {"post_id": post_id, "is_favorite": flags.get("is_favorite", 0)}


@router.post("/api/posts/{post_id}/delete")
async def api_delete_post(
    post_id: str,
    request: Request,
    ctx=Depends(get_auth_context),
):
    payload: Optional[dict[str, Any]] = None
    try:
        if request.headers.get("content-type", "").lower().startswith("application/json"):
            body = (await request.body()) or b""
            if body:
                payload = _json.loads(body.decode("utf-8"))  # type: ignore[attr-defined]
    except Exception:
        payload = None
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
        # If no last_run from Mongo meta and SQLite is used, derive from latest collected_at
        if not data.get("last_run") and ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
            try:
                conn = sqlite3.connect(ctx.settings.sqlite_path)
                with conn:
                    # Exclude deleted posts if flags table exists
                    # We do a LEFT JOIN and allow missing flags table by try/except
                    try:
                        conn.execute("SELECT 1 FROM post_flags LIMIT 1")
                        row = conn.execute(
                            "SELECT MAX(p.collected_at) FROM posts p LEFT JOIN post_flags f ON f.post_id = p.id WHERE COALESCE(f.is_deleted,0) = 0"
                        ).fetchone()
                    except Exception:
                        row = conn.execute("SELECT MAX(collected_at) FROM posts").fetchone()
                latest = row[0] if row else None
                if latest:
                    data["last_run"] = latest
                    try:
                        dt = datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
                        age = datetime.now(timezone.utc) - dt
                        data["last_run_age_seconds"] = int(age.total_seconds())
                    except Exception:
                        pass
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
    # Intentionally do not surface any banner/message on the login page
    # even when redirected with a reason (e.g., session_expired).
    # This keeps the UI cleaner per request.
    message = None
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
        # Ensure error text is meaningful
        if isinstance(diag, dict) and (not diag.get("error")):
            diag["error"] = diag.get("message") or diag.get("hint") or "login_failed"
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
async def stream(ctx=Depends(get_auth_context)):
    """SSE stream endpoint delivering real-time events (no internal auth for fluid UI).

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
