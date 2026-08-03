from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.logger import get_logger

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Faz 3'te doldurulacak: intraday_scan, eod_scan, news_poll."""
    logger.info("scheduler.jobs_registered", count=len(scheduler.get_jobs()))


def start_scheduler() -> AsyncIOScheduler:
    scheduler = get_scheduler()
    if not scheduler.running:
        register_jobs(scheduler)
        scheduler.start()
        logger.info("scheduler.started")
    return scheduler


def shutdown_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler.stopped")
