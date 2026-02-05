"""Inspect posts data - v2 with detailed stats."""
import sqlite3
import os

db_path = os.path.join(os.environ.get("LOCALAPPDATA", "."), "TitanScraper", "fallback.sqlite3")
conn = sqlite3.connect(db_path)

# Count stats first
cur = conn.execute("SELECT COUNT(*) FROM posts")
total = cur.fetchone()[0]
print(f"\n=== Database Stats ===")
print(f"Total posts: {total}")

if total > 0:
    cur = conn.execute("SELECT COUNT(*) FROM posts WHERE company IS NOT NULL AND company != ''")
    with_company = cur.fetchone()[0]
    print(f"Posts with company: {with_company}/{total} ({100*with_company/total:.0f}%)")
    
    cur = conn.execute("SELECT COUNT(*) FROM posts WHERE published_at IS NOT NULL AND published_at != ''")
    with_date = cur.fetchone()[0]
    print(f"Posts with date: {with_date}/{total} ({100*with_date/total:.0f}%)")
    
    cur = conn.execute("SELECT COUNT(*) FROM posts WHERE permalink LIKE '%urn:li:%' OR permalink LIKE '%/feed/update/%'")
    with_real_link = cur.fetchone()[0]
    print(f"Posts with real permalink: {with_real_link}/{total} ({100*with_real_link/total:.0f}%)")

print()
cur = conn.execute("""
    SELECT author, company, permalink, published_at, substr(text, 1, 50) as preview
    FROM posts 
    ORDER BY collected_at DESC 
    LIMIT 15
""")

print("="*100)
print(f"{'Auteur':<25} | {'Entreprise':<20} | {'Date pub':<22} | {'Texte'}")
print("="*100)

for r in cur.fetchall():
    author = (r[0] or "?")[:24]
    company = (r[1] or "-")[:19]
    published = (r[3] or "-")[:21]
    permalink = r[2] or "?"
    text = (r[4] or "")[:45]
    
    # Check if permalink is profile or post
    is_profile_link = "/in/" in permalink and "#post-" in permalink
    link_type = "PROFILE!" if is_profile_link else "post" if "/feed/update/" in permalink else "other"
    
    print(f"{author:<25} | {company:<20} | {published:<22} | {text}...")
    print(f"    -> Permalink ({link_type}): {permalink[:80]}")
    print()

conn.close()
