from __future__ import annotations

import asyncio
from typing import Iterable

import pandas as pd
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import get_settings
from core.logger import get_logger
from schemas.market import (
    DEFAULT_PERIOD,
    OHLCV_COLUMNS,
    Interval,
    OHLCVFrame,
    SymbolConfig,
)

logger = get_logger(__name__)


class DataFetchError(RuntimeError):
    """yfinance'ten veri alinamadiginda firlatilir."""


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = _flatten_columns(df)
    df = df.rename(columns={str(column): str(column).strip().lower() for column in df.columns})
    df = df.loc[:, ~df.columns.duplicated()]

    missing = [column for column in OHLCV_COLUMNS if column not in df.columns]
    if missing:
        raise DataFetchError(f"Beklenen kolonlar eksik: {missing}")

    df = df[list(OHLCV_COLUMNS)].astype("float64")

    index = pd.DatetimeIndex(df.index)
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    df.index = index
    df.index.name = "ts"

    df = df.dropna(how="any")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _download(ticker: str, interval: Interval, period: str) -> pd.DataFrame:
    """Bloklayan yfinance cagrisi. Sadece to_thread icinden cagrilmalidir (K-01)."""
    return yf.download(
        tickers=ticker,
        period=period,
        interval=interval.value,
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
    )


@retry(
    retry=retry_if_exception_type((DataFetchError, ConnectionError, TimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def fetch_ohlcv(
    symbol: SymbolConfig,
    period: str | None = None,
) -> OHLCVFrame:
    """Tek sembol icin OHLCV verisini asenkron ceker."""
    interval = symbol.interval
    resolved_period = period or DEFAULT_PERIOD[interval]

    try:
        raw = await asyncio.to_thread(_download, symbol.yf_ticker, interval, resolved_period)
    except Exception as exc:  # noqa: BLE001 - dis kutuphane her turlu hatayi atabilir
        raise DataFetchError(f"{symbol.yf_ticker} indirilemedi: {exc}") from exc

    if raw is None or raw.empty:
        raise DataFetchError(f"{symbol.yf_ticker} icin bos veri dondu")

    df = _normalize(raw)
    if df.empty:
        raise DataFetchError(f"{symbol.yf_ticker} normalizasyon sonrasi bos")

    frame = OHLCVFrame(symbol=symbol, df=df)
    logger.info(
        "data.fetched",
        ticker=symbol.yf_ticker,
        interval=interval.value,
        rows=len(df),
        last_ts=frame.last_timestamp.isoformat() if frame.last_timestamp else None,
    )
    return frame


async def fetch_many(
    symbols: Iterable[SymbolConfig],
    period: str | None = None,
    concurrency: int | None = None,
) -> dict[str, OHLCVFrame]:
    """Coklu sembol cekimi. Bir sembolun hatasi digerlerini dusurmez (K-03)."""
    symbol_list = list(symbols)
    if not symbol_list:
        return {}

    limit = concurrency or get_settings().scan_concurrency
    semaphore = asyncio.Semaphore(limit)

    async def _guarded(symbol: SymbolConfig) -> OHLCVFrame:
        async with semaphore:
            return await fetch_ohlcv(symbol, period=period)

    results = await asyncio.gather(
        *(_guarded(symbol) for symbol in symbol_list),
        return_exceptions=True,
    )

    frames: dict[str, OHLCVFrame] = {}
    for symbol, result in zip(symbol_list, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("data.fetch_failed", ticker=symbol.yf_ticker, error=str(result))
            continue
        frames[symbol.yf_ticker] = result

    logger.info("data.fetch_batch", requested=len(symbol_list), succeeded=len(frames))
    return frames


def watchlist_from_settings() -> list[SymbolConfig]:
    settings = get_settings()
    interval = Interval(settings.intraday_interval)
    return [
        SymbolConfig.from_ticker(ticker, interval=interval) for ticker in settings.all_symbols
    ]
