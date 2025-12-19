"""Robust metadata extraction with multi-fallback strategies.

This module provides reliable extraction of post metadata:
- Author name and title
- Post date (relative and absolute)
- Company information
- Permalink/Post ID

Each extraction method has multiple fallback strategies to handle
LinkedIn's frequent DOM changes.

Integration:
    - Call from scrape_subprocess.py or worker.py
    - Replace direct selector queries with these extractors

Author: Titan Scraper Team
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class AuthorInfo:
    """Extracted author information."""
    name: str = ""
    title: str = ""
    profile_url: str = ""
    confidence: float = 0.0  # 0-1
    extraction_method: str = ""
    
    @property
    def is_valid(self) -> bool:
        return bool(self.name.strip()) and self.confidence >= 0.3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "profile_url": self.profile_url,
            "confidence": round(self.confidence, 2),
            "extraction_method": self.extraction_method,
        }


@dataclass
class DateInfo:
    """Extracted date information."""
    raw_text: str = ""
    parsed_date: Optional[datetime] = None
    is_relative: bool = True
    age_hours: int = 0
    confidence: float = 0.0
    extraction_method: str = ""
    
    @property
    def is_valid(self) -> bool:
        return bool(self.parsed_date) and self.confidence >= 0.3
    
    @property
    def age_days(self) -> int:
        return self.age_hours // 24
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "parsed_date": self.parsed_date.isoformat() if self.parsed_date else None,
            "is_relative": self.is_relative,
            "age_hours": self.age_hours,
            "age_days": self.age_days,
            "confidence": round(self.confidence, 2),
            "extraction_method": self.extraction_method,
        }


@dataclass
class CompanyInfo:
    """Extracted company information."""
    name: str = ""
    linkedin_url: str = ""
    industry: str = ""
    confidence: float = 0.0
    extraction_method: str = ""
    
    @property
    def is_valid(self) -> bool:
        return bool(self.name.strip()) and self.confidence >= 0.3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "linkedin_url": self.linkedin_url,
            "industry": self.industry,
            "confidence": round(self.confidence, 2),
            "extraction_method": self.extraction_method,
        }


@dataclass
class PermalinkInfo:
    """Extracted permalink information."""
    url: str = ""
    post_id: str = ""
    is_activity: bool = True  # vs ugcPost
    confidence: float = 0.0
    extraction_method: str = ""
    
    @property
    def is_valid(self) -> bool:
        return bool(self.post_id) and self.confidence >= 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "post_id": self.post_id,
            "is_activity": self.is_activity,
            "confidence": round(self.confidence, 2),
            "extraction_method": self.extraction_method,
        }


@dataclass
class PostMetadata:
    """Complete post metadata."""
    author: AuthorInfo = field(default_factory=AuthorInfo)
    date: DateInfo = field(default_factory=DateInfo)
    company: CompanyInfo = field(default_factory=CompanyInfo)
    permalink: PermalinkInfo = field(default_factory=PermalinkInfo)
    
    @property
    def overall_confidence(self) -> float:
        """Average confidence of all extracted fields."""
        confidences = [
            self.author.confidence,
            self.date.confidence,
            self.permalink.confidence,
        ]
        if self.company.confidence > 0:
            confidences.append(self.company.confidence)
        return sum(confidences) / len(confidences) if confidences else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "author": self.author.to_dict(),
            "date": self.date.to_dict(),
            "company": self.company.to_dict(),
            "permalink": self.permalink.to_dict(),
            "overall_confidence": round(self.overall_confidence, 2),
        }


# =============================================================================
# DATE PARSING
# =============================================================================

# French relative time patterns
FR_RELATIVE_PATTERNS: List[Tuple[re.Pattern, int]] = [
    # Hours
    (re.compile(r"il y a (\d+)\s*h", re.I), 1),  # "il y a 2h"
    (re.compile(r"il y a (\d+)\s*heure", re.I), 1),
    (re.compile(r"(\d+)\s*h(?:eure)?s?\s*ago", re.I), 1),
    
    # Days
    (re.compile(r"il y a (\d+)\s*j", re.I), 24),  # "il y a 3j"
    (re.compile(r"il y a (\d+)\s*jour", re.I), 24),
    (re.compile(r"(\d+)\s*d(?:ay)?s?\s*ago", re.I), 24),
    
    # Weeks
    (re.compile(r"il y a (\d+)\s*sem", re.I), 168),  # "il y a 1 semaine"
    (re.compile(r"il y a (\d+)\s*w", re.I), 168),
    (re.compile(r"(\d+)\s*w(?:eek)?s?\s*ago", re.I), 168),
    
    # Months
    (re.compile(r"il y a (\d+)\s*mois", re.I), 720),
    (re.compile(r"(\d+)\s*mo(?:nth)?s?\s*ago", re.I), 720),
    
    # Minutes
    (re.compile(r"il y a (\d+)\s*min", re.I), 0),  # < 1 hour
    (re.compile(r"(\d+)\s*min(?:ute)?s?\s*ago", re.I), 0),
    
    # Just now
    (re.compile(r"à l'instant|maintenant|just now|now", re.I), 0),
]

# Absolute date patterns
FR_ABSOLUTE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # "15 janvier 2024"
    (re.compile(r"(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})", re.I), "%d %B %Y"),
    # "15/01/2024"
    (re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"), "%d/%m/%Y"),
    # "2024-01-15"
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "%Y-%m-%d"),
]

FR_MONTH_MAP = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "fevrier": 2, "aout": 8,  # Without accents
}


def parse_relative_date(text: str) -> Tuple[Optional[datetime], int, float]:
    """Parse relative date text.
    
    Returns:
        (parsed_datetime, age_hours, confidence)
    """
    text = text.lower().strip()
    
    for pattern, hours_per_unit in FR_RELATIVE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                if hours_per_unit == 0 and "instant" in text or "now" in text:
                    # Just now
                    return datetime.now(timezone.utc), 0, 0.9
                
                groups = match.groups()
                if groups:
                    value = int(groups[0])
                else:
                    value = 1  # "il y a 1 heure" might just say "il y a une heure"
                
                age_hours = value * hours_per_unit if hours_per_unit > 0 else 0
                parsed = datetime.now(timezone.utc) - timedelta(hours=age_hours)
                return parsed, age_hours, 0.8
            except (ValueError, IndexError):
                continue
    
    return None, 0, 0.0


def parse_absolute_date(text: str) -> Tuple[Optional[datetime], float]:
    """Parse absolute date text.
    
    Returns:
        (parsed_datetime, confidence)
    """
    text = text.lower().strip()
    
    # French month pattern
    month_pattern = r"(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre)\s+(\d{4})"
    match = re.search(month_pattern, text, re.I)
    if match:
        try:
            day = int(match.group(1))
            month_name = match.group(2).lower()
            year = int(match.group(3))
            month = FR_MONTH_MAP.get(month_name, 0)
            if month:
                return datetime(year, month, day, tzinfo=timezone.utc), 0.9
        except (ValueError, KeyError):
            pass
    
    # Numeric patterns
    for pattern, _ in FR_ABSOLUTE_PATTERNS[1:]:  # Skip French month (already handled)
        match = pattern.search(text)
        if match:
            try:
                groups = match.groups()
                if len(groups) == 3:
                    if int(groups[0]) > 100:  # YYYY-MM-DD
                        year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                    else:  # DD/MM/YYYY
                        day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                    return datetime(year, month, day, tzinfo=timezone.utc), 0.85
            except ValueError:
                continue
    
    return None, 0.0


def extract_date_from_text(text: str) -> DateInfo:
    """Extract date from any text format.
    
    Tries relative parsing first, then absolute.
    """
    if not text:
        return DateInfo(confidence=0.0)
    
    # Try relative first (more common on LinkedIn)
    parsed, age_hours, confidence = parse_relative_date(text)
    if parsed:
        return DateInfo(
            raw_text=text,
            parsed_date=parsed,
            is_relative=True,
            age_hours=age_hours,
            confidence=confidence,
            extraction_method="relative_pattern",
        )
    
    # Try absolute
    parsed, confidence = parse_absolute_date(text)
    if parsed:
        age_hours = int((datetime.now(timezone.utc) - parsed).total_seconds() / 3600)
        return DateInfo(
            raw_text=text,
            parsed_date=parsed,
            is_relative=False,
            age_hours=max(0, age_hours),
            confidence=confidence,
            extraction_method="absolute_pattern",
        )
    
    return DateInfo(raw_text=text, confidence=0.0, extraction_method="failed")


# =============================================================================
# AUTHOR EXTRACTION
# =============================================================================

def extract_author_from_element(
    name_text: str = "",
    title_text: str = "",
    profile_url: str = "",
) -> AuthorInfo:
    """Extract and validate author information.
    
    Args:
        name_text: Raw name text from DOM
        title_text: Raw title/description text
        profile_url: Author's LinkedIn profile URL
    """
    # Clean name
    name = clean_author_name(name_text)
    
    # Clean title
    title = clean_author_title(title_text)
    
    # Validate URL
    clean_url = ""
    if profile_url:
        parsed = urlparse(profile_url)
        if "linkedin.com" in parsed.netloc:
            clean_url = profile_url.split("?")[0]  # Remove query params
    
    # Calculate confidence
    confidence = 0.0
    method_parts = []
    
    if name:
        confidence += 0.5
        method_parts.append("name")
    
    if title:
        confidence += 0.3
        method_parts.append("title")
    
    if clean_url:
        confidence += 0.2
        method_parts.append("url")
    
    return AuthorInfo(
        name=name,
        title=title,
        profile_url=clean_url,
        confidence=min(1.0, confidence),
        extraction_method="+".join(method_parts) if method_parts else "none",
    )


def clean_author_name(raw: str) -> str:
    """Clean author name from LinkedIn formatting."""
    if not raw:
        return ""
    
    # Remove common suffixes
    name = raw.strip()
    
    # Remove LinkedIn connection indicators
    patterns_to_remove = [
        r"\s*\(.*?\)\s*$",  # (He/Him), (LION), etc.
        r"\s*•.*$",  # • 1st, • 2nd, etc.
        r"\s*\|\s*\d+(st|nd|rd|th)?.*$",
        r"\s*\d+(st|nd|rd|th)\s*$",
        r"\s*🔵.*$",  # Emoji badges
        r"\s*✓.*$",
        r"\s*👉.*$",
    ]
    
    for pattern in patterns_to_remove:
        name = re.sub(pattern, "", name, flags=re.I)
    
    # Remove extra whitespace
    name = " ".join(name.split())
    
    # Validate: should have at least first and last name
    parts = name.split()
    if len(parts) < 2:
        return name  # Keep single name but lower confidence
    
    return name


def clean_author_title(raw: str) -> str:
    """Clean author title/headline."""
    if not raw:
        return ""
    
    title = raw.strip()
    
    # Remove "View profile" etc.
    patterns_to_remove = [
        r"^View.*profile.*$",
        r"^Voir.*profil.*$",
        r"^\d+\s*followers?.*$",
        r"^\d+\s*abonnés?.*$",
    ]
    
    for pattern in patterns_to_remove:
        if re.match(pattern, title, re.I):
            return ""
    
    # Truncate if too long
    if len(title) > 200:
        title = title[:200] + "..."
    
    return " ".join(title.split())


# =============================================================================
# COMPANY EXTRACTION
# =============================================================================

def extract_company_from_elements(
    company_name: str = "",
    company_url: str = "",
    author_title: str = "",
) -> CompanyInfo:
    """Extract company information with fallbacks.
    
    Args:
        company_name: Direct company name from DOM
        company_url: Company LinkedIn page URL
        author_title: Author's title (may contain company)
    """
    name = ""
    url = ""
    confidence = 0.0
    method = []
    
    # Primary: direct company name
    if company_name:
        name = clean_company_name(company_name)
        confidence = 0.9
        method.append("direct")
    
    # Fallback: extract from URL
    if not name and company_url:
        name = extract_company_from_url(company_url)
        url = company_url.split("?")[0]
        if name:
            confidence = 0.7
            method.append("url")
    
    # Fallback: extract from author title
    if not name and author_title:
        name = extract_company_from_title(author_title)
        if name:
            confidence = 0.5
            method.append("title")
    
    # Validate URL
    if company_url and "linkedin.com/company" in company_url:
        url = company_url.split("?")[0]
    
    return CompanyInfo(
        name=name,
        linkedin_url=url,
        confidence=confidence,
        extraction_method="+".join(method) if method else "none",
    )


def clean_company_name(raw: str) -> str:
    """Clean company name."""
    if not raw:
        return ""
    
    name = raw.strip()
    
    # Remove follower counts
    name = re.sub(r"\s*\|\s*\d+.*followers?.*$", "", name, flags=re.I)
    name = re.sub(r"\s*\|\s*\d+.*abonnés?.*$", "", name, flags=re.I)
    name = re.sub(r"\s*•\s*\d+.*$", "", name)
    
    return " ".join(name.split())


def extract_company_from_url(url: str) -> str:
    """Extract company name from LinkedIn company URL."""
    if not url or "linkedin.com/company" not in url:
        return ""
    
    try:
        path = urlparse(url).path
        # /company/company-name/
        match = re.search(r"/company/([^/]+)", path)
        if match:
            slug = match.group(1)
            # Convert slug to readable name
            name = slug.replace("-", " ").replace("_", " ")
            return name.title()
    except Exception:
        pass
    
    return ""


def extract_company_from_title(title: str) -> str:
    """Extract company name from author title.
    
    Common patterns:
    - "Juriste chez CompanyName"
    - "Legal Counsel at CompanyName"
    - "CompanyName | Juriste"
    """
    if not title:
        return ""
    
    patterns = [
        r"(?:chez|at|@)\s+([A-Z][A-Za-zÀ-ÿ\s&\-\.]+?)(?:\s*\||$|\s*-\s*|,)",
        r"^([A-Z][A-Za-zÀ-ÿ\s&\-\.]+?)\s*\|",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            company = match.group(1).strip()
            # Validate: not too short, not a job title
            if len(company) > 3 and not is_job_title(company):
                return company
    
    return ""


def is_job_title(text: str) -> bool:
    """Check if text looks like a job title rather than company."""
    job_indicators = [
        "juriste", "avocat", "legal", "counsel", "manager",
        "directeur", "responsable", "chief", "head of",
    ]
    text_lower = text.lower()
    return any(ind in text_lower for ind in job_indicators)


# =============================================================================
# PERMALINK EXTRACTION
# =============================================================================

def extract_permalink_from_element(
    url: str = "",
    post_urn: str = "",
) -> PermalinkInfo:
    """Extract permalink and post ID.
    
    Args:
        url: Full permalink URL
        post_urn: Post URN (urn:li:activity:xxx)
    """
    post_id = ""
    clean_url = ""
    is_activity = True
    confidence = 0.0
    method = []
    
    # Try URN first
    if post_urn:
        match = re.search(r"urn:li:(activity|ugcPost):(\d+)", post_urn)
        if match:
            is_activity = match.group(1) == "activity"
            post_id = match.group(2)
            confidence = 0.95
            method.append("urn")
    
    # Try URL
    if url:
        clean_url = url.split("?")[0]  # Remove query params
        
        if not post_id:
            # Extract from activity URL
            match = re.search(r"/feed/update/urn:li:activity:(\d+)", url)
            if match:
                post_id = match.group(1)
                is_activity = True
                confidence = 0.9
                method.append("url_activity")
            else:
                # Extract from ugcPost URL
                match = re.search(r"/feed/update/urn:li:ugcPost:(\d+)", url)
                if match:
                    post_id = match.group(1)
                    is_activity = False
                    confidence = 0.9
                    method.append("url_ugcpost")
    
    # Generate synthetic ID if nothing found
    if not post_id and clean_url:
        post_id = hashlib.md5(clean_url.encode()).hexdigest()[:16]
        confidence = 0.5
        method.append("hash")
    
    return PermalinkInfo(
        url=clean_url,
        post_id=post_id,
        is_activity=is_activity,
        confidence=confidence,
        extraction_method="+".join(method) if method else "none",
    )


# =============================================================================
# MAIN EXTRACTOR CLASS
# =============================================================================

class MetadataExtractor:
    """Unified metadata extractor with multi-fallback strategies."""
    
    def __init__(self):
        self._extraction_stats = {
            "author_success": 0,
            "author_fail": 0,
            "date_success": 0,
            "date_fail": 0,
            "company_success": 0,
            "company_fail": 0,
            "permalink_success": 0,
            "permalink_fail": 0,
        }
    
    def extract_from_post_element(
        self,
        text_content: str = "",
        author_name: str = "",
        author_title: str = "",
        author_url: str = "",
        date_text: str = "",
        company_name: str = "",
        company_url: str = "",
        permalink: str = "",
        post_urn: str = "",
    ) -> PostMetadata:
        """Extract all metadata from raw element data.
        
        Args:
            text_content: Post text (for fallback extraction)
            author_name: Author name from DOM
            author_title: Author title/headline
            author_url: Author profile URL
            date_text: Date text from DOM
            company_name: Company name from DOM
            company_url: Company page URL
            permalink: Post permalink
            post_urn: Post URN
            
        Returns:
            Complete PostMetadata object
        """
        # Extract author
        author = extract_author_from_element(
            name_text=author_name,
            title_text=author_title,
            profile_url=author_url,
        )
        if author.is_valid:
            self._extraction_stats["author_success"] += 1
        else:
            self._extraction_stats["author_fail"] += 1
        
        # Extract date
        date = extract_date_from_text(date_text)
        if date.is_valid:
            self._extraction_stats["date_success"] += 1
        else:
            self._extraction_stats["date_fail"] += 1
        
        # Extract company (with fallback to author title)
        company = extract_company_from_elements(
            company_name=company_name,
            company_url=company_url,
            author_title=author_title,
        )
        if company.is_valid:
            self._extraction_stats["company_success"] += 1
        else:
            self._extraction_stats["company_fail"] += 1
        
        # Extract permalink
        plink = extract_permalink_from_element(
            url=permalink,
            post_urn=post_urn,
        )
        if plink.is_valid:
            self._extraction_stats["permalink_success"] += 1
        else:
            self._extraction_stats["permalink_fail"] += 1
        
        return PostMetadata(
            author=author,
            date=date,
            company=company,
            permalink=plink,
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get extraction statistics."""
        total = sum(self._extraction_stats.values()) // 4 or 1
        return {
            "total_extractions": total,
            "success_rates": {
                "author": round(self._extraction_stats["author_success"] / max(1, self._extraction_stats["author_success"] + self._extraction_stats["author_fail"]), 2),
                "date": round(self._extraction_stats["date_success"] / max(1, self._extraction_stats["date_success"] + self._extraction_stats["date_fail"]), 2),
                "company": round(self._extraction_stats["company_success"] / max(1, self._extraction_stats["company_success"] + self._extraction_stats["company_fail"]), 2),
                "permalink": round(self._extraction_stats["permalink_success"] / max(1, self._extraction_stats["permalink_success"] + self._extraction_stats["permalink_fail"]), 2),
            },
            "raw_stats": self._extraction_stats.copy(),
        }


# =============================================================================
# SINGLETON
# =============================================================================

_extractor_instance: Optional[MetadataExtractor] = None


def get_metadata_extractor() -> MetadataExtractor:
    """Get or create metadata extractor singleton."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = MetadataExtractor()
    return _extractor_instance


def reset_metadata_extractor() -> None:
    """Reset singleton (for testing)."""
    global _extractor_instance
    _extractor_instance = None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def extract_metadata(
    text_content: str = "",
    author_name: str = "",
    author_title: str = "",
    author_url: str = "",
    date_text: str = "",
    company_name: str = "",
    company_url: str = "",
    permalink: str = "",
    post_urn: str = "",
) -> PostMetadata:
    """Convenience function for metadata extraction."""
    return get_metadata_extractor().extract_from_post_element(
        text_content=text_content,
        author_name=author_name,
        author_title=author_title,
        author_url=author_url,
        date_text=date_text,
        company_name=company_name,
        company_url=company_url,
        permalink=permalink,
        post_urn=post_urn,
    )


__all__ = [
    # Classes
    "MetadataExtractor",
    "PostMetadata",
    "AuthorInfo",
    "DateInfo",
    "CompanyInfo",
    "PermalinkInfo",
    
    # Functions
    "get_metadata_extractor",
    "reset_metadata_extractor",
    "extract_metadata",
    "extract_date_from_text",
    "extract_author_from_element",
    "extract_company_from_elements",
    "extract_permalink_from_element",
]
