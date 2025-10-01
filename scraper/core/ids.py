"""ID, permalink, and hash utilities centralised."""
from __future__ import annotations
import re, hashlib

_ACTIVITY_PAT = re.compile(r"urn:li:activity:(\d+)")
_ACTIVITY_PAT2 = re.compile(r"/activity/(\d+)")

def canonical_permalink(url: str | None) -> str | None:
    if not url:
        return url
    u = url.split('?',1)[0].split('#',1)[0].rstrip('/')
    m = _ACTIVITY_PAT.search(u) or _ACTIVITY_PAT2.search(u)
    if m:
        act = m.group(1)
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{act}"
    return u

def content_hash(author: str | None, text: str | None) -> str:
    a = (author or '').strip().lower()
    t = (text or '')
    t = re.sub(r"\s+"," ", t).strip().lower()
    t = re.sub(r"\d{2,}", "#", t)
    blob = f"{a}||{t}".encode('utf-8', errors='ignore')
    return hashlib.sha1(blob).hexdigest()[:20]

def make_post_id(*parts: str | None) -> str:
    flat = [p for p in parts if p]
    base = "::".join(flat) if flat else "post"
    h = hashlib.sha1(base.encode('utf-8', errors='ignore')).hexdigest()[:16]
    return h
