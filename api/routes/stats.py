from __future__ import annotations

from fastapi import APIRouter, Query

from core.logger import get_logger
from core.pipeline import evaluate_outcomes
from core.stats import StatsReport, build_stats
from database import db_manager

logger = get_logger(__name__)

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsReport)
async def get_stats(days: int | None = Query(default=None, ge=1, le=3650)) -> StatsReport:
    """Kaydedilmis sinyal sonuclarindan isabet istatistigi.

    `days` verilirse yalnizca o donemde uretilen sinyaller hesaba katilir.
    """
    return build_stats(await db_manager.outcome_rows(days=days))


@router.post("/stats/evaluate")
async def evaluate(
    horizon: int | None = Query(default=None, ge=1, le=200),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, int]:
    """Bekleyen sinyalleri simdi degerlendirir (zamanlanmis is de ayni sey yapar)."""
    return await evaluate_outcomes(horizon=horizon, limit=limit)
