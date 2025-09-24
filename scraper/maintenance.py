"""Maintenance utilities: recompute recruitment_score across backends.

Functions here are imported by the CLI script `scripts/recompute_recruitment_scores.py` and
can be unit tested independently.
"""
from __future__ import annotations

from typing import Iterable, Tuple
import sqlite3
import csv
import json
from pathlib import Path

import structlog

from . import utils
from .bootstrap import AppContext, get_context

logger = structlog.get_logger().bind(component="maintenance")


def recompute_sqlite(sqlite_path: str, force: bool = False) -> int:
    """Recompute recruitment_score in a SQLite fallback DB.

    Adds column if missing. Returns number of rows updated.
    """
    path = Path(sqlite_path)
    if not path.exists():
        return 0
    conn = sqlite3.connect(str(path))
    updated = 0
    with conn:
        # Add column if not present
        cols = [r[1] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
        if "recruitment_score" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN recruitment_score REAL")
        rows = conn.execute("SELECT id, text, recruitment_score FROM posts").fetchall()
        for pid, text, existing in rows:
            if existing is not None and not force:
                continue
            score = utils.compute_recruitment_signal(text or "")
            conn.execute(
                "UPDATE posts SET recruitment_score=? WHERE id=?", (score, pid)
            )
            updated += 1
    return updated


def recompute_csv(csv_file: str, force: bool = False) -> int:
    """Recompute recruitment_score in a CSV fallback file.

    Rewrites file in-place via temp file. Returns number of lines updated (excluding header).
    """
    path = Path(csv_file)
    if not path.exists():
        return 0
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    updated = 0
    with path.open("r", encoding="utf-8", newline="") as inp, tmp_path.open(
        "w", encoding="utf-8", newline=""
    ) as out:
        reader = csv.DictReader(inp)
        fieldnames = list(reader.fieldnames or [])
        if "recruitment_score" not in fieldnames:
            # Insert after score if present
            if "score" in fieldnames:
                idx = fieldnames.index("score") + 1
                fieldnames.insert(idx, "recruitment_score")
            else:
                fieldnames.append("recruitment_score")
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            existing = row.get("recruitment_score")
            if existing and existing.strip() != "" and not force:
                writer.writerow(row)
                continue
            score = utils.compute_recruitment_signal(row.get("text", ""))
            row["recruitment_score"] = f"{score:.4f}"
            updated += 1
            writer.writerow(row)
    tmp_path.replace(path)
    return updated


async def recompute_mongo(ctx: AppContext, force: bool = False, batch_size: int = 500) -> Tuple[int, int]:
    """Recompute recruitment_score for Mongo documents.

    Returns (scanned, updated).
    """
    if not ctx.mongo_client:
        return 0, 0
    coll = ctx.mongo_client[ctx.settings.mongo_db][ctx.settings.mongo_collection_posts]
    q = {} if force else {"$or": [{"recruitment_score": {"$exists": False}}, {"recruitment_score": None}]}
    scanned = 0
    updated = 0
    cursor = coll.find(q, {"_id": 1, "text": 1, "recruitment_score": 1})
    batch: list[dict] = []
    async for doc in cursor:
        scanned += 1
        batch.append(doc)
        if len(batch) >= batch_size:
            updated += await _update_mongo_batch(coll, batch, force)
            batch.clear()
    if batch:
        updated += await _update_mongo_batch(coll, batch, force)
    return scanned, updated


async def _update_mongo_batch(coll, batch: Iterable[dict], force: bool) -> int:
    ops = []
    changed = 0
    for d in batch:
        if d.get("recruitment_score") is not None and not force:
            continue
        score = utils.compute_recruitment_signal(d.get("text") or "")
        ops.append(
            {
                "update_one": {
                    "filter": {"_id": d["_id"]},
                    "update": {"$set": {"recruitment_score": score}},
                }
            }
        )
        changed += 1
    if ops:
        await coll.bulk_write(ops, ordered=False)
    return changed


async def recompute_all(force: bool = False) -> None:
    ctx = await get_context()
    updated_mongo = (0, 0)
    try:
        updated_mongo = await recompute_mongo(ctx, force=force)
    except Exception as exc:  # pragma: no cover
        logger.warning("mongo_recompute_failed", error=str(exc))
    try:
        up_sqlite = recompute_sqlite(ctx.settings.sqlite_path, force=force)
    except Exception as exc:  # pragma: no cover
        up_sqlite = 0
        logger.warning("sqlite_recompute_failed", error=str(exc))
    try:
        up_csv = recompute_csv(ctx.settings.csv_fallback_file, force=force)
    except Exception as exc:  # pragma: no cover
        up_csv = 0
        logger.warning("csv_recompute_failed", error=str(exc))
    logger.info(
        "recompute_done",
        mongo_scanned=updated_mongo[0],
        mongo_updated=updated_mongo[1],
        sqlite_updated=up_sqlite,
        csv_updated=up_csv,
        force=force,
    )
