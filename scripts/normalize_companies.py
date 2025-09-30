"""Backfill / normalization script to derive missing companies for existing posts.

Usage:
  python scripts/normalize_companies.py

It will:
  * Open SQLite DB (ctx.settings.sqlite_path)
  * For posts where company is NULL/empty OR equals author (case-insensitive), attempt derivation
  * Update inline (in-place) and print a small summary

Safe: skips rows where no heuristic result.
"""
from __future__ import annotations
import os, json, sqlite3
from pathlib import Path
from datetime import datetime

from scraper.bootstrap import get_context

# Reuse a simplified version of the heuristic (mirrors server.routes._derive_company)

def derive_company(author: str, current: str | None, author_profile: str | None, text: str | None) -> str | None:
    try:
        if current and current.strip() and current.strip().lower() != author.strip().lower():
            return current
        profile_obj = None
        if author_profile and author_profile.strip().startswith('{'):
            try:
                profile_obj = json.loads(author_profile)
            except Exception:
                profile_obj = None
        candidates: list[str] = []
        if profile_obj:
            for k in ("company", "organization", "org", "headline", "subtitle", "occupation", "title"):
                v = profile_obj.get(k)
                if isinstance(v, str):
                    candidates.append(v)
        if text and isinstance(text, str):
            candidates.append(text[:240])
        def _clean(seg: str) -> str:
            return seg.strip().strip('-–|·•').strip()
        extracted: list[str] = []
        for raw in candidates:
            if not raw: continue
            lower = raw.lower()
            marker_pos = -1
            for m in ["chez ", " at ", " @"]:
                mp = lower.find(m)
                if mp != -1:
                    marker_pos = mp + len(m)
                    break
            segs: list[str] = []
            if marker_pos != -1:
                segs.append(raw[marker_pos:])
            for sep in [" | ", " · ", " - ", ",", " • "]:
                if sep in raw:
                    segs.extend(raw.split(sep))
            if not segs:
                segs = [raw]
            for seg in segs:
                segc = _clean(seg)
                if not segc: continue
                if len(segc) < 2 or segc.lower() == author.lower():
                    continue
                if segc.lower() in {"freelance", "independant", "indépendant", "consultant", "recruteur"}:
                    continue
                if not any(c.isalpha() for c in segc):
                    continue
                extracted.append(segc)
        for cand in extracted:
            if author.lower() not in cand.lower():
                return cand[:120]
    except Exception:
        return current
    return current

async def main():
    ctx = await get_context()
    path = ctx.settings.sqlite_path
    if not path or not Path(path).exists():
        print("[normalize] No sqlite DB found")
        return
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    updated = 0
    scanned = 0
    with conn:
        # Add company column if missing (defensive)
        try: conn.execute("ALTER TABLE posts ADD COLUMN company TEXT")
        except Exception: pass
        cur = conn.execute("SELECT id, author, company, text, author_profile FROM posts")
        rows = cur.fetchall()
        for r in rows:
            scanned += 1
            author = r["author"] or ""
            company = r["company"]
            text = r["text"]
            author_profile = r["author_profile"]
            if not author:
                continue
            if company and company.strip() and company.strip().lower() != author.strip().lower():
                continue  # already distinct
            derived = derive_company(author, company, author_profile, text)
            if derived and (not company or company.strip().lower()==author.strip().lower()):
                conn.execute("UPDATE posts SET company=? WHERE id=?", (derived, r["id"]))
                updated += 1
    print(f"[normalize] scanned={scanned} updated={updated} path={path}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
