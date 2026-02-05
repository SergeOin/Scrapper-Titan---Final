#!/usr/bin/env python3
"""Quick database check with file output - runs immediately on import."""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "TitanScraper", "fallback.sqlite3")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db_status.txt")

def main():
    results = []
    results.append(f"=== Database Check at {datetime.now().isoformat()} ===")
    results.append(f"DB Path: {DB_PATH}")
    results.append(f"Output File: {OUTPUT_FILE}")
    
    if not os.path.exists(DB_PATH):
        results.append("ERROR: Database file not found!")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(results))
        return
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Total posts
    cur.execute("SELECT COUNT(*) FROM posts")
    total = cur.fetchone()[0]
    results.append(f"\nTotal posts: {total}")
    
    # Posts last hour
    cur.execute("SELECT COUNT(*) FROM posts WHERE created_at > datetime('now', '-1 hour')")
    last_hour = cur.fetchone()[0]
    results.append(f"Posts last hour: {last_hour}")
    
    # Posts today
    cur.execute("SELECT COUNT(*) FROM posts WHERE date(created_at) = date('now')")
    today = cur.fetchone()[0]
    results.append(f"Posts today: {today}")
    
    # Recent posts
    results.append("\n--- 10 Most Recent Posts ---")
    cur.execute("""
        SELECT id, author, keyword, created_at 
        FROM posts 
        ORDER BY created_at DESC 
        LIMIT 10
    """)
    for row in cur.fetchall():
        results.append(f"  {row[0]}: {row[1][:30] if row[1] else 'N/A'} | {row[2]} | {row[3]}")
    
    # Keywords distribution
    results.append("\n--- Posts by Keyword (top 10) ---")
    cur.execute("""
        SELECT keyword, COUNT(*) as cnt 
        FROM posts 
        GROUP BY keyword 
        ORDER BY cnt DESC 
        LIMIT 10
    """)
    for row in cur.fetchall():
        results.append(f"  {row[0]}: {row[1]}")
    
    conn.close()
    
    # Write to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(results))
    
    print("Output written to", OUTPUT_FILE)

if __name__ == "__main__":
    main()
else:
    # Run automatically on import too
    main()
