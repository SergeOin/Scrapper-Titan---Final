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

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Form, Query, Body
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound  # runtime safeguard for missing templates
from passlib.hash import bcrypt
import asyncio
import signal

from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from scraper.bootstrap import get_context
from scraper.utils import normalize_for_search as _normalize_for_search  # type: ignore
from scraper import utils as _scrape_utils  # unified opportunity logic
from scraper.session import session_status, login_via_playwright  # type: ignore
from scraper.bootstrap import _save_runtime_state  # type: ignore
from scraper.bootstrap import API_RATE_LIMIT_REJECTIONS
from .events import sse_event_iter, broadcast, EventType  # type: ignore
from fastapi.responses import RedirectResponse

router = APIRouter()

# Attempt optional desktop IPC import (safe if not present)
try:  # pragma: no cover - dynamic environment
    from desktop import ipc as _desktop_ipc  # type: ignore
except Exception:  # pragma: no cover
    _desktop_ipc = None  # type: ignore

# Jinja templates setup (single dashboard page)
# Robust path resolution: when packaged (PyInstaller) the working directory may not be
# the project root, so using a relative string like "server/templates" can break and
# produce a 500 on first page load. We resolve relative to this file's location.
_THIS_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _THIS_DIR / "templates"
if not _TEMPLATE_DIR.exists():  # Fallback strategies for frozen/shortcut launch contexts
    candidates = []
    # 1. CWD/server/templates (already tried previously as 'alt')
    candidates.append(Path.cwd() / "server" / "templates")
    # 2. Executable directory (PyInstaller one-folder) sibling path
    try:
        import sys as _sys
        if getattr(_sys, "frozen", False):
            exe_dir = Path(_sys.executable).parent
            candidates.append(exe_dir / "server" / "templates")
            # PyInstaller may also unpack to _MEIPASS – include it
            meipass = Path(getattr(_sys, "_MEIPASS", exe_dir))  # type: ignore[attr-defined]
            candidates.append(meipass / "server" / "templates")
            candidates.append(exe_dir / "_internal" / "server" / "templates")
    except Exception:
        pass
    # 3. Walk upwards a few levels (defensive) looking for server/templates
    try:
        cur = Path.cwd()
        for _ in range(4):
            cand = cur / "server" / "templates"
            candidates.append(cand)
            cur = cur.parent
    except Exception:
        pass
    for c in candidates:
        if c.exists():
            _TEMPLATE_DIR = c
            break

try:
    import logging as _logging
    _logging.getLogger("server").info(
        "templates_init", chosen=str(_TEMPLATE_DIR), exists=_TEMPLATE_DIR.exists(), cwd=str(Path.cwd())
    )
    # Extra diagnostics for packaged environments where login.html was reported missing
    if _TEMPLATE_DIR.exists():
        # list a few files
        sample = sorted([p.name for p in _TEMPLATE_DIR.glob('*.html')])[:5]
        _logging.getLogger("server").info("templates_sample", sample=sample)
except Exception:
    pass

templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

# Additional explicit diagnostics for key template presence (login/dashboard) so desktop logs
# clearly show root cause instead of only raising TemplateNotFound during first request.
try:  # pragma: no cover - diagnostics only
    import logging as _logging2
    for _name in ["login.html", "dashboard.html", "trash.html"]:
        _exists = (_TEMPLATE_DIR / _name).exists()
        _logging2.getLogger("server").info(
            "template_probe", name=_name, exists=_exists, dir=str(_TEMPLATE_DIR)
        )
except Exception:
    pass

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
# Store for blocked LinkedIn accounts (Mongo if available, else SQLite)
# Document: { id/_id: str, name: str | None, url: str, blocked_at: ISO8601 }
# ------------------------------------------------------------
from uuid import uuid4

def _normalize_linkedin_url(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return s
    # Accept either full URL or identifier; try to coerce to canonical https URL
    # Supported forms: linkedin.com/in/username, /in/username, username, or company pages
    v = s
    # If it looks like only an identifier (no slash), assume /in/<id>
    if 'linkedin.com' not in v:
        # Allow forms like in/username or company/slug too
        if v.startswith('in/') or v.startswith('company/'):
            v = f"https://www.linkedin.com/{v}"
        elif v.startswith('/'):
            v = f"https://www.linkedin.com{v}"
        else:
            v = f"https://www.linkedin.com/in/{v}"
    # Ensure scheme
    if not v.startswith('http://') and not v.startswith('https://'):
        v = 'https://' + v.lstrip('/')
    # Strip query/fragment and trailing slash
    try:
        from urllib.parse import urlparse, urlunparse
        pr = urlparse(v)
        # Only accept linkedin hostnames for safety
        host = (pr.netloc or '').lower()
        if 'linkedin.' not in host:
            # Treat as invalid by returning empty string
            return ''
        cleaned = pr._replace(query='', fragment='')
        out = urlunparse(cleaned).rstrip('/')
        return out
    except Exception:
        return ''

# Lightweight helper to extract a comparable name/slug from a LinkedIn URL.
# Examples:
#  - https://www.linkedin.com/company/law-profiler/ -> "law profiler"
#  - https://www.linkedin.com/in/john-doe -> "john doe"
# If parsing fails, returns a normalized last non-empty path segment.
def _blocked_slug_from_url(url: str) -> str:
    try:
        from urllib.parse import urlparse, unquote
        p = urlparse(url or "")
        parts = [seg for seg in (p.path or "").split('/') if seg]
        slug = ""
        if parts:
            # Prefer segment after known prefixes like 'company' or 'in'
            for pref in ("company", "in", "school", "pages"):
                if pref in parts:
                    idx = parts.index(pref)
                    if idx + 1 < len(parts):
                        slug = parts[idx + 1]
                        break
            if not slug:
                slug = parts[-1]
        slug = unquote(slug)
        # Transform dashes/underscores to spaces then normalize accents/case
        slug = slug.replace('-', ' ').replace('_', ' ')
        try:
            from scraper.utils import normalize_for_search as _nfs  # type: ignore
            return _nfs(slug)
        except Exception:
            return (slug or "").strip().lower()
    except Exception:
        return ""

async def _blocked_count(ctx) -> int:
    # Mongo path
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db]["blocked_accounts"]
            return await coll.count_documents({})
        except Exception:
            return 0
    # SQLite path
    path = ctx.settings.sqlite_path
    if not path or not Path(path).exists():
        return 0
    conn = sqlite3.connect(path)
    with conn:
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS blocked_accounts (id TEXT PRIMARY KEY, url TEXT UNIQUE, name TEXT, blocked_at TEXT)")
        except Exception:
            pass
        row = conn.execute("SELECT COUNT(*) FROM blocked_accounts").fetchone()
        return int(row[0] or 0)


async def _blocked_list(ctx) -> list[dict[str, Any]]:
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db]["blocked_accounts"]
            cursor = coll.find({}, {"_id": 1, "url": 1, "blocked_at": 1}).sort("blocked_at", -1)
            items: list[dict[str, Any]] = []
            async for doc in cursor:
                items.append({
                    "id": str(doc.get("_id")),
                    "url": doc.get("url"),
                    "blocked_at": doc.get("blocked_at"),
                })
            return items
        except Exception:
            return []
    # SQLite
    path = ctx.settings.sqlite_path
    if not path or not Path(path).exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    with conn:
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS blocked_accounts (id TEXT PRIMARY KEY, url TEXT UNIQUE, name TEXT, blocked_at TEXT)")
        except Exception:
            pass
        rows = conn.execute("SELECT id, url, blocked_at FROM blocked_accounts ORDER BY blocked_at DESC").fetchall()
        return [dict(r) for r in rows]


async def _blocked_add(ctx, url: str):
    now_iso = datetime.now(timezone.utc).isoformat()
    item_id = str(uuid4())
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db]["blocked_accounts"]
            # Unique by url: check duplicate
            exists = await coll.find_one({"url": url})
            if exists:
                raise HTTPException(status_code=409, detail="Ce compte est déjà bloqué")
            doc = {"_id": item_id, "url": url, "blocked_at": now_iso}
            await coll.insert_one(doc)
            return {"id": item_id, "url": url, "blocked_at": now_iso}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Erreur d'insertion: {exc}")
    # SQLite
    path = ctx.settings.sqlite_path
    if not path:
        raise HTTPException(status_code=400, detail="SQLite non configuré")
    conn = sqlite3.connect(path)
    with conn:
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS blocked_accounts (id TEXT PRIMARY KEY, url TEXT UNIQUE, name TEXT, blocked_at TEXT)")
            conn.execute(
                "INSERT INTO blocked_accounts(id, url, name, blocked_at) VALUES(?,?,?,?)",
                (item_id, url, None, now_iso),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Ce compte est déjà bloqué")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Erreur d'insertion: {exc}")
    return {"id": item_id, "url": url, "blocked_at": now_iso}


async def _blocked_delete(ctx, item_id: str):
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db]["blocked_accounts"]
            res = await coll.delete_one({"_id": item_id})
            if not getattr(res, 'deleted_count', 0):
                raise HTTPException(status_code=404, detail="Compte introuvable")
            return
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Erreur suppression: {exc}")
    # SQLite
    path = ctx.settings.sqlite_path
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Compte introuvable")
    conn = sqlite3.connect(path)
    with conn:
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS blocked_accounts (id TEXT PRIMARY KEY, url TEXT UNIQUE, name TEXT, blocked_at TEXT)")
            res = conn.execute("DELETE FROM blocked_accounts WHERE id = ?", (item_id,))
            if res.rowcount == 0:
                raise HTTPException(status_code=404, detail="Compte introuvable")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Erreur suppression: {exc}")

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

def _looks_like_followers(segment: str) -> bool:
    import re
    seg = segment.strip().lower()
    seg = seg.replace("\u00a0", " ").replace("\u202f", " ")
    # Accept forms: 12 345 abonnés, 12k abonnés, 1.2m followers, 123 abonnés (singular/plural tolerant)
    return re.search(r"\b\d[\d\s\.,]*\s*(k|m)?\s*(abonn[eé]s?|followers)\b", seg, flags=re.IGNORECASE) is not None

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
    # Last resort: inspect author string itself for patterns "Nom Prénom • Entreprise" or "Nom chez Entreprise"
    author_clean = (author or "").strip()
    if author_clean:
        lc = author_clean.lower()
        for marker in [" chez ", " at "]:
            if marker in lc:
                tail = author_clean[lc.index(marker)+len(marker):].strip()
                for stop in [" |", " -", ",", " •", " ·", " —", " –", " (", "  "]:
                    if stop in tail:
                        tail = tail.split(stop, 1)[0].strip()
                if 2 <= len(tail) <= 80 and tail.lower() != norm_author and not looks_like_role(tail):
                    return tail
        for sep in [" • ", " – ", " — ", " | ", " - "]:
            if sep in author_clean:
                parts = [p.strip() for p in author_clean.split(sep) if p.strip()]
                if len(parts) >= 2:
                    cand2 = parts[-1]
                    if 2 <= len(cand2) <= 80 and cand2.lower() != norm_author and not looks_like_role(cand2):
                        return cand2
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

def _strip_followers_suffix(value: Optional[str]) -> Optional[str]:
    import re
    s = (value or "").strip()
    if not s:
        return None
    # Remove parenthesized follower counts
    s = re.sub(r"\(\s*\d[\d\s\.,\u202f\u00a0]*\s*(?:k|m)?\s*(?:abonn[eé]s?|followers)\s*\)", "", s, flags=re.IGNORECASE)
    # Remove trailing segments separated by common separators
    for sep in [" | ", " · ", " - ", " — ", " – "]:
        parts = [p.strip() for p in s.split(sep) if p is not None]
        if len(parts) >= 2 and _looks_like_followers(parts[-1]):
            s = sep.join(parts[:-1])
    # Terminal follower phrase
    s = re.sub(r"[\s\-•|·—,;:]*\d[\d\s\.,\u202f\u00a0]*\s*(?:k|m)?\s*(?:abonn[eé]s?|followers)\s*$", "", s, flags=re.IGNORECASE)
    # Leading follower phrase like "12 345 abonnés • Company"
    if " • " in s:
        head, tail = s.split(" • ", 1)
        if _looks_like_followers(head):
            s = tail.strip()
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
    # En mode mock on autorise l'accès sans session LinkedIn réelle
    try:
        if ctx.settings.playwright_mock_mode:  # type: ignore[attr-defined]
            return
    except Exception:
        pass
    st = await session_status(ctx)
    if not st.valid:
        # Pas authentifié : redirige vers login
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
        try:
            for r in conn.execute(query):
                rows.append(dict(r))
        except sqlite3.OperationalError as e:
            # In environments that never created the 'posts' table (e.g., Mongo-only setups),
            # gracefully degrade to an empty trash view instead of raising 500.
            if "no such table: posts" in str(e).lower():
                try:
                    ctx.logger.warning("trash_posts_table_missing", hint="Returning empty list", error=str(e))
                except Exception:
                    pass
                return []
            raise
    return rows

async def fetch_posts(ctx, skip: int, limit: int, q: Optional[str] = None, sort_by: Optional[str] = None, sort_dir: Optional[str] = None, intent: Optional[str] = None, include_raw: bool = False) -> list[dict[str, Any]]:
    q = _sanitize_query(q)
    sort_field, sort_direction = _normalize_sort(sort_by, sort_dir)
    rows: list[dict[str, Any]] = []
    def _derive_company(author: str, current_company: Optional[str], author_profile: Optional[str], text: Optional[str]) -> Optional[str]:
        """Attempt to derive a company name when the stored company is missing or duplicates the author.

        Heuristics (lightweight, defensive):
         - If author_profile looks like JSON, parse and look for keys (company, organization, headline, subtitle, occupation)
         - Extract portion after French 'chez ' or English ' at ' / '@' tokens
         - Split on common separators (" | ", " · ", " - ", ",") and choose a segment that does not repeat the author name and has letters
        """
        try:
            if current_company and current_company.strip() and current_company.strip().lower() != author.strip().lower():
                return current_company  # Already distinct
            profile_obj = None
            if author_profile and author_profile.strip().startswith('{'):
                import json as _json_mod
                try:
                    profile_obj = _json_mod.loads(author_profile)
                except Exception:
                    profile_obj = None
            candidates: list[str] = []
            if profile_obj:
                for k in ("company", "organization", "org", "headline", "subtitle", "occupation", "title"):
                    v = profile_obj.get(k)
                    if isinstance(v, str):
                        candidates.append(v)
            if text and isinstance(text, str):
                # Sometimes post text contains signature lines with company
                candidates.append(text[:240])  # limit for speed
            def _clean(seg: str) -> str:
                return seg.strip().strip('-–|·•').strip()
            extracted: list[str] = []
            for raw in candidates:
                if not raw:
                    continue
                lower = raw.lower()
                marker_pos = -1
                marker = None
                for m in ["chez ", " at ", " @"]:
                    mp = lower.find(m)
                    if mp != -1:
                        marker_pos = mp + len(m)
                        marker = m
                        break
                segs: list[str] = []
                if marker_pos != -1:
                    tail = raw[marker_pos:]
                    segs.append(tail)
                # Also split full raw on separators to find plausible company tokens
                for sep in [" | ", " · ", " - ", ",", " • "]:
                    if sep in raw:
                        segs.extend(raw.split(sep))
                if not segs:
                    segs = [raw]
                for seg in segs:
                    segc = _clean(seg)
                    if not segc:
                        continue
                    if len(segc) < 2 or segc.lower() == author.lower():
                        continue
                    # Avoid picking obvious role words alone
                    if segc.lower() in {"freelance", "independant", "indépendant", "consultant", "recruteur"}:
                        continue
                    # Must contain at least one letter
                    if not any(c.isalpha() for c in segc):
                        continue
                    extracted.append(segc)
            # Rank choices: prefer ones with capital letters and without '@'
            for cand in extracted:
                if author.lower() not in cand.lower():
                    return cand[:120]
        except Exception:
            return current_company
        return current_company
    # Mongo path
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
            # Toujours exclure contenu de démonstration
            mf: dict[str, Any] = {"author": {"$ne": "demo_recruteur"}, "keyword": {"$ne": "demo_recruteur"}}
            if q:
                mf["$or"] = [
                    {"text": {"$regex": q, "$options": "i"}},
                    {"author": {"$regex": q, "$options": "i"}},
                    {"company": {"$regex": q, "$options": "i"}},
                    {"keyword": {"$regex": q, "$options": "i"}},
                ]
            if intent and intent in ("recherche_profil","autre"):
                mf["intent"] = intent
            # Exclude raw + legacy score fields
            projection = {"score": 0, "recruitment_score": 0}
            if not include_raw:
                projection["raw"] = 0
            cursor = coll.find(mf, projection).sort(sort_field, sort_direction).skip(skip).limit(limit)
            rows = []
            async for doc in cursor:
                try:
                    author = str(doc.get("author") or "")
                    comp = doc.get("company")
                    prof = doc.get("author_profile")
                    txt = doc.get("text")
                    derived = _derive_company(author, comp, prof, txt)
                    if derived and (not comp or str(comp).strip().lower() == author.strip().lower()):
                        doc["company"] = derived
                except Exception:
                    pass
                rows.append(doc)
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
                # Dynamic column projection: tolerate minimal schemas used in tests
                try:
                    col_rows = conn.execute("PRAGMA table_info(posts)").fetchall()
                    existing_cols = {r[1] for r in col_rows}
                except Exception:
                    existing_cols = set()
                wanted = [
                    ("id", "p.id as _id"),
                    ("keyword", "p.keyword"),
                    ("author", "p.author"),
                    ("author_profile", "p.author_profile"),  # optional
                    ("company", "p.company"),
                    ("text", "p.text"),
                    ("published_at", "p.published_at"),
                    ("collected_at", "p.collected_at"),
                    ("permalink", "p.permalink"),
                    ("intent", "p.intent"),
                    ("relevance_score", "p.relevance_score"),
                    ("confidence", "p.confidence"),
                    ("keywords_matched", "p.keywords_matched"),
                    ("location_ok", "p.location_ok"),
                    ("raw_json", "p.raw_json"),
                ]
                select_parts: list[str] = []
                for logical, expr in wanted:
                    base_name = logical if logical != "id" else "id"
                    if base_name in existing_cols:
                        select_parts.append(expr)
                    else:
                        # Provide NULL alias for missing optional columns
                        alias = logical if logical != "id" else "_id"
                        if logical == "id":
                            # id we always expect; ensure fallback
                            select_parts.append("p.id as _id")
                        elif logical == "author_profile":
                            select_parts.append("NULL as author_profile")
                        else:
                            select_parts.append(f"NULL as {logical}")
                # Flags columns appended
                select_parts.append("COALESCE(f.is_favorite,0) AS is_favorite")
                select_parts.append("COALESCE(f.is_deleted,0) AS is_deleted")
                base_q = "SELECT " + ", ".join(select_parts) + " FROM posts p LEFT JOIN post_flags f ON f.post_id = p.id"
                params: list[Any] = []
                # Base WHERE pour exclure posts démo + corbeille
                where_clauses = [
                    "LOWER(p.author) <> 'demo_recruteur'",
                    "LOWER(p.keyword) <> 'demo_recruteur'",
                    "COALESCE(f.is_deleted,0) = 0"
                ]
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
                if intent and intent in ("recherche_profil","autre"):
                    # Prefer explicit column if present else fallback raw_json LIKE
                    try:
                        col_rows = conn.execute("PRAGMA table_info(posts)").fetchall()
                        col_names = {r[1] for r in col_rows}
                    except Exception:
                        col_names = set()
                    if 'intent' in col_names:
                        where_clauses.append("COALESCE(p.intent,'') = ?")
                        params.append(intent)
                    else:
                        where_clauses.append("p.raw_json LIKE ?")
                        params.append(f'%"intent": "{intent}"%')
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
                    # Derive company if missing or equal to author
                    try:
                        item["company"] = _derive_company(str(item.get("author") or ""), item.get("company"), item.get("author_profile"), item.get("text")) or item.get("company")
                        # Provide company_norm (non-persistent here; persisted by background task)
                        if not item.get("company_norm"):
                            cn = _derive_company(str(item.get("author") or ""), item.get("company"), item.get("author_profile"), item.get("text"))
                            if cn:
                                item["company_norm"] = cn
                    except Exception:
                        pass
                    # Attach raw/classification debug if requested and columns exist (attempt to parse raw_json)
                    if include_raw:
                        try:
                            if 'raw_json' in item and item['raw_json']:
                                raw_obj = _json.loads(item['raw_json'])
                            else:
                                raw_obj = {}
                        except Exception:
                            raw_obj = {}
                        # SQLite explicit columns may already hold values; ensure classification sub-dict
                        classification = {
                            "intent": item.get("intent"),
                            "relevance_score": item.get("relevance_score"),
                            "confidence": item.get("confidence"),
                            "keywords_matched": item.get("keywords_matched"),
                            "location_ok": item.get("location_ok"),
                        }
                        # On-demand lightweight reclassification if fields absent
                        if not classification.get("intent"):
                            try:
                                from scraper.legal_classifier import classify_legal_post  # local import to avoid startup cost
                                lc = classify_legal_post(item.get("text") or "", language=item.get("language") or "fr", intent_threshold=0.35)
                                classification.update({
                                    "intent": lc.intent,
                                    "relevance_score": lc.relevance_score,
                                    "confidence": lc.confidence,
                                    "keywords_matched": lc.keywords_matched,
                                    "location_ok": lc.location_ok,
                                    "_derived": True,
                                })
                            except Exception:
                                classification.setdefault("_derived", False)
                        if raw_obj:
                            classification["raw_fragment"] = raw_obj.get("raw") or raw_obj
                        # Guarantee presence even if empty
                        if not classification.get("intent") and not classification.get("keywords_matched"):
                            classification.setdefault("note", "derived_empty")
                        item["classification_debug"] = classification
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
            # 7-day window dedup memory (per request) to suppress older duplicates in last week
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            week_ago = now - timedelta(days=7)
            recent_keys: dict[str, datetime] = {}
            # Optional: attempt to fetch content_hash for rows coming from SQLite path (only if available)
            content_hash_map: dict[str, str] = {}
            try:
                # Only build map if sqlite file exists and ids present
                if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
                    conn = sqlite3.connect(ctx.settings.sqlite_path)
                    conn.row_factory = sqlite3.Row
                    with conn:
                        ids = [itm.get("_id") for itm in rows if itm.get("_id")]
                        if ids:
                            placeholders = ",".join(["?"]*len(ids))
                            for r in conn.execute(f"SELECT id, content_hash, permalink FROM posts WHERE id IN ({placeholders})", ids):
                                if r[1]:
                                    content_hash_map[str(r[0])] = str(r[1])
            except Exception:
                content_hash_map = {}
            for item in rows:
                # Sanitize author duplication in display
                item_author = _dedupe_person_name(item.get("author"))
                item_author = _strip_followers_suffix(item_author)
                # Extra hardening: if author still matches follower pattern alone, blank it -> 'Unknown'
                try:
                    if item_author and _looks_like_followers(item_author):
                        item_author = "Unknown"
                except Exception:
                    pass
                if item_author:
                    item["author"] = item_author
                # Fix / enhance company
                comp = item.get("company")
                if not comp or str(comp).strip().lower() == str(item.get("author") or "").strip().lower():
                    # Prefer author_profile first if present
                    prof = item.get("author_profile")
                    derived = None
                    if prof:
                        derived = _derive_company(item.get("author") or "", prof, item.get("text"))
                    if not derived:
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
                try:
                    if _scrape_utils.is_opportunity(item.get("text"), threshold=ctx.settings.recruitment_signal_threshold):
                        item["opportunity"] = True
                except Exception:
                    pass
                perma_raw = item.get("permalink") or ""
                if perma_raw:
                    # Canonicalise: drop trailing slash & unify activity id pattern
                    perma_norm = perma_raw.split('?',1)[0].split('#',1)[0].rstrip('/')
                    # Convert various forms to standard activity URL if activity id present
                    import re as _re
                    m = _re.search(r"(urn:li:activity:(\d+))|(activity/(\d+))", perma_norm)
                    if m:
                        act = m.group(2) or m.group(4)
                        if act:
                            perma_norm = f"https://www.linkedin.com/feed/update/urn:li:activity:{act}"
                    if perma_norm != perma_raw:
                        item["permalink"] = perma_norm
                perma = item.get("permalink") or ""
                author = (item.get("author") or "")
                published = item.get("published_at") or ""
                text = (item.get("text") or "")
                # Prefer permalink; fallback author+published; then content_hash if available; else text snippet hash
                if perma:
                    key = f"perma|{perma}"
                elif author and published:
                    key = f"authdate|{author}|{published}"
                else:
                    ch = None
                    pid = item.get("_id")
                    if pid and pid in content_hash_map:
                        ch = content_hash_map[pid]
                    if not ch:
                        import hashlib
                        snippet = text[:220]
                        reduced = __import__('re').sub(r"\d{2,}", "#", __import__('re').sub(r"\s+", " ", snippet))
                        ch = hashlib.sha1(reduced.encode('utf-8', errors='ignore')).hexdigest()[:12]
                    key = f"authtext|{author}|{ch}"
                if key in seen:
                    # Secondary suppression: if duplicate within 7-day window, skip older one
                    try:
                        ts_raw = item.get("published_at") or item.get("collected_at")
                        ts = datetime.fromisoformat(str(ts_raw).replace("Z","+00:00")) if ts_raw else None
                        if key in recent_keys and ts and ts < recent_keys[key] and ts > week_ago:
                            continue
                    except Exception:
                        continue
                else:
                    # Record first timestamp for window logic
                    try:
                        ts_raw = item.get("published_at") or item.get("collected_at")
                        ts = datetime.fromisoformat(str(ts_raw).replace("Z","+00:00")) if ts_raw else None
                        if ts:
                            recent_keys[key] = ts
                    except Exception:
                        pass
                seen.add(key)
                deduped.append(item)
            rows = deduped
    except Exception:
        pass

    # Exclude posts coming from blocked accounts (by LinkedIn URL slug matched against author/company)
    try:
        items = await _blocked_list(ctx)
        blocked_names: set[str] = set()
        for it in items:
            u = (it.get("url") or "").strip()
            if not u:
                continue
            slug = _blocked_slug_from_url(u)
            if slug:
                blocked_names.add(slug)
        if blocked_names and rows:
            def _norm_name(s: Any) -> str:
                try:
                    from scraper.utils import normalize_for_search as _nfs  # type: ignore
                    return _nfs(str(s or "")).strip()
                except Exception:
                    return str(s or "").strip().lower()
            filtered_rows: list[dict[str, Any]] = []
            for it in rows:
                a = _norm_name(it.get("author"))
                c = _norm_name(it.get("company"))
                # direct equality or substring match to be tolerant to suffixes
                is_blocked = any(
                    (bn and ((a and (a == bn or bn in a)) or (c and (c == bn or bn in c))))
                    for bn in blocked_names
                )
                if not is_blocked:
                    filtered_rows.append(it)
            rows = filtered_rows
    except Exception:
        # On any error, do not block results; better to show than break
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
        # SQLite meta: prefer explicit meta table when present, then approximate posts_count from posts
        try:
            if ctx.settings.sqlite_path and Path(ctx.settings.sqlite_path).exists():
                conn = sqlite3.connect(ctx.settings.sqlite_path)
                with conn:
                    # Try meta table first (created by worker.update_meta)
                    try:
                        row = conn.execute("SELECT last_run, COALESCE(posts_count,0), COALESCE(scraping_enabled, 1) FROM meta WHERE id = 'global'").fetchone()
                        if row:
                            meta["last_run"] = row[0]
                            meta["posts_count"] = int(row[1] or 0)
                            meta["scraping_enabled"] = bool(row[2])
                    except Exception:
                        pass
                    # Fallback: compute posts_count from posts if meta table not present
                    _ensure_post_flags(conn)
                    c = conn.execute(
                        "SELECT COUNT(*) FROM posts p LEFT JOIN post_flags f ON f.post_id = p.id "
                        "WHERE LOWER(p.author) <> 'demo_recruteur' AND LOWER(p.keyword) <> 'demo_recruteur' AND COALESCE(f.is_deleted,0) = 0"
                    ).fetchone()
                    if c and (not meta.get("posts_count")):
                        meta["posts_count"] = int(c[0] or 0)
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
    intent: Optional[str] = Query(None, description="Filtrer par intent (recherche_profil/autre)"),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query(None),
    ctx=Depends(get_auth_context),
    # min_score removed
    _auth=Depends(require_auth),  # enforce auth if enabled
    _ls=Depends(require_linkedin_session),  # require linkedin session
):
    skip = (page - 1) * limit
    posts = await fetch_posts(ctx, skip=skip, limit=limit, q=q, sort_by=sort_by, sort_dir=sort_dir, intent=intent, include_raw=False)
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
            "intent": intent or "",
            "autonomous_interval": ctx.settings.autonomous_worker_interval_seconds,
            "login_initial_wait_seconds": ctx.settings.login_initial_wait_seconds,
            "sort_by": (sort_by or "collected_at"),
            "sort_dir": (sort_dir or "desc"),
            "mock_mode": ctx.settings.playwright_mock_mode,
            "trash_count": trash_count,
        },
    )

# Variante sans exigence de session LinkedIn quand mock actif (accès /demo)
@router.get("/demo", response_class=HTMLResponse)
async def dashboard_demo(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(default_factory=_default_limit, ge=1, le=200),
    q: Optional[str] = Query(None),
    intent: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query(None),
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
):
    # Si on n'est pas en mock rediriger vers route normale (qui appliquera la vérification de session)
    try:
        if not ctx.settings.playwright_mock_mode:  # type: ignore[attr-defined]
            return RedirectResponse("/", status_code=302)
    except Exception:
        return RedirectResponse("/", status_code=302)
    skip = (page - 1) * limit
    posts = await fetch_posts(ctx, skip=skip, limit=limit, q=q, sort_by=sort_by, sort_dir=sort_dir, intent=intent, include_raw=False)
    meta = await fetch_meta(ctx)
    trash_count = _count_deleted(ctx)
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
            "intent": intent or "",
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
    # Lazy import pandas to avoid failing app startup if numpy/pandas cannot load in frozen builds
    try:
        import pandas as pd  # type: ignore
    except Exception as e:  # pragma: no cover
        try:
            ctx.logger.error("export_excel_pandas_unavailable", error=str(e))
        except Exception:
            pass
        return PlainTextResponse(
            "Export Excel indisponible: dépendance pandas/numpy introuvable. Réinstallez l'application.",
            status_code=500,
        )
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
    sync: Optional[int] = Query(None, description="Exécuter le cycle en ligne (synchrone) si =1 et sans Redis"),
    relaxed: Optional[int] = Query(None, description="Relâcher les filtres pour un run de test si =1"),
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
    # If Redis is configured, always enqueue (distributed workers will handle it)
    if ctx.redis:
        try:
            await ctx.redis.rpush(ctx.settings.redis_queue_key, json_dumps(payload))
            ctx.logger.info("job_enqueued", keywords=kws)
            return Response(status_code=202)
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("enqueue_failed", error=str(exc))
            raise HTTPException(status_code=500, detail="Queue indisponible")
    # No redis: optionally allow a synchronous inline run for deterministic desktop tests
    try:
        sync_header = request.headers.get("X-Trigger-Sync")
        sync_mode = bool(sync and int(sync) == 1) or (str(sync_header).strip().lower() in ("1","true","yes"))
    except Exception:
        sync_mode = False
    if sync_mode:
        try:
            from scraper.worker import process_job  # local import
            # Optionnel: mode relaxé pour tests (désactive filtres stricts ponctuellement)
            relaxed_mode = bool(relaxed and int(relaxed) == 1)
            if relaxed_mode:
                setattr(ctx, "_relaxed_filters", True)
            try:
                new = await process_job(kws, ctx)
            finally:
                if relaxed_mode and hasattr(ctx, "_relaxed_filters"):
                    try:
                        delattr(ctx, "_relaxed_filters")
                    except Exception:
                        pass
            # Explicit meta refresh occurs inside process_job; return result count
            return JSONResponse({"status": "ok", "inserted": int(new)})
        except Exception as exc:
            ctx.logger.error("inline_trigger_failed", error=str(exc))
            raise HTTPException(status_code=500, detail="Echec exécution inline")
    # Default: No redis path -> enqueue locally and ensure single worker task
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
    include_raw: Optional[int] = Query(0, description="Inclure bloc classification_debug et raw minimal si =1"),
    # min_score removed
):
    skip = (page - 1) * limit
    posts = await fetch_posts(ctx, skip=skip, limit=limit, q=q, sort_by=sort_by, sort_dir=sort_dir, include_raw=bool(include_raw))
    return {"page": page, "limit": limit, "items": posts, "include_raw": bool(include_raw)}


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


@router.post("/api/posts/{post_id}/purge")
async def api_purge_post(
    post_id: str,
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
):
    """Purge définitivement un post (suppression de la base et des flags)."""
    removed = 0
    # Mongo
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
            res = await coll.delete_one({"_id": post_id})
            removed += int(getattr(res, 'deleted_count', 0) or 0)
        except Exception:
            pass
    # SQLite
    path = ctx.settings.sqlite_path
    if path and Path(path).exists():
        import sqlite3 as _sqlite
        try:
            conn = _sqlite.connect(path)
            with conn:
                try:
                    conn.execute("DELETE FROM post_flags WHERE post_id=?", (post_id,))
                except Exception:
                    pass
                res = conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
                removed += int(res.rowcount or 0)
        except Exception:
            pass
    return {"post_id": post_id, "removed": removed, "trash_count": _count_deleted(ctx)}


@router.post("/api/trash/empty")
async def api_trash_empty(
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
):
    """Supprime définitivement tous les posts marqués supprimés (corbeille)."""
    removed_sqlite = 0
    removed_mongo = 0
    # Mongo: best-effort remove documents that have a corresponding deleted flag in SQLite (if any)
    # If only Mongo is used, no flags table exists; skip to avoid heavy full scans.
    path = ctx.settings.sqlite_path
    deleted_ids: list[str] = []
    if path and Path(path).exists():
        import sqlite3 as _sqlite
        try:
            conn = _sqlite.connect(path)
            conn.row_factory = _sqlite.Row
            with conn:
                _ensure_post_flags(conn)
                ids = [r[0] for r in conn.execute("SELECT post_id FROM post_flags WHERE is_deleted = 1").fetchall()]
                deleted_ids = ids
                # Purge flags first, then posts
                if ids:
                    placeholders = ",".join(["?"] * len(ids))
                    try:
                        conn.execute(f"DELETE FROM post_flags WHERE post_id IN ({placeholders})", ids)
                    except Exception:
                        pass
                    res = conn.execute(f"DELETE FROM posts WHERE id IN ({placeholders})", ids)
                    removed_sqlite = int(res.rowcount or 0)
                    try:
                        conn.execute("VACUUM")
                    except Exception:
                        pass
        except Exception:
            pass
    if deleted_ids and ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
            mres = await coll.delete_many({"_id": {"$in": deleted_ids}})
            removed_mongo = int(getattr(mres, 'deleted_count', 0) or 0)
        except Exception:
            pass
    return {"ok": True, "removed_sqlite": removed_sqlite, "removed_mongo": removed_mongo, "trash_count": _count_deleted(ctx)}


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
        # If still no last_run and SQLite is used, derive from latest collected_at
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
    try:
        data["autonomous_worker_active"] = bool(getattr(ctx, "_autonomous_worker_active", False))
    except Exception:
        data["autonomous_worker_active"] = False
    # Disabled flag propagated
    try:
        data["disabled_flag"] = bool(getattr(ctx.settings, 'disable_scraper', False))
    except Exception:
        data["disabled_flag"] = False
    # Playwright availability shallow check (only if not disabled)
    try:
        if not data.get("disabled_flag"):
            from playwright.async_api import async_playwright  # type: ignore
            data["playwright_available"] = True
        else:
            data["playwright_available"] = False
    except Exception:
        data["playwright_available"] = False
    # Quota progression (in-memory)
    try:
        target = ctx.settings.daily_post_target
        soft = getattr(ctx.settings, 'daily_post_soft_target', max(1, int(target*0.8)))
        collected = getattr(ctx, 'daily_post_count', 0)
        data["daily_post_target"] = target
        data["daily_post_soft_target"] = soft
        data["daily_post_collected"] = collected
        data["daily_remaining_soft"] = max(0, soft - collected)
        data["daily_remaining_hard"] = max(0, target - collected)
        pacing = "cooldown" if collected >= target else ("accelerated" if collected < soft else "normal")
        data["pacing_mode"] = pacing
    except Exception:
        pass
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


@router.post("/api/admin/normalize_companies")
async def admin_normalize_companies(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Manual trigger for company normalization (SQLite only).
    Returns number of rows updated in this invocation.
    """
    import sqlite3, json, re
    from pathlib import Path
    if not ctx.settings.sqlite_path or not Path(ctx.settings.sqlite_path).exists():
        raise HTTPException(status_code=400, detail="SQLite indisponible")
    conn = sqlite3.connect(ctx.settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    updated = 0; scanned = 0
    # Lightweight derivation (reuse simplified subset identical to background job)
    CAPITAL_RE = re.compile(r"(?:(?:[A-Z][A-Za-z&\-]{1,}\s){0,3}[A-Z][A-Za-z&\-]{1,})")
    EXCLUDE = {"freelance","consultant","independant","indépendant","recruteur"}
    def derive(author: str, company: str|None, profile: str|None, text: str|None):
        try:
            if company and company.strip() and company.strip().lower() != author.strip().lower():
                return company
            cand_blocks = []
            if profile and profile.strip().startswith('{'):
                try:
                    pobj = json.loads(profile)
                    for k in ("company","organization","org","headline","subtitle","occupation","title"):
                        v = pobj.get(k)
                        if isinstance(v,str): cand_blocks.append(v)
                except Exception: pass
            if text: cand_blocks.append(text[:240])
            out_candidates = []
            for raw in cand_blocks:
                if not raw: continue
                low = raw.lower()
                for marker in ["chez "," at "," @"]:
                    if marker in low:
                        seg = raw[low.find(marker)+len(marker):]
                        out_candidates.append(seg)
                for part in re.split(r"\s[|·•-]\s|,", raw):
                    out_candidates.append(part)
                for m in CAPITAL_RE.findall(raw):
                    out_candidates.append(m)
            cleaned = []
            for c in out_candidates:
                c2 = c.strip().strip('-–|·•').strip()
                if not c2 or len(c2)<2: continue
                if c2.lower()==author.lower(): continue
                if c2.lower() in EXCLUDE: continue
                if not any(ch.isalpha() for ch in c2): continue
                if author.lower() in c2.lower(): continue
                cleaned.append(c2)
            for c3 in cleaned:
                return c3[:120]
        except Exception:
            return company
        return company
    with conn:
        try: conn.execute("ALTER TABLE posts ADD COLUMN company_norm TEXT")
        except Exception: pass
        try: conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_company_norm ON posts(company_norm)")
        except Exception: pass
        cur = conn.execute("SELECT id, author, company, company_norm, author_profile, text FROM posts")
        for r in cur.fetchall():
            scanned += 1
            author = r["author"] or ""
            if not author: continue
            comp_norm = r["company_norm"]
            comp = r["company"]
            if comp_norm and comp_norm.strip():
                continue
            derived = derive(author, comp, r["author_profile"], r["text"])
            if derived and (not comp or comp.strip().lower()==author.strip().lower() or derived!=comp):
                conn.execute("UPDATE posts SET company_norm=? WHERE id=?", (derived, r["id"]))
                updated += 1
    return {"updated": updated, "scanned": scanned}


@router.get("/api/daily_summary")
async def api_daily_summary(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Return aggregated statistics for the current (local) day.

    Stats include: total posts today, opportunities detected, favorites auto vs manual,
    top companies, contract status distribution.
    """
    from datetime import date
    today_prefix = date.today().isoformat()  # match on collected_at starting with date
    path = ctx.settings.sqlite_path
    summary = {
        "date": today_prefix,
        "total": 0,
        "opportunities": 0,
        "favorites": 0,
        "favorites_manual": 0,
        "favorites_auto": 0,
        "companies_top": [],
        "status_distribution": {},
    }
    if not path or not Path(path).exists():
        return summary
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    with conn:
        try:
            # base select for today (excluding deleted)
            conn.execute("CREATE TABLE IF NOT EXISTS post_flags (post_id TEXT PRIMARY KEY, is_favorite INTEGER, is_deleted INTEGER, favorite_at TEXT, deleted_at TEXT)")
        except Exception:
            pass
        rows = conn.execute(
            "SELECT p.id, p.text, p.company, p.collected_at, p.published_at, f.is_favorite, f.is_deleted, f.favorite_at FROM posts p LEFT JOIN post_flags f ON f.post_id=p.id WHERE p.collected_at LIKE ? AND COALESCE(f.is_deleted,0)=0",
            (f"{today_prefix}%",),
        ).fetchall()
        summary["total"] = len(rows)
        comp_counter: dict[str,int] = {}
        status_counter: dict[str,int] = {}
        opp = 0
        fav = 0
        fav_auto = 0
        fav_manual = 0
        for r in rows:
            txt = r["text"] or ""
            if _scrape_utils.is_opportunity(txt, threshold=ctx.settings.recruitment_signal_threshold):
                opp += 1
            if r["is_favorite"]:
                fav += 1
                # Heuristic: if favorite_at is within 3 seconds of collected_at -> auto
                try:
                    import datetime as _dt
                    fav_at = _dt.datetime.fromisoformat(str(r["favorite_at"]).replace("Z","+00:00")) if r["favorite_at"] else None
                    coll_at = _dt.datetime.fromisoformat(str(r["collected_at"]).replace("Z","+00:00")) if r["collected_at"] else None
                    if fav_at and coll_at and abs((fav_at - coll_at).total_seconds()) <= 3:
                        fav_auto += 1
                    else:
                        fav_manual += 1
                except Exception:
                    fav_manual += 1
            comp = (r["company"] or "").strip()
            if comp:
                comp_counter[comp] = comp_counter.get(comp,0)+1
            # Status derivation reused (contract keywords) simplistic
            from .routes import _extract_contract_status  # type: ignore
            st = _extract_contract_status(txt)
            if st:
                for token in [s.strip() for s in st.split(',') if s.strip()]:
                    status_counter[token] = status_counter.get(token,0)+1
        summary["opportunities"] = opp
        summary["favorites"] = fav
        summary["favorites_manual"] = fav_manual
        summary["favorites_auto"] = fav_auto
        summary["companies_top"] = sorted([{ "company": c, "count": n } for c,n in comp_counter.items()], key=lambda x: x["count"], reverse=True)[:5]
        summary["status_distribution"] = status_counter
    return summary


@router.get("/focus")
async def focus_window():  # noqa: D401
    """Desktop only: bring existing window to foreground.

    Returns 200 with {focused: bool}. Always 200 to keep client simple.
    """
    focused = False
    if _desktop_ipc is not None:
        try:
            focused = bool(_desktop_ipc.focus_window())  # type: ignore[attr-defined]
        except Exception:
            focused = False
    return {"focused": focused}


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
    # If the template directory does not contain login.html (packaging issue),
    # provide a minimal inline fallback so the application remains usable and
    # the user gets a clear indication of the missing resource instead of a 500.
    try:
        if not (_TEMPLATE_DIR / "login.html").exists():
            from fastapi.responses import HTMLResponse
            html = (
                "<html><head><title>Login (fallback)</title><style>body{font-family:system-ui;padding:2rem;background:#111;color:#eee}</style></head><body>"
                "<h2>Login template manquante</h2>"
                f"<p>Dossier templates: <code>{_TEMPLATE_DIR}</code></p>"
                "<p>Le fichier <code>login.html</code> est introuvable dans le paquet installé. Recréez / re-emballez l'application avec le dossier <code>server/templates</code>.</p>"
                "<p>Statut de session actuel: <strong>" + ("valide" if st.valid else "invalide") + "</strong></p>"
                "</body></html>"
            )
            return HTMLResponse(html)
    except Exception:
        pass
    try:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "session": st.details,
                "valid": st.valid,
                "reason_message": message,
            },
        )
    except TemplateNotFound as exc:  # pragma: no cover - defensive path
        # Final safety net: even if the existence pre-check mis‑fired we still serve a fallback page.
        from fastapi.responses import HTMLResponse
        try:
            import logging as _logging3
            _logging3.getLogger("server").error(
                "login_template_missing_after_check", error=str(exc), template_dir=str(_TEMPLATE_DIR)
            )
            listing = []
            if _TEMPLATE_DIR.exists():
                listing = [p.name for p in _TEMPLATE_DIR.glob("*.html")]
        except Exception:
            listing = []  # type: ignore
        html = (
            "<html><head><title>Login (fallback 2)</title><style>body{font-family:system-ui;padding:2rem;background:#111;color:#eee}</style></head><body>"
            "<h2>Template de connexion introuvable (post-exception)</h2>"
            f"<p>Dossier templates résolu: <code>{_TEMPLATE_DIR}</code></p>"
            f"<p>Fichiers présents: <code>{', '.join(listing) or 'aucun'}</code></p>"
            "<p>Veuillez réinstaller ou reconstruire l'application. Cette page est un repli.</p>"
            f"<p>Statut session actuel: <strong>{'valide' if st.valid else 'invalide'}</strong></p>"
            "</body></html>"
        )
        return HTMLResponse(html, status_code=200)


@router.get("/debug/templates")
async def debug_templates():  # pragma: no cover - diagnostic endpoint
    """Return diagnostic information about the active Jinja2 template directory.

    Provides: chosen directory, existence, listing of .html files (first 50), and cwd.
    Useful to confirm packaging integrity on end‑user machines.
    """
    try:
        files = sorted([p.name for p in _TEMPLATE_DIR.glob("*.html")])[:50]
    except Exception:
        files = []  # type: ignore
    return {
        "template_dir": str(_TEMPLATE_DIR),
        "dir_exists": _TEMPLATE_DIR.exists(),
        "files": files,
        "cwd": str(Path.cwd()),
    }


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


@router.post("/api/session/import_cookies")
async def api_session_import_cookies(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Importe les cookies LinkedIn depuis les navigateurs locaux (Edge/Chrome/Firefox).

    Écrit un storage_state.json compatible Playwright si un cookie li_at est trouvé.
    """
    try:
        from scraper.session import browser_sync
        ok, diag = browser_sync(ctx)
        if not ok:
            return JSONResponse({"ok": False, **diag}, status_code=400)
        return {"ok": True, **diag}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


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


@router.get("/api/legal_stats")
async def api_legal_stats(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Aggregated legal-domain classification statistics for current UTC day.

    Returns counts and rates based on in-memory tracking + persistent counts.
    Note: In-memory counters reset when process restarts (acceptable for daily view).
    """
    from datetime import date
    today = date.today().isoformat()
    # Ensure date roll-over resets discard counters
    if getattr(ctx, 'legal_stats_date', None) != today:
        setattr(ctx, 'legal_stats_date', today)
        setattr(ctx, 'legal_daily_discard_intent', 0)
        setattr(ctx, 'legal_daily_discard_location', 0)
    accepted = getattr(ctx, 'legal_daily_count', 0)
    discard_intent = getattr(ctx, 'legal_daily_discard_intent', 0)
    discard_location = getattr(ctx, 'legal_daily_discard_location', 0)
    discarded = discard_intent + discard_location
    total_classified = accepted + discarded
    cap = ctx.settings.legal_daily_post_cap
    progress = (accepted / cap) if cap else 0.0
    rejection_rate = (discarded / total_classified) if total_classified else 0.0
    return {
        "date": today,
        "accepted": accepted,
        "discarded_intent": discard_intent,
        "discarded_location": discard_location,
        "discarded_total": discarded,
        "total_classified": total_classified,
        "cap": cap,
        "cap_remaining": max(0, cap - accepted),
        "cap_progress": round(progress, 4),
        "rejection_rate": round(rejection_rate, 4),
        "intent_threshold": ctx.settings.legal_intent_threshold,
    }


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


# ------------------------------------------------------------
# API Mock: Gestion des comptes LinkedIn bloqués
# ------------------------------------------------------------
@router.get("/blocked-accounts")
async def list_blocked_accounts(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Retourne la liste des comptes bloqués."""
    items = await _blocked_list(ctx)
    return {"items": items, "count": len(items)}


@router.post("/blocked-accounts")
async def add_blocked_account(
    payload: dict[str, Any] = Body(..., description="{ url: string }"),
    ctx=Depends(get_auth_context),
    _auth=Depends(require_auth),
):
    url_raw = (payload.get('url') or '').strip()
    url = _normalize_linkedin_url(url_raw)
    if not url:
        raise HTTPException(status_code=400, detail="URL LinkedIn invalide")
    item = await _blocked_add(ctx, url)
    return {"ok": True, "item": item}


@router.delete("/blocked-accounts/{item_id}")
async def delete_blocked_account(item_id: str, ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    await _blocked_delete(ctx, item_id)
    return {"ok": True, "id": item_id}


@router.get("/blocked-accounts/count")
async def count_blocked_accounts(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    cnt = await _blocked_count(ctx)
    return {"count": cnt}


# ------------------------------------------------------------
# Admin: purge all posts (Mongo + SQLite + CSV fallback)
# ------------------------------------------------------------
@router.post("/api/admin/purge_posts")
async def api_admin_purge_posts(ctx=Depends(get_auth_context), _auth=Depends(require_auth)):
    """Erase all stored posts and related flags, returning counts removed.

    This mirrors scripts/purge_data.py but exposes a protected HTTP endpoint for
    convenience from the dashboard. Authentication (basic) is required if enabled.
    """
    removed_sqlite = 0
    removed_mongo = 0
    # Mongo purge
    if ctx.mongo_client:
        try:
            coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
            res = await coll.delete_many({})
            removed_mongo = getattr(res, 'deleted_count', 0) or 0
            # Reset meta doc counters
            mcoll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_meta]
            await mcoll.update_one({"_id": "global"}, {"$set": {"posts_count": 0, "last_run": None}}, upsert=True)
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("api_purge_mongo_failed", error=str(exc))
    # SQLite purge
    import sqlite3 as _sqlite
    from pathlib import Path as _P
    if ctx.settings.sqlite_path and _P(ctx.settings.sqlite_path).exists():
        try:
            conn = _sqlite.connect(ctx.settings.sqlite_path)
            with conn:
                try:
                    cur = conn.execute("SELECT COUNT(*) FROM posts")
                    removed_sqlite = int(cur.fetchone()[0] or 0)
                except Exception:
                    removed_sqlite = 0
                try:
                    conn.execute("DELETE FROM post_flags")
                except Exception:
                    pass
                conn.execute("DELETE FROM posts")
                try:
                    conn.execute("VACUUM")
                except Exception:
                    pass
        except Exception as exc:  # pragma: no cover
            ctx.logger.error("api_purge_sqlite_failed", error=str(exc))
    # CSV fallback file
    try:
        csv_path = _P(ctx.settings.csv_fallback_file)
        if csv_path.exists():
            csv_path.unlink()
    except Exception:
        pass
    # Reset in-memory daily counter
    try:
        ctx.daily_post_count = 0  # type: ignore[attr-defined]
    except Exception:
        pass
    # Broadcast a lightweight event so UI can react (reuse toggle type or define new?)
    try:
        await broadcast({"type": "purge", "removed_sqlite": removed_sqlite, "removed_mongo": removed_mongo})
    except Exception:
        pass
    return {"ok": True, "removed_sqlite": removed_sqlite, "removed_mongo": removed_mongo}
