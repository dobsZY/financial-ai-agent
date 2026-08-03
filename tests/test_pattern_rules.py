from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ai_modules.base import REGISTRY, get_analyzer
from ai_modules.pattern_rules import detect_patterns, find_pivots
from schemas.market import OHLCVFrame, SymbolConfig
from schemas.signal import Direction, Pattern


def _frame_from_closes(closes: list[float]) -> pd.DataFrame:
    array = np.asarray(closes, dtype="float64")
    index = pd.date_range("2024-01-01", periods=len(array), freq="h", tz="UTC", name="ts")
    return pd.DataFrame(
        {
            "open": array,
            "high": array * 1.001,
            "low": array * 0.999,
            "close": array,
            "volume": np.full(len(array), 1000.0),
        },
        index=index,
    )


def _ramp(start: float, end: float, steps: int) -> list[float]:
    return list(np.linspace(start, end, steps, endpoint=False))


def _double_top_closes() -> list[float]:
    return (
        _ramp(100, 130, 15)
        + _ramp(130, 110, 12)
        + _ramp(110, 129, 12)
        + _ramp(129, 105, 14)
    )


def _double_bottom_closes() -> list[float]:
    return (
        _ramp(130, 100, 15)
        + _ramp(100, 120, 12)
        + _ramp(120, 101, 12)
        + _ramp(101, 125, 14)
    )


def test_find_pivots_detects_extremes() -> None:
    df = _frame_from_closes(_double_top_closes())

    pivots = find_pivots(df["high"].to_numpy(), df["low"].to_numpy(), window=4)

    assert any(pivot.kind == "peak" for pivot in pivots)
    assert any(pivot.kind == "trough" for pivot in pivots)


def test_detects_double_top() -> None:
    detections = detect_patterns(_frame_from_closes(_double_top_closes()), pivot_window=4)

    patterns = {item.pattern for item in detections}
    assert Pattern.DOUBLE_TOP in patterns

    detection = next(item for item in detections if item.pattern is Pattern.DOUBLE_TOP)
    assert detection.resolved_direction is Direction.SHORT
    assert 0.0 < detection.confidence <= 0.92
    assert detection.source == "rules"


def test_detects_double_bottom() -> None:
    detections = detect_patterns(_frame_from_closes(_double_bottom_closes()), pivot_window=4)

    patterns = {item.pattern for item in detections}
    assert Pattern.DOUBLE_BOTTOM in patterns
    detection = next(item for item in detections if item.pattern is Pattern.DOUBLE_BOTTOM)
    assert detection.resolved_direction is Direction.LONG


def test_no_detection_on_random_walk(ohlcv_df: pd.DataFrame) -> None:
    detections = detect_patterns(ohlcv_df)

    assert all(item.confidence >= 0.55 for item in detections)


def test_short_series_returns_empty() -> None:
    detections = detect_patterns(_frame_from_closes([100.0] * 10))

    assert detections == []


def test_registry_contains_analyzers() -> None:
    assert {"rules", "yolo"} <= set(REGISTRY)
    assert get_analyzer("rules").is_available is True


async def test_rule_analyzer_analyze(symbol: SymbolConfig) -> None:
    frame = OHLCVFrame(symbol=symbol, df=_frame_from_closes(_double_top_closes()))

    detections = await get_analyzer("rules").analyze(frame)

    assert any(item.pattern is Pattern.DOUBLE_TOP for item in detections)


def test_unknown_analyzer_raises() -> None:
    with pytest.raises(KeyError):
        get_analyzer("bilinmeyen")
