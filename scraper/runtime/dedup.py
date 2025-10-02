"""Deduplication utilities extracted from legacy worker.

Rules (priorité décroissante):
1. Permalink (canonical)
2. Auteur + published_at
3. Hash (auteur + texte)

Entrée: liste de dicts issus de l'orchestrateur (posts_dicts)
Sortie: liste filtrée sans doublons selon clé supérieure rencontrée.
"""
from __future__ import annotations

from typing import Iterable, List, Dict, Any, Set, Tuple
from scraper.core.ids import content_hash

DedupKey = str

def compute_key(p: Dict[str, Any]) -> Tuple[DedupKey, int]:
    """Retourne (clé, priorité) où priorité plus faible = plus forte importance.

    Permet éventuellement d'ajouter un tri futur si nécessaire pour garder la meilleure version
    d'un doublon (ex: post enrichi). Pour l'instant on garde premier vu.
    """
    perma = p.get('permalink')
    author = p.get('author')
    published_at = p.get('published_at')
    if perma:
        return f"perma|{perma}", 0
    if author and published_at:
        return f"authdate|{author}|{published_at}", 1
    ch = p.get('content_hash') or content_hash(author, p.get('text'))
    return f"hash|{ch}", 2


def deduplicate(posts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[DedupKey] = set()
    out: List[Dict[str, Any]] = []
    for p in posts:
        try:
            key, _prio = compute_key(p)
        except Exception:  # pragma: no cover
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out
