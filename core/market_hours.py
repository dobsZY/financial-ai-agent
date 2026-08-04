from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from schemas.market import Market


@dataclass(frozen=True)
class Session:
    timezone_name: str
    open_time: time
    close_time: time

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


SESSIONS: dict[Market, Session] = {
    Market.BIST: Session("Europe/Istanbul", time(10, 0), time(18, 0)),
    Market.NASDAQ: Session("America/New_York", time(9, 30), time(16, 0)),
}

# Sabit tarihli resmi tatiller (yila bagli degisenler haric)
_FIXED_HOLIDAYS: dict[Market, set[tuple[int, int]]] = {
    Market.BIST: {
        (1, 1),  # Yilbasi
        (4, 23),  # Ulusal Egemenlik
        (5, 1),  # Emek ve Dayanisma
        (5, 19),  # Ataturk'u Anma
        (7, 15),  # Demokrasi
        (8, 30),  # Zafer
        (10, 29),  # Cumhuriyet
    },
    Market.NASDAQ: {
        (1, 1),  # New Year
        (6, 19),  # Juneteenth
        (7, 4),  # Independence Day
        (12, 25),  # Christmas
    },
}


def _local_now(market: Market, moment: datetime | None = None) -> datetime:
    session = SESSIONS[market]
    reference = moment or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(session.zone)


def is_holiday(market: Market, day: date) -> bool:
    return (day.month, day.day) in _FIXED_HOLIDAYS.get(market, set())


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def is_trading_day(market: Market, moment: datetime | None = None) -> bool:
    local = _local_now(market, moment)
    return not is_weekend(local.date()) and not is_holiday(market, local.date())


def is_market_open(market: Market, moment: datetime | None = None) -> bool:
    """Seans ici mi? Hafta sonu ve sabit tatiller haric tutulur."""
    if not is_trading_day(market, moment):
        return False
    local = _local_now(market, moment)
    session = SESSIONS[market]
    return session.open_time <= local.time() <= session.close_time


def open_markets(moment: datetime | None = None) -> list[Market]:
    return [market for market in SESSIONS if is_market_open(market, moment)]


def market_of(ticker: str) -> Market:
    return Market.BIST if ticker.strip().upper().endswith(".IS") else Market.NASDAQ


def filter_open_tickers(tickers: list[str], moment: datetime | None = None) -> list[str]:
    """Yalnizca seansi acik piyasalara ait sembolleri dondurur."""
    active = set(open_markets(moment))
    return [ticker for ticker in tickers if market_of(ticker) in active]
