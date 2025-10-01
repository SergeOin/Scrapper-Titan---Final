from scraper.core.ids import content_hash, canonical_permalink

def test_content_hash_stability():
    h1 = content_hash("Alice", "Hello 123 world 456")
    h2 = content_hash("alice", "Hello 999 world 777")  # digits collapsed
    assert h1 == h2

def test_canonical_permalink_variants():
    base = "https://www.linkedin.com/feed/update/urn:li:activity:1234567890"
    assert canonical_permalink(base+"/?tracking=foo") == base
    assert canonical_permalink("https://www.linkedin.com/activity/1234567890/") == base
