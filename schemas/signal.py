from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class Pattern(StrEnum):
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    HEAD_SHOULDERS = "head_shoulders"
    INV_HEAD_SHOULDERS = "inv_head_shoulders"
    ASC_TRIANGLE = "asc_triangle"
    DESC_TRIANGLE = "desc_triangle"
    BULL_FLAG = "bull_flag"
    BEAR_FLAG = "bear_flag"
    CUP_HANDLE = "cup_handle"


PATTERN_DIRECTION: dict[Pattern, Direction] = {
    Pattern.DOUBLE_TOP: Direction.SHORT,
    Pattern.DOUBLE_BOTTOM: Direction.LONG,
    Pattern.HEAD_SHOULDERS: Direction.SHORT,
    Pattern.INV_HEAD_SHOULDERS: Direction.LONG,
    Pattern.ASC_TRIANGLE: Direction.LONG,
    Pattern.DESC_TRIANGLE: Direction.SHORT,
    Pattern.BULL_FLAG: Direction.LONG,
    Pattern.BEAR_FLAG: Direction.SHORT,
    Pattern.CUP_HANDLE: Direction.LONG,
}

PATTERN_CLASS_NAMES: tuple[str, ...] = tuple(pattern.value for pattern in Pattern)


class BoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    x1: float
    y1: float
    x2: float
    y2: float


class Detection(BaseModel):
    """Bir analiz modulunun urettigi tek formasyon tespiti."""

    model_config = ConfigDict(frozen=True)

    pattern: Pattern
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    direction: Direction | None = None
    box: BoundingBox | None = None
    meta: dict[str, float | str] = Field(default_factory=dict)

    @property
    def resolved_direction(self) -> Direction:
        return self.direction or PATTERN_DIRECTION[self.pattern]


class SignalCandidate(BaseModel):
    """Skorlama oncesi birlestirilmis sinyal adayi (Faz 3'te puanlanir)."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    interval: str
    detection: Detection
    bucket_ts: datetime
    price: float | None = None
    indicator_score: float = 0.0
    sentiment: float = 0.0
    final_score: float | None = None
    chart_hash: str | None = None

    @property
    def pattern(self) -> Pattern:
        return self.detection.pattern

    @property
    def direction(self) -> Direction:
        return self.detection.resolved_direction
