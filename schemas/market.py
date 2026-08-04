from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator

OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


class Market(StrEnum):
    BIST = "BIST"
    NASDAQ = "NASDAQ"


class Interval(StrEnum):
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"


INTERVAL_MINUTES: dict[Interval, int] = {
    Interval.M5: 5,
    Interval.M15: 15,
    Interval.M30: 30,
    Interval.H1: 60,
    Interval.D1: 1440,
}

DEFAULT_PERIOD: dict[Interval, str] = {
    Interval.M5: "5d",
    Interval.M15: "1mo",
    Interval.M30: "1mo",
    Interval.H1: "3mo",
    Interval.D1: "2y",
}


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("ts")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class SymbolConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    market: Market
    interval: Interval = Interval.H1
    is_active: bool = True

    @classmethod
    def from_ticker(cls, ticker: str, interval: Interval = Interval.H1) -> SymbolConfig:
        normalized = ticker.strip().upper()
        market = Market.BIST if normalized.endswith(".IS") else Market.NASDAQ
        return cls(ticker=normalized, market=market, interval=interval)

    @property
    def yf_ticker(self) -> str:
        if self.market is Market.BIST and not self.ticker.endswith(".IS"):
            return f"{self.ticker}.IS"
        return self.ticker

    @property
    def timezone_name(self) -> str:
        return "Europe/Istanbul" if self.market is Market.BIST else "America/New_York"


class SymbolRead(BaseModel):
    """API cikti sozlesmesi: izleme listesi kaydi."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    market: str
    name: str | None = None
    interval: str
    is_active: bool
    created_at: datetime


class SymbolCreate(BaseModel):
    ticker: str
    interval: Interval = Interval.H1
    name: str | None = None


class SymbolUpdate(BaseModel):
    is_active: bool | None = None
    interval: Interval | None = None
    name: str | None = None


class OHLCVFrame(BaseModel):
    """OHLCV zaman serisi. `df` UTC DatetimeIndex ve OHLCV_COLUMNS kolonlarina sahiptir."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    symbol: SymbolConfig
    df: pd.DataFrame

    @field_validator("df")
    @classmethod
    def _validate_df(cls, value: pd.DataFrame) -> pd.DataFrame:
        missing = [column for column in OHLCV_COLUMNS if column not in value.columns]
        if missing:
            raise ValueError(f"Eksik OHLCV kolonlari: {missing}")
        if not isinstance(value.index, pd.DatetimeIndex):
            raise ValueError("df.index bir DatetimeIndex olmalidir")
        if value.index.tz is None:
            raise ValueError("df.index tz-aware (UTC) olmalidir")
        return value

    @property
    def interval(self) -> Interval:
        return self.symbol.interval

    @property
    def is_empty(self) -> bool:
        return self.df.empty

    @property
    def last_timestamp(self) -> datetime | None:
        if self.df.empty:
            return None
        return self.df.index[-1].to_pydatetime()

    @property
    def latest_close(self) -> float | None:
        if self.df.empty:
            return None
        return float(self.df["close"].iloc[-1])

    def is_stale(self, max_age_multiplier: float = 3.0, now: datetime | None = None) -> bool:
        """Son mum, interval suresinin katindan daha eskiyse veri bayat sayilir (K-03)."""
        last = self.last_timestamp
        if last is None:
            return True
        reference = now or datetime.now(timezone.utc)
        max_age_minutes = INTERVAL_MINUTES[self.interval] * max_age_multiplier
        return (reference - last).total_seconds() / 60.0 > max_age_minutes

    def to_candles(self) -> list[Candle]:
        return [
            Candle(
                ts=index.to_pydatetime(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for index, row in self.df.iterrows()
        ]

    def tail(self, count: int) -> OHLCVFrame:
        return OHLCVFrame(symbol=self.symbol, df=self.df.tail(count))
