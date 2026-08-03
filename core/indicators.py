from __future__ import annotations

import numpy as np
import pandas as pd

RSI_PERIOD = 14
EMA_SPANS: tuple[int, ...] = (20, 50, 200)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
VOLUME_WINDOW = 20


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))
    return result.where(avg_loss != 0.0, 100.0).rename("rsi")


def macd(
    series: pd.Series,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    return pd.DataFrame(
        {
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": macd_line - signal_line,
        }
    )


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame'e indikator kolonlarini ekleyip yeni bir kopya dondurur."""
    enriched = df.copy()
    close = enriched["close"]

    enriched["rsi"] = rsi(close)
    for span in EMA_SPANS:
        enriched[f"ema_{span}"] = ema(close, span)
    enriched = enriched.join(macd(close))
    enriched["volume_sma"] = enriched["volume"].rolling(VOLUME_WINDOW, min_periods=1).mean()
    enriched["volume_ratio"] = enriched["volume"] / enriched["volume_sma"].replace(0.0, np.nan)
    return enriched


def _last_value(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns or df.empty:
        return None
    value = df[column].iloc[-1]
    return None if pd.isna(value) else float(value)


def indicator_snapshot(df: pd.DataFrame) -> dict[str, float | None]:
    """Son mumun indikator ozeti; Faz 3 skorlamasinda kullanilir."""
    enriched = compute_all(df)
    snapshot: dict[str, float | None] = {
        "close": _last_value(enriched, "close"),
        "rsi": _last_value(enriched, "rsi"),
        "macd_hist": _last_value(enriched, "macd_hist"),
        "volume_ratio": _last_value(enriched, "volume_ratio"),
    }
    for span in EMA_SPANS:
        snapshot[f"ema_{span}"] = _last_value(enriched, f"ema_{span}")
    return snapshot


def trend_confirmation(df: pd.DataFrame) -> float:
    """-1.0 (dusus) .. +1.0 (yukselis) araliginda indikator teyit skoru."""
    snapshot = indicator_snapshot(df)
    close = snapshot["close"]
    if close is None:
        return 0.0

    score = 0.0
    weight_total = 0.0

    ema_50 = snapshot.get("ema_50")
    if ema_50 is not None:
        score += 1.0 if close > ema_50 else -1.0
        weight_total += 1.0

    rsi_value = snapshot.get("rsi")
    if rsi_value is not None:
        if rsi_value >= 70.0:
            score -= 0.5
        elif rsi_value <= 30.0:
            score += 0.5
        else:
            score += (rsi_value - 50.0) / 50.0
        weight_total += 1.0

    macd_hist = snapshot.get("macd_hist")
    if macd_hist is not None:
        score += 1.0 if macd_hist > 0 else -1.0
        weight_total += 1.0

    if weight_total == 0.0:
        return 0.0
    return round(max(-1.0, min(1.0, score / weight_total)), 4)
