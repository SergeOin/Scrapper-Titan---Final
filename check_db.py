#!/usr/bin/env python3
"""Check database tables and contents."""
import sqlite3

conn = sqlite3.connect('fallback.sqlite3')
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print(f"Tables: {tables}")

for table in tables:
    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"  {table}: {count} rows")

conn.close()
