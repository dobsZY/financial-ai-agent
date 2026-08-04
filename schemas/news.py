from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NewsSource(StrEnum):
    KAP = "KAP"
    SEC = "SEC"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NewsItem(BaseModel):
    """Scraper cikisi; `external_id` kaynak icinde tekildir (dedup icin)."""

    model_config = ConfigDict(frozen=True)

    source: NewsSource
    external_id: str
    title: str
    ticker: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    raw_text: str | None = None

    @property
    def content(self) -> str:
        return f"{self.title}\n\n{self.raw_text or ''}".strip()


class LLMSummary(BaseModel):
    """Gemini'nin zorunlu JSON semasi (2.8)."""

    sentiment: float = Field(ge=-1.0, le=1.0)
    bullets: list[str] = Field(min_length=1, max_length=5)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    model: str = ""
    tokens: int | None = None

    @field_validator("bullets")
    @classmethod
    def _strip_bullets(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("bullets bos olamaz")
        return cleaned


class NewsRead(BaseModel):
    """API cikti sozlesmesi: haber + (varsa) LLM ozeti."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    title: str
    ticker: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    sentiment: float | None = None
    bullets: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    model: str | None = None


LLM_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "number"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["sentiment", "bullets", "risk_level"],
}
