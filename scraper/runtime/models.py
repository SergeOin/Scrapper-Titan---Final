from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass(slots=True)
class RuntimePost:
    """Lightweight representation of a scraped or mock-generated post."""

    id: str
    keyword: str
    author: str
    author_profile: Optional[str]
    text: str
    language: str
    published_at: Optional[str]
    collected_at: str
    company: Optional[str] = None
    permalink: Optional[str] = None
    score: Optional[float] = None
    raw: Optional[dict[str, Any]] = None


@dataclass(slots=True)
class JobResult:
    """Aggregate result for a runtime job execution."""

    posts: list[RuntimePost]
    unknown_authors: int
    mode: str
    started_at: datetime
    finished_at: datetime

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.finished_at - self.started_at).total_seconds())
