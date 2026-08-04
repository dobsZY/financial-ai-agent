from __future__ import annotations

import json

from fastapi import APIRouter, Query

from core.pipeline import backfill_summaries
from database import db_manager
from database.models import LLMSummary, NewsItem
from schemas.news import NewsRead

router = APIRouter(tags=["news"])


def _to_read(item: NewsItem, ticker: str | None, summary: LLMSummary | None) -> NewsRead:
    bullets: list[str] = []
    if summary is not None:
        try:
            bullets = json.loads(summary.bullets_json)
        except (ValueError, TypeError):
            bullets = []

    return NewsRead(
        id=item.id,
        source=item.source,
        title=item.title,
        ticker=ticker,
        url=item.url,
        published_at=item.published_at,
        created_at=item.created_at,
        sentiment=summary.sentiment if summary else None,
        bullets=bullets,
        risk_level=summary.risk_level if summary else None,
        model=summary.model if summary else None,
    )


@router.post("/news/summarize")
async def summarize_pending(
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, int]:
    """Kota kesintisinde ozetsiz kalan haberleri tamamlar."""
    return await backfill_summaries(limit=limit)


@router.get("/news", response_model=list[NewsRead])
async def list_news(
    limit: int = Query(default=50, ge=1, le=200),
    ticker: str | None = None,
    source: str | None = Query(default=None, description="KAP veya SEC"),
) -> list[NewsRead]:
    rows = await db_manager.list_news(limit=limit, ticker=ticker, source=source)
    return [_to_read(item, symbol_ticker, summary) for item, symbol_ticker, summary in rows]
