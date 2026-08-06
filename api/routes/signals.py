from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from core.logger import get_logger
from core.pipeline import run_tracked_news_poll, run_tracked_scan
from database import db_manager
from database.models import Signal
from schemas.market import Interval
from schemas.signal import JobRunRead, SignalRead

logger = get_logger(__name__)

router = APIRouter(tags=["signals"])


class ScanRequest(BaseModel):
    """Manuel tarama istegi (3.9)."""

    tickers: list[str] | None = None
    interval: Interval | None = None
    only_open_markets: bool = False
    send_notification: bool = True
    background: bool = Field(
        default=False, description="True ise tarama arka planda calisir, yanit hemen doner."
    )


def _to_read(signal: Signal, ticker: str) -> SignalRead:
    return SignalRead(
        id=signal.id,
        ticker=ticker,
        pattern=signal.pattern,
        direction=signal.direction,
        confidence=signal.confidence,
        final_score=signal.final_score,
        price_at_signal=signal.price_at_signal,
        bucket_ts=signal.bucket_ts,
        created_at=signal.created_at,
        notified_at=signal.notified_at,
    )


@router.get("/signals", response_model=list[SignalRead])
async def list_signals(
    limit: int = Query(default=50, ge=1, le=500),
    ticker: str | None = None,
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
) -> list[SignalRead]:
    rows = await db_manager.list_signals(limit=limit, ticker=ticker, min_score=min_score)
    return [_to_read(signal, symbol_ticker) for signal, symbol_ticker in rows]


@router.get("/signals/{signal_id}", response_model=SignalRead)
async def get_signal(signal_id: int) -> SignalRead:
    row = await db_manager.get_signal(signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sinyal bulunamadı")
    return _to_read(row[0], row[1])


@router.post("/scan")
async def trigger_scan(request: ScanRequest, tasks: BackgroundTasks) -> dict[str, object]:
    """Zamanlayiciyi beklemeden tarama tetikler (3.9)."""
    kwargs: dict[str, object] = {
        "tickers": request.tickers,
        "interval": request.interval,
        "only_open_markets": request.only_open_markets,
        "send_notification": request.send_notification,
    }
    if request.background:
        tasks.add_task(run_tracked_scan, "manual_scan", **kwargs)
        logger.info("api.scan_queued", tickers=request.tickers)
        return {"status": "queued"}

    result = await run_tracked_scan("manual_scan", **kwargs)
    return {"status": "completed", **result.summary}


@router.post("/news/poll")
async def trigger_news_poll(tasks: BackgroundTasks, background: bool = False) -> dict[str, object]:
    """KAP/SEC yoklamasini manuel tetikler (3.9)."""
    if background:
        tasks.add_task(run_tracked_news_poll, "manual_news_poll")
        return {"status": "queued"}
    return {"status": "completed", **await run_tracked_news_poll("manual_news_poll")}


@router.get("/jobs", response_model=list[JobRunRead])
async def list_job_runs(
    limit: int = Query(default=20, ge=1, le=200),
    job_name: str | None = None,
) -> list[JobRunRead]:
    """Son is calistirmalari — sistem sagligi gorunumu icin (3.8)."""
    runs = await db_manager.list_job_runs(limit=limit, job_name=job_name)
    return [JobRunRead.model_validate(run) for run in runs]
