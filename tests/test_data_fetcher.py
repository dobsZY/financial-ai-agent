from __future__ import annotations

import pandas as pd
import pytest

from core import data_fetcher
from core.data_fetcher import DataFetchError, fetch_many, fetch_ohlcv
from schemas.market import Interval, Market, SymbolConfig
from helpers import make_ohlcv_df


def _yfinance_style_df(ticker: str = "AAPL") -> pd.DataFrame:
    df = make_ohlcv_df(rows=60)
    df = df.rename(columns=str.capitalize)
    df.index = df.index.tz_convert("America/New_York")
    df.columns = pd.MultiIndex.from_product([df.columns, [ticker]])
    return df


def test_symbol_config_infers_market() -> None:
    bist = SymbolConfig.from_ticker("thyao.is")
    nasdaq = SymbolConfig.from_ticker("aapl")

    assert bist.market is Market.BIST
    assert bist.yf_ticker == "THYAO.IS"
    assert bist.timezone_name == "Europe/Istanbul"
    assert nasdaq.market is Market.NASDAQ
    assert nasdaq.yf_ticker == "AAPL"


async def test_fetch_ohlcv_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        data_fetcher.yf, "download", lambda **_: _yfinance_style_df(), raising=True
    )

    frame = await fetch_ohlcv(SymbolConfig.from_ticker("AAPL", interval=Interval.H1))

    assert list(frame.df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(frame.df.index.tz) == "UTC"
    assert frame.df.index.is_monotonic_increasing
    assert frame.latest_close is not None


async def test_fetch_ohlcv_raises_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_fetcher.yf, "download", lambda **_: pd.DataFrame(), raising=True)

    with pytest.raises(DataFetchError):
        await fetch_ohlcv(SymbolConfig.from_ticker("AAPL"))


async def test_fetch_many_isolates_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(**kwargs: object) -> pd.DataFrame:
        if kwargs["tickers"] == "THYAO.IS":
            raise RuntimeError("BIST verisi gecikmeli")
        return _yfinance_style_df()

    monkeypatch.setattr(data_fetcher.yf, "download", fake_download, raising=True)

    frames = await fetch_many(
        [SymbolConfig.from_ticker("AAPL"), SymbolConfig.from_ticker("THYAO.IS")]
    )

    assert set(frames) == {"AAPL"}


def test_watchlist_from_settings() -> None:
    watchlist = data_fetcher.watchlist_from_settings()

    assert {item.yf_ticker for item in watchlist} == {"THYAO.IS", "AAPL"}
