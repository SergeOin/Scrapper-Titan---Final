from scraper.core import mock as mock_core

class DummySettings:
    recruitment_signal_threshold = 0.05

def test_generate_mock_posts_basic():
    settings = DummySettings()
    posts = mock_core.generate_mock_posts("juriste", 3, settings, settings.recruitment_signal_threshold)
    assert len(posts) == 3
    assert all(p["keyword"] == "juriste" for p in posts)
    # At least a permalink and id
    assert all(p.get("id") and p.get("permalink") for p in posts)
