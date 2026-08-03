from __future__ import annotations

import numpy as np
import pandas as pd

from core.indicators import compute_all, indicator_snapshot, rsi, trend_confirmation
from helpers import make_ohlcv_df


def test_rsi_stays_in_bounds(ohlcv_df: pd.DataFrame) -> None:
    values = rsi(ohlcv_df["close"]).dropna()

    assert not values.empty
    assert values.between(0.0, 100.0).all()


def test_compute_all_adds_expected_columns(ohlcv_df: pd.DataFrame) -> None:
    enriched = compute_all(ohlcv_df)

    for column in ("rsi", "ema_20", "ema_50", "ema_200", "macd", "macd_signal", "macd_hist"):
        assert column in enriched.columns
    assert len(enriched) == len(ohlcv_df)
    assert list(ohlcv_df.columns) == ["open", "high", "low", "close", "volume"]


def test_indicator_snapshot_returns_last_values(ohlcv_df: pd.DataFrame) -> None:
    snapshot = indicator_snapshot(ohlcv_df)

    assert snapshot["close"] == float(ohlcv_df["close"].iloc[-1])
    assert snapshot["rsi"] is not None


def test_trend_confirmation_sign_follows_trend() -> None:
    index = pd.date_range("2024-01-01", periods=250, freq="h", tz="UTC")
    rising = pd.Series(np.linspace(100, 200, 250), index=index)
    falling = pd.Series(np.linspace(200, 100, 250), index=index)

    up_df = make_ohlcv_df(rows=250).assign(close=rising.to_numpy())
    down_df = make_ohlcv_df(rows=250).assign(close=falling.to_numpy())

    assert trend_confirmation(up_df) > 0
    assert trend_confirmation(down_df) < 0
