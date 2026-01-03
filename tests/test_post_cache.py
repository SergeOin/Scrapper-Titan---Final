"""Tests for scraper/post_cache.py - Post deduplication cache."""
import pytest
import tempfile
import os


class TestSignatureGeneration:
    """Tests for signature generation functions."""
    
    def test_content_signature(self):
        from scraper.post_cache import generate_content_signature
        
        sig1 = generate_content_signature("Hello world", "author1")
        sig2 = generate_content_signature("Hello world", "author1")
        sig3 = generate_content_signature("Different text", "author1")
        
        assert sig1 == sig2
        assert sig1 != sig3
    
    def test_content_signature_normalization(self):
        from scraper.post_cache import generate_content_signature
        
        sig1 = generate_content_signature("Hello   world", "author")
        sig2 = generate_content_signature("Hello world", "author")
        
        assert sig1 == sig2
    
    def test_content_signature_case_insensitive(self):
        from scraper.post_cache import generate_content_signature
        
        sig1 = generate_content_signature("HELLO WORLD", "author")
        sig2 = generate_content_signature("hello world", "author")
        
        assert sig1 == sig2
    
    def test_url_signature(self):
        from scraper.post_cache import generate_url_signature
        
        sig1 = generate_url_signature("https://linkedin.com/post/123")
        sig2 = generate_url_signature("https://linkedin.com/post/123?ref=feed")
        
        # Query params should be removed
        assert sig1 == sig2
    
    def test_url_signature_empty(self):
        from scraper.post_cache import generate_url_signature
        
        sig = generate_url_signature("")
        assert sig == ""
    
    def test_post_id_signature(self):
        from scraper.post_cache import generate_post_id_signature
        
        sig = generate_post_id_signature("7123456789")
        
        assert sig == "pid:7123456789"
    
    def test_composite_signature_priority(self):
        from scraper.post_cache import generate_composite_signature
        
        # Post ID takes priority
        sig1 = generate_composite_signature(
            url="https://linkedin.com/post/123",
            post_id="7123456789",
            text="Some text",
        )
        assert sig1.startswith("pid:")
        
        # URL next
        sig2 = generate_composite_signature(
            url="https://linkedin.com/post/123",
            text="Some text",
        )
        assert sig2.startswith("url:")
        
        # Content fallback
        sig3 = generate_composite_signature(
            text="Some text",
            author="Author",
        )
        assert sig3.startswith("content:")


class TestLRUCache:
    """Tests for LRUCache memory cache."""
    
    def test_cache_add_and_contains(self):
        from scraper.post_cache import LRUCache
        
        cache = LRUCache(maxsize=100)
        
        cache.add("key1")
        
        assert cache.contains("key1") is True
        assert cache.contains("key2") is False
    
    def test_cache_eviction(self):
        from scraper.post_cache import LRUCache
        
        cache = LRUCache(maxsize=3)
        
        cache.add("key1")
        cache.add("key2")
        cache.add("key3")
        cache.add("key4")  # Should evict key1
        
        assert cache.contains("key1") is False
        assert cache.contains("key4") is True
    
    def test_cache_lru_behavior(self):
        from scraper.post_cache import LRUCache
        
        cache = LRUCache(maxsize=3)
        
        cache.add("key1")
        cache.add("key2")
        cache.add("key3")
        
        # Access key1 to make it recent
        cache.contains("key1")
        
        # Add new key, should evict key2 (least recent)
        cache.add("key4")
        
        assert cache.contains("key1") is True
        assert cache.contains("key2") is False
    
    def test_cache_remove(self):
        from scraper.post_cache import LRUCache
        
        cache = LRUCache(maxsize=100)
        
        cache.add("key1")
        assert cache.contains("key1") is True
        
        removed = cache.remove("key1")
        
        assert removed is True
        assert cache.contains("key1") is False
    
    def test_cache_clear(self):
        from scraper.post_cache import LRUCache
        
        cache = LRUCache(maxsize=100)
        
        cache.add("key1")
        cache.add("key2")
        
        count = cache.clear()
        
        assert count == 2
        assert cache.size() == 0
    
    def test_cache_stats(self):
        from scraper.post_cache import LRUCache
        
        cache = LRUCache(maxsize=100)
        cache.add("key1")
        cache.add("key2")
        
        stats = cache.get_stats()
        
        assert stats["size"] == 2
        assert stats["maxsize"] == 100
        assert stats["utilization"] == 0.02


class TestPersistentCache:
    """Tests for PersistentCache SQLite cache."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        try:
            os.unlink(f.name)
        except PermissionError:
            pass  # Ignore on Windows if file is locked
    
    def test_cache_initialization(self, temp_db):
        from scraper.post_cache import PersistentCache
        
        cache = PersistentCache(temp_db)
        
        assert cache._initialized is True
    
    def test_cache_add_and_contains(self, temp_db):
        from scraper.post_cache import PersistentCache
        
        cache = PersistentCache(temp_db)
        
        cache.add("sig1", source="test")
        
        assert cache.contains("sig1") is True
        assert cache.contains("sig2") is False
    
    def test_cache_persistence(self, temp_db):
        from scraper.post_cache import PersistentCache
        
        cache1 = PersistentCache(temp_db)
        cache1.add("sig1")
        
        # New instance
        cache2 = PersistentCache(temp_db)
        
        assert cache2.contains("sig1") is True
    
    def test_cache_remove(self, temp_db):
        from scraper.post_cache import PersistentCache
        
        cache = PersistentCache(temp_db)
        cache.add("sig1")
        
        removed = cache.remove("sig1")
        
        assert removed is True
        assert cache.contains("sig1") is False
    
    def test_cache_clear(self, temp_db):
        from scraper.post_cache import PersistentCache
        
        cache = PersistentCache(temp_db)
        cache.add("sig1")
        cache.add("sig2")
        
        count = cache.clear()
        
        assert count == 2
        assert cache.size() == 0


class TestPostCache:
    """Tests for unified PostCache."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        try:
            os.unlink(f.name)
        except PermissionError:
            pass  # Ignore on Windows if file is locked
    
    def test_is_duplicate_false_for_new(self, temp_db):
        from scraper.post_cache import PostCache, CacheConfig
        
        config = CacheConfig(persist_path=temp_db)
        cache = PostCache(config)
        
        is_dup = cache.is_duplicate(url="https://linkedin.com/post/123")
        
        assert is_dup is False
    
    def test_is_duplicate_true_after_mark(self, temp_db):
        from scraper.post_cache import PostCache, CacheConfig
        
        config = CacheConfig(persist_path=temp_db)
        cache = PostCache(config)
        
        cache.mark_processed(url="https://linkedin.com/post/123")
        is_dup = cache.is_duplicate(url="https://linkedin.com/post/123")
        
        assert is_dup is True
    
    def test_cache_uses_post_id_priority(self, temp_db):
        from scraper.post_cache import PostCache, CacheConfig
        
        config = CacheConfig(persist_path=temp_db)
        cache = PostCache(config)
        
        cache.mark_processed(post_id="7123")
        
        # Same post_id, different URL should be duplicate
        is_dup = cache.is_duplicate(
            post_id="7123",
            url="https://different-url.com",
        )
        
        assert is_dup is True
    
    def test_cache_stats(self, temp_db):
        from scraper.post_cache import PostCache, CacheConfig
        
        config = CacheConfig(persist_path=temp_db)
        cache = PostCache(config)
        
        # Some operations
        cache.is_duplicate(url="https://url1.com")
        cache.mark_processed(url="https://url1.com")
        cache.is_duplicate(url="https://url1.com")  # Should hit
        cache.is_duplicate(url="https://url2.com")  # Should miss
        
        stats = cache.get_stats()
        
        assert stats["checks"] == 3
        assert stats["additions"] == 1
        assert stats["hit_rate"] > 0
    
    def test_cache_health(self, temp_db):
        from scraper.post_cache import PostCache, CacheConfig
        
        config = CacheConfig(persist_path=temp_db)
        cache = PostCache(config)
        
        health = cache.get_health()
        
        assert "healthy" in health
        assert health["healthy"] is True
    
    def test_cache_remove(self, temp_db):
        from scraper.post_cache import PostCache, CacheConfig
        
        config = CacheConfig(persist_path=temp_db)
        cache = PostCache(config)
        
        cache.mark_processed(url="https://url1.com")
        assert cache.is_duplicate(url="https://url1.com") is True
        
        cache.remove(url="https://url1.com")
        assert cache.is_duplicate(url="https://url1.com") is False
    
    def test_clear_memory(self, temp_db):
        from scraper.post_cache import PostCache, CacheConfig
        
        config = CacheConfig(persist_path=temp_db)
        cache = PostCache(config)
        
        cache.mark_processed(url="https://url1.com")
        
        cache.clear_memory()
        
        # Should still find in persistent
        assert cache.is_duplicate(url="https://url1.com") is True
    
    def test_clear_all(self, temp_db):
        from scraper.post_cache import PostCache, CacheConfig
        
        config = CacheConfig(persist_path=temp_db)
        cache = PostCache(config)
        
        cache.mark_processed(url="https://url1.com")
        
        mem_count, persist_count = cache.clear_all()
        
        assert cache.is_duplicate(url="https://url1.com") is False


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            yield f.name
        try:
            os.unlink(f.name)
        except PermissionError:
            pass  # Ignore on Windows if file is locked
    
    def test_is_duplicate_function(self, temp_db):
        from scraper.post_cache import (
            is_duplicate, mark_processed, 
            get_post_cache, reset_post_cache, CacheConfig
        )
        
        reset_post_cache()
        
        # Patch default path
        import scraper.post_cache as cache_module
        original = cache_module.CacheConfig._default_path
        cache_module.CacheConfig._default_path = staticmethod(lambda: temp_db)
        
        try:
            assert is_duplicate(url="https://test.com") is False
            mark_processed(url="https://test.com")
            assert is_duplicate(url="https://test.com") is True
        finally:
            cache_module.CacheConfig._default_path = original
            reset_post_cache()
    
    def test_singleton_pattern(self, temp_db):
        from scraper.post_cache import (
            get_post_cache, reset_post_cache, CacheConfig
        )
        
        reset_post_cache()
        
        import scraper.post_cache as cache_module
        original = cache_module.CacheConfig._default_path
        cache_module.CacheConfig._default_path = staticmethod(lambda: temp_db)
        
        try:
            cache1 = get_post_cache()
            cache2 = get_post_cache()
            assert cache1 is cache2
        finally:
            cache_module.CacheConfig._default_path = original
            reset_post_cache()
