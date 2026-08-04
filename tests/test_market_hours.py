from __future__ import annotations

from datetime import datetime, timezone

from core import market_hours
from schemas.market import Market


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_bist_open_during_session() -> None:
    # 2026-08-04 Sali, 12:00 Istanbul = 09:00 UTC
    assert market_hours.is_market_open(Market.BIST, _utc(2026, 8, 4, 9))


def test_bist_closed_after_session() -> None:
    # 21:00 Istanbul = 18:00 UTC
    assert not market_hours.is_market_open(Market.BIST, _utc(2026, 8, 4, 18))


def test_nasdaq_open_during_session() -> None:
    # 11:00 New York = 15:00 UTC
    assert market_hours.is_market_open(Market.NASDAQ, _utc(2026, 8, 4, 15))


def test_weekend_is_not_trading_day() -> None:
    saturday = _utc(2026, 8, 8, 12)
    assert not market_hours.is_trading_day(Market.BIST, saturday)
    assert not market_hours.is_market_open(Market.NASDAQ, saturday)


def test_fixed_holiday_is_skipped() -> None:
    # 29 Ekim 2026 Persembe, 13:00 UTC: BIST tatil (16:00 Istanbul), NASDAQ acik (09:00 New York)
    moment = _utc(2026, 10, 29, 13, 30)
    assert not market_hours.is_market_open(Market.BIST, moment)
    assert market_hours.is_market_open(Market.NASDAQ, moment)


def test_market_of_uses_is_suffix() -> None:
    assert market_hours.market_of("thyao.is") is Market.BIST
    assert market_hours.market_of("AAPL") is Market.NASDAQ


def test_filter_open_tickers() -> None:
    # 09:00 UTC: BIST acik (12:00 Istanbul), NASDAQ kapali (05:00 New York)
    tickers = market_hours.filter_open_tickers(["THYAO.IS", "AAPL"], _utc(2026, 8, 4, 9))
    assert tickers == ["THYAO.IS"]


def test_open_markets_empty_at_night() -> None:
    assert market_hours.open_markets(_utc(2026, 8, 4, 2)) == []
