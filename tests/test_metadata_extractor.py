"""Tests for scraper/metadata_extractor.py - Robust metadata extraction."""
import pytest
from datetime import datetime, timezone, timedelta


class TestDateParsing:
    """Tests for date parsing functions."""
    
    def test_parse_relative_hours(self):
        from scraper.metadata_extractor import parse_relative_date
        
        parsed, age_hours, confidence = parse_relative_date("il y a 2h")
        
        assert parsed is not None
        assert age_hours == 2
        assert confidence > 0.5
    
    def test_parse_relative_days(self):
        from scraper.metadata_extractor import parse_relative_date
        
        parsed, age_hours, confidence = parse_relative_date("il y a 3 jours")
        
        assert parsed is not None
        assert age_hours == 72  # 3 * 24
        assert confidence > 0.5
    
    def test_parse_relative_weeks(self):
        from scraper.metadata_extractor import parse_relative_date
        
        parsed, age_hours, confidence = parse_relative_date("il y a 1 semaine")
        
        assert parsed is not None
        assert age_hours == 168  # 7 * 24
    
    def test_parse_relative_english(self):
        from scraper.metadata_extractor import parse_relative_date
        
        parsed, age_hours, confidence = parse_relative_date("2 days ago")
        
        assert parsed is not None
        assert age_hours == 48
    
    def test_parse_just_now(self):
        from scraper.metadata_extractor import parse_relative_date
        
        parsed, age_hours, confidence = parse_relative_date("à l'instant")
        
        assert parsed is not None
        assert age_hours == 0
        assert confidence > 0.8
    
    def test_parse_absolute_french(self):
        from scraper.metadata_extractor import parse_absolute_date
        
        parsed, confidence = parse_absolute_date("15 janvier 2024")
        
        assert parsed is not None
        assert parsed.day == 15
        assert parsed.month == 1
        assert parsed.year == 2024
    
    def test_parse_absolute_numeric(self):
        from scraper.metadata_extractor import parse_absolute_date
        
        parsed, confidence = parse_absolute_date("15/03/2024")
        
        assert parsed is not None
        assert parsed.day == 15
        assert parsed.month == 3
        assert parsed.year == 2024
    
    def test_parse_invalid_date(self):
        from scraper.metadata_extractor import parse_relative_date
        
        parsed, age_hours, confidence = parse_relative_date("not a date")
        
        assert parsed is None
        assert confidence == 0.0
    
    def test_extract_date_from_text(self):
        from scraper.metadata_extractor import extract_date_from_text
        
        result = extract_date_from_text("il y a 5h")
        
        assert result.is_valid is True
        assert result.is_relative is True
        assert result.age_hours == 5


class TestAuthorExtraction:
    """Tests for author extraction."""
    
    def test_clean_author_name_simple(self):
        from scraper.metadata_extractor import clean_author_name
        
        cleaned = clean_author_name("Jean Dupont")
        assert cleaned == "Jean Dupont"
    
    def test_clean_author_name_with_suffix(self):
        from scraper.metadata_extractor import clean_author_name
        
        cleaned = clean_author_name("Jean Dupont (He/Him)")
        assert cleaned == "Jean Dupont"
        
        cleaned2 = clean_author_name("Marie Martin • 1st")
        assert cleaned2 == "Marie Martin"
    
    def test_clean_author_name_with_emoji(self):
        from scraper.metadata_extractor import clean_author_name
        
        cleaned = clean_author_name("Jean Dupont 🔵 Top Voice")
        assert "🔵" not in cleaned
    
    def test_clean_author_title(self):
        from scraper.metadata_extractor import clean_author_title
        
        cleaned = clean_author_title("Juriste chez Total")
        assert cleaned == "Juriste chez Total"
    
    def test_clean_author_title_removes_view_profile(self):
        from scraper.metadata_extractor import clean_author_title
        
        cleaned = clean_author_title("View Jean's profile")
        assert cleaned == ""
    
    def test_extract_author_from_element(self):
        from scraper.metadata_extractor import extract_author_from_element
        
        result = extract_author_from_element(
            name_text="Jean Dupont",
            title_text="Directeur Juridique chez Total",
            profile_url="https://www.linkedin.com/in/jeandupont",
        )
        
        assert result.is_valid is True
        assert result.name == "Jean Dupont"
        assert "linkedin.com" in result.profile_url
        assert result.confidence > 0.5


class TestCompanyExtraction:
    """Tests for company extraction."""
    
    def test_clean_company_name(self):
        from scraper.metadata_extractor import clean_company_name
        
        cleaned = clean_company_name("TotalEnergies | 5M followers")
        assert cleaned == "TotalEnergies"
    
    def test_extract_company_from_url(self):
        from scraper.metadata_extractor import extract_company_from_url
        
        name = extract_company_from_url(
            "https://www.linkedin.com/company/totalenergies/"
        )
        
        assert name.lower() == "totalenergies"
    
    def test_extract_company_from_title(self):
        from scraper.metadata_extractor import extract_company_from_title
        
        name = extract_company_from_title("Juriste chez Société Générale")
        
        assert "Société Générale" in name or "Societe Generale" in name
    
    def test_extract_company_from_title_at(self):
        from scraper.metadata_extractor import extract_company_from_title
        
        name = extract_company_from_title("Legal Counsel at Google France")
        
        assert "Google" in name
    
    def test_extract_company_from_elements(self):
        from scraper.metadata_extractor import extract_company_from_elements
        
        result = extract_company_from_elements(
            company_name="BNP Paribas",
            company_url="https://www.linkedin.com/company/bnp-paribas/",
        )
        
        assert result.is_valid is True
        assert "BNP Paribas" in result.name


class TestPermalinkExtraction:
    """Tests for permalink extraction."""
    
    def test_extract_from_activity_url(self):
        from scraper.metadata_extractor import extract_permalink_from_element
        
        result = extract_permalink_from_element(
            url="https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678"
        )
        
        assert result.is_valid is True
        assert result.post_id == "7123456789012345678"
        assert result.is_activity is True
    
    def test_extract_from_ugcpost_url(self):
        from scraper.metadata_extractor import extract_permalink_from_element
        
        result = extract_permalink_from_element(
            url="https://www.linkedin.com/feed/update/urn:li:ugcPost:7123456789012345678"
        )
        
        assert result.is_valid is True
        assert result.is_activity is False
    
    def test_extract_from_urn(self):
        from scraper.metadata_extractor import extract_permalink_from_element
        
        result = extract_permalink_from_element(
            post_urn="urn:li:activity:7123456789012345678"
        )
        
        assert result.is_valid is True
        assert result.post_id == "7123456789012345678"
    
    def test_hash_fallback(self):
        from scraper.metadata_extractor import extract_permalink_from_element
        
        result = extract_permalink_from_element(
            url="https://www.linkedin.com/some/weird/url"
        )
        
        assert result.post_id != ""  # Should have a hash-based ID
        assert result.confidence < 0.9


class TestPostMetadata:
    """Tests for complete PostMetadata."""
    
    def test_metadata_creation(self):
        from scraper.metadata_extractor import PostMetadata, AuthorInfo, DateInfo
        
        metadata = PostMetadata(
            author=AuthorInfo(name="Test", confidence=0.8),
            date=DateInfo(confidence=0.7),
        )
        
        assert metadata.author.name == "Test"
    
    def test_overall_confidence(self):
        from scraper.metadata_extractor import (
            PostMetadata, AuthorInfo, DateInfo, 
            CompanyInfo, PermalinkInfo
        )
        
        metadata = PostMetadata(
            author=AuthorInfo(name="Test", confidence=0.8),
            date=DateInfo(confidence=0.6),
            company=CompanyInfo(confidence=0.0),  # Not extracted
            permalink=PermalinkInfo(post_id="123", confidence=0.9),
        )
        
        # Should average author, date, permalink (company is 0)
        assert 0.5 < metadata.overall_confidence < 0.9
    
    def test_metadata_to_dict(self):
        from scraper.metadata_extractor import PostMetadata
        
        metadata = PostMetadata()
        d = metadata.to_dict()
        
        assert "author" in d
        assert "date" in d
        assert "company" in d
        assert "permalink" in d
        assert "overall_confidence" in d


class TestMetadataExtractor:
    """Tests for MetadataExtractor class."""
    
    def test_extract_from_post_element(self):
        from scraper.metadata_extractor import MetadataExtractor
        
        extractor = MetadataExtractor()
        
        metadata = extractor.extract_from_post_element(
            text_content="Nous recrutons un juriste",
            author_name="Jean Dupont",
            author_title="DRH chez Total",
            author_url="https://linkedin.com/in/jean",
            date_text="il y a 2 jours",
            company_name="Total",
            company_url="https://linkedin.com/company/total",
            permalink="https://linkedin.com/feed/update/urn:li:activity:123",
        )
        
        assert metadata.author.is_valid is True
        assert metadata.date.is_valid is True
        assert metadata.company.is_valid is True
        assert metadata.permalink.is_valid is True
    
    def test_extractor_stats(self):
        from scraper.metadata_extractor import MetadataExtractor
        
        extractor = MetadataExtractor()
        
        # Extract a few times
        for _ in range(3):
            extractor.extract_from_post_element(
                author_name="Test User",
                date_text="il y a 1h",
            )
        
        stats = extractor.get_stats()
        
        assert stats["total_extractions"] == 3
        assert "success_rates" in stats


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_extract_metadata(self):
        from scraper.metadata_extractor import extract_metadata
        
        result = extract_metadata(
            author_name="Test User",
            date_text="il y a 5h",
        )
        
        assert result.author.name == "Test User"
        assert result.date.age_hours == 5
    
    def test_singleton_pattern(self):
        from scraper.metadata_extractor import (
            get_metadata_extractor, reset_metadata_extractor
        )
        
        reset_metadata_extractor()
        
        ext1 = get_metadata_extractor()
        ext2 = get_metadata_extractor()
        
        assert ext1 is ext2
        
        reset_metadata_extractor()
