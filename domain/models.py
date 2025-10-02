from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

class PostModel(BaseModel):
    """Canonical in-memory representation of a post.

    This model is Pydantic-only (not an ORM) and is used to decouple
    route / worker logic from raw dicts. Persistence layers convert
    to/from this structure.
    """
    id: str = Field(..., description="Deterministic id (hash/permalink composite)")
    keyword: str
    author: str
    author_profile: Optional[str] = None
    company: Optional[str] = None
    text: str
    language: str
    published_at: Optional[str] = Field(None, description="ISO8601 date when published")
    collected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    permalink: Optional[str] = None
    raw: dict[str, Any] | None = None

    @property
    def is_demo(self) -> bool:
        a = (self.author or '').lower()
        k = (self.keyword or '').lower()
        return a == 'demo_recruteur' or k == 'demo_recruteur'

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "_id": self.id,
            "keyword": self.keyword,
            "author": self.author,
            "author_profile": self.author_profile,
            "company": self.company,
            "text": self.text,
            "language": self.language,
            "published_at": self.published_at,
            "collected_at": self.collected_at,
            "permalink": self.permalink,
            "raw": self.raw or {},
        }

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> "PostModel":
        return cls(
            id=str(data.get("_id") or data.get("id")),
            keyword=data.get("keyword", ""),
            author=data.get("author", "Unknown"),
            author_profile=data.get("author_profile"),
            company=data.get("company"),
            text=data.get("text", ""),
            language=data.get("language", ""),
            published_at=data.get("published_at"),
            collected_at=data.get("collected_at") or datetime.utcnow().isoformat(),
            permalink=data.get("permalink"),
            raw=data.get("raw") or {},
        )
