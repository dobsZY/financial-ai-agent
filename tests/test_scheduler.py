from __future__ import annotations

from datetime import time

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import scheduler as scheduler_module
from schemas.market import Interval, Market


@pytest.fixture
def scheduler() -> AsyncIOScheduler:
    instance = AsyncIOScheduler(timezone="UTC")
    scheduler_module.register_jobs(instance)
    return instance


def test_all_jobs_are_registered(scheduler: AsyncIOScheduler) -> None:
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        "intraday_scan_bist",
        "intraday_scan_nasdaq",
        "eod_scan_bist",
        "eod_scan_nasdaq",
        "news_poll",
        "outcome_scan",
    }


def test_jobs_use_market_timezones(scheduler: AsyncIOScheduler) -> None:
    bist = scheduler.get_job("intraday_scan_bist")
    nasdaq = scheduler.get_job("intraday_scan_nasdaq")

    assert str(bist.trigger.timezone) == "Europe/Istanbul"
    assert str(nasdaq.trigger.timezone) == "America/New_York"


def test_outcome_job_runs_hourly(scheduler: AsyncIOScheduler) -> None:
    """Sonuc degerlendirmesi piyasadan bagimsiz, saatlik calisir."""
    trigger = str(scheduler.get_job("outcome_scan").trigger)
    assert "1:00:00" in trigger


def test_weekend_is_excluded_from_cron(scheduler: AsyncIOScheduler) -> None:
    trigger = str(scheduler.get_job("eod_scan_nasdaq").trigger)
    assert "day_of_week='mon-fri'" in trigger


def test_eod_time_handles_hour_overflow() -> None:
    assert scheduler_module._eod_time(time(16, 0)) == time(16, 15)
    assert scheduler_module._eod_time(time(17, 50)) == time(18, 5)


async def test_intraday_scan_skips_closed_market(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    async def fake_tracked_scan(job_name: str, **kwargs: object) -> None:
        called.append(job_name)

    monkeypatch.setattr(scheduler_module, "is_market_open", lambda market: False)
    monkeypatch.setattr(scheduler_module, "run_tracked_scan", fake_tracked_scan)

    await scheduler_module.intraday_scan(Market.BIST)

    assert called == []


async def test_intraday_scan_runs_when_open(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_tracked_scan(job_name: str, **kwargs: object) -> None:
        captured["job_name"] = job_name
        captured.update(kwargs)

    monkeypatch.setattr(scheduler_module, "is_market_open", lambda market: True)
    monkeypatch.setattr(scheduler_module, "_market_tickers", lambda market: ["AAPL"])
    monkeypatch.setattr(scheduler_module, "run_tracked_scan", fake_tracked_scan)

    await scheduler_module.intraday_scan(Market.NASDAQ)

    assert captured["job_name"] == "intraday_scan_nasdaq"
    assert captured["tickers"] == ["AAPL"]


async def test_eod_scan_uses_daily_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_tracked_scan(job_name: str, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(scheduler_module, "is_trading_day", lambda market: True)
    monkeypatch.setattr(scheduler_module, "_market_tickers", lambda market: ["THYAO.IS"])
    monkeypatch.setattr(scheduler_module, "run_tracked_scan", fake_tracked_scan)

    await scheduler_module.eod_scan(Market.BIST)

    assert captured["interval"] is Interval.D1


async def test_news_poll_skips_when_no_trading_day(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    async def fake_poll() -> None:
        called.append(True)

    monkeypatch.setattr(scheduler_module, "is_trading_day", lambda market: False)
    monkeypatch.setattr(scheduler_module, "run_tracked_news_poll", fake_poll)

    await scheduler_module.news_poll()

    assert called == []
