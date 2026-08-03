from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv_df(rows: int = 200, seed: int = 7) -> pd.DataFrame:
    """Deterministik sentetik OHLCV serisi (UTC DatetimeIndex)."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC", name="ts")
    close = 100.0 + np.cumsum(rng.normal(0, 1, rows))
    open_ = close + rng.normal(0, 0.3, rows)
    high = np.maximum(open_, close) + rng.random(rows)
    low = np.minimum(open_, close) - rng.random(rows)
    volume = rng.integers(1_000, 10_000, rows).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
