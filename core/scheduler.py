from __future__ import annotations

from datetime import date, datetime, time, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import get_settings
from core.logger import get_logger
from core.market_hours import SESSIONS, is_market_open, is_trading_day
from database import db_manager
from core.pipeline import evaluate_outcomes, run_tracked_news_poll, run_tracked_scan
from schemas.market import Interval, Market

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Seans ici tarama pencereleri: (baslangic saati, bitis saati) yerel saat.
# Kapanis saatinin bir onceki tam saatinde son tarama yapilir.
_INTRADAY_HOURS: dict[Market, str] = {
    Market.BIST: "10-17",
    Market.NASDAQ: "10-15",
}

# Kapanistan sonra gunluk mumun oturmasi icin beklenen dakika.
_EOD_DELAY_MINUTES = 15


def _eod_time(close_time: time) -> time:
    """Kapanis + gecikme; saat tasmasini dogru hesaplar."""
    reference = datetime.combine(date(2000, 1, 1), close_time)
    return (reference + timedelta(minutes=_EOD_DELAY_MINUTES)).time()


def _market_tickers(market: Market) -> list[str]:
    settings = get_settings()
    return settings.bist_tickers if market is Market.BIST else settings.nasdaq_tickers


async def intraday_scan(market: Market) -> None:
    """Seans ici saatlik tarama (3.7). Tatil/kapali seansta atlanir."""
    job_name = f"intraday_scan_{market.value.lower()}"
    if not is_market_open(market):
        logger.info("scheduler.job_skipped", job=job_name, reason="market_closed")
        return

    tickers = _market_tickers(market)
    if not tickers:
        logger.info("scheduler.job_skipped", job=job_name, reason="empty_watchlist")
        return

    await run_tracked_scan(
        job_name=job_name,
        tickers=tickers,
        interval=Interval(get_settings().intraday_interval),
    )


async def eod_scan(market: Market) -> None:
    """Kapanis sonrasi gunluk mumla tarama (3.7)."""
    job_name = f"eod_scan_{market.value.lower()}"
    if not is_trading_day(market):
        logger.info("scheduler.job_skipped", job=job_name, reason="not_trading_day")
        return

    tickers = _market_tickers(market)
    if not tickers:
        logger.info("scheduler.job_skipped", job=job_name, reason="empty_watchlist")
        return

    await run_tracked_scan(job_name=job_name, tickers=tickers, interval=Interval.D1)


async def news_poll() -> None:
    """KAP/SEC bildirim yoklamasi (3.7). Her iki piyasa da kapaliysa atlanir."""
    if not any(is_trading_day(market) for market in SESSIONS):
        logger.info("scheduler.job_skipped", job="news_poll", reason="no_trading_day")
        return
    await run_tracked_news_poll()


async def outcome_scan() -> None:
    """Bekleyen sinyalleri N mum sonrasina tasiyip sonucunu kaydeder (3.8 + 6.2)."""
    job_id = await db_manager.start_job_run("outcome_scan")
    try:
        stats = await evaluate_outcomes()
    except Exception as exc:  # noqa: BLE001 - zamanlayici dusmez
        logger.error("scheduler.outcome_failed", error=str(exc))
        await db_manager.finish_job_run(job_id, status="error", error_text=str(exc)[:1000])
        return
    await db_manager.finish_job_run(
        job_id, status="success", items_processed=stats["evaluated"]
    )


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
        )
    return _scheduler


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """intraday_scan (saatlik), eod_scan (kapanis), news_poll (15 dk) — 3.7."""
    settings = get_settings()

    for market, session in SESSIONS.items():
        suffix = market.value.lower()
        scheduler.add_job(
            intraday_scan,
            CronTrigger(
                day_of_week="mon-fri",
                hour=_INTRADAY_HOURS[market],
                minute=5,
                timezone=session.zone,
            ),
            args=[market],
            id=f"intraday_scan_{suffix}",
            name=f"Seans ici tarama ({market.value})",
            replace_existing=True,
        )
        eod_at = _eod_time(session.close_time)
        scheduler.add_job(
            eod_scan,
            CronTrigger(
                day_of_week="mon-fri",
                hour=eod_at.hour,
                minute=eod_at.minute,
                timezone=session.zone,
            ),
            args=[market],
            id=f"eod_scan_{suffix}",
            name=f"Kapanis taramasi ({market.value})",
            replace_existing=True,
        )

    scheduler.add_job(
        outcome_scan,
        IntervalTrigger(hours=1),
        id="outcome_scan",
        name="Sinyal sonuclarini degerlendir",
        replace_existing=True,
    )

    scheduler.add_job(
        news_poll,
        IntervalTrigger(minutes=settings.news_poll_interval_minutes),
        id="news_poll",
        name="KAP/SEC bildirim yoklamasi",
        replace_existing=True,
    )

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
