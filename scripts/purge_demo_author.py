from __future__ import annotations
import argparse
import asyncio
import base64
import os
import sqlite3
from pathlib import Path

try:
    from scraper.bootstrap import get_context
except Exception:
    get_context = None


def purge_sqlite(sqlite_path: Path) -> int:
    if not sqlite_path.exists():
        print("sqlite_missing", sqlite_path)
        return 0
    conn = sqlite3.connect(str(sqlite_path))
    with conn:
        cur = conn.execute("select count(*) from posts where lower(author) = 'demo_recruteur'")
        to_del = cur.fetchone()[0]
        print("sqlite_matches", to_del)
        if to_del:
            conn.execute("delete from posts where lower(author) = 'demo_recruteur'")
            conn.commit()
    return to_del


def purge_csv(csv_dir: Path) -> int:
    # Best-effort: rewrite CSV files without matching rows if CSV fallback is used
    # We look for posts_*.csv in the directory
    if not csv_dir.exists():
        return 0
    import csv
    total_removed = 0
    for p in csv_dir.glob("posts_*.csv"):
        rows = []
        removed = 0
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for r in reader:
                author = (r.get("author") or "").lower()
                if author == "demo_recruteur":
                    removed += 1
                else:
                    rows.append(r)
        if removed:
            tmp = p.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            tmp.replace(p)
            print(f"csv_cleaned {p.name} removed={removed}")
            total_removed += removed
    return total_removed


async def main():
    parser = argparse.ArgumentParser(description="Purge posts authored by demo_recruteur from local storage")
    parser.add_argument("--force", action="store_true", help="Actually perform deletions")
    args = parser.parse_args()

    # Try to use project context if available to locate storage
    sqlite_path = None
    csv_dir = None
    if get_context is not None:
        try:
            ctx = await get_context()
            sqlite_path = Path(ctx.settings.sqlite_path)
            csv_dir = Path(ctx.settings.data_dir)
        except Exception:
            pass

    if sqlite_path is None:
        sqlite_path = Path.cwd() / "fallback.sqlite3"
    if csv_dir is None:
        csv_dir = Path.cwd() / "data"

    print("sqlite:", sqlite_path)
    print("csv_dir:", csv_dir)

    # Dry-run first: show how many would be removed
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.execute("select count(*) from posts where lower(author) = 'demo_recruteur'")
        candidates = cur.fetchone()[0]
    except Exception as e:
        print("sqlite_check_error", e)
        candidates = 0
    finally:
        conn.close()
    print("would_remove_sqlite:", candidates)

    csv_candidates = 0
    try:
        # count candidates without modifying files
        import csv
        for p in csv_dir.glob("posts_*.csv"):
            with p.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    author = (r.get("author") or "").lower()
                    if author == "demo_recruteur":
                        csv_candidates += 1
    except Exception as e:
        print("csv_check_error", e)
    print("would_remove_csv:", csv_candidates)

    if not args.force:
        print("Run with --force to apply deletions.")
        return

    removed_sqlite = purge_sqlite(sqlite_path)
    removed_csv = purge_csv(csv_dir)

    print("purge_demo_author_done", {"sqlite": removed_sqlite, "csv": removed_csv})


if __name__ == "__main__":
    asyncio.run(main())
