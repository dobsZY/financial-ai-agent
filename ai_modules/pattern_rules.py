from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ai_modules.base import PatternAnalyzer, deduplicate, register_analyzer
from core.logger import get_logger
from schemas.market import OHLCVFrame
from schemas.signal import Detection, Pattern

logger = get_logger(__name__)

PIVOT_WINDOW = 5
LOOKBACK = 120
RECENCY_BARS = 20
LEVEL_TOLERANCE = 0.03
FLAT_TOLERANCE = 0.02
MIN_DEPTH = 0.03
SOURCE = "rules"

PivotKind = Literal["peak", "trough"]


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    kind: PivotKind


def find_pivots(
    highs: np.ndarray,
    lows: np.ndarray,
    window: int = PIVOT_WINDOW,
) -> list[Pivot]:
    """Yerel tepe/dip noktalarini bulur (her iki yanda `window` mum karsilastirmasi)."""
    pivots: list[Pivot] = []
    count = len(highs)
    for i in range(window, count - window):
        window_slice = slice(i - window, i + window + 1)
        if highs[i] >= highs[window_slice].max():
            pivots.append(Pivot(index=i, price=float(highs[i]), kind="peak"))
        elif lows[i] <= lows[window_slice].min():
            pivots.append(Pivot(index=i, price=float(lows[i]), kind="trough"))
    return pivots


def _relative_diff(first: float, second: float) -> float:
    reference = max(abs(first), abs(second), 1e-9)
    return abs(first - second) / reference


def _clamp_confidence(value: float) -> float:
    return round(float(min(0.92, max(0.0, value))), 4)


def _level_confidence(similarity_error: float, depth: float) -> float:
    """Seviyeler ne kadar esit ve formasyon ne kadar derinse guven artar."""
    symmetry = 1.0 - min(similarity_error / LEVEL_TOLERANCE, 1.0)
    depth_score = min(depth / (MIN_DEPTH * 3.0), 1.0)
    return _clamp_confidence(0.55 + 0.22 * symmetry + 0.15 * depth_score)


def _is_recent(pivot_index: int, last_index: int, recency: int) -> bool:
    return last_index - pivot_index <= recency


def _double_pattern(
    pivots: list[Pivot],
    kind: PivotKind,
    closes: np.ndarray,
    lows: np.ndarray,
    highs: np.ndarray,
    recency: int,
) -> Detection | None:
    extremes = [pivot for pivot in pivots if pivot.kind == kind]
    if len(extremes) < 2:
        return None

    first, second = extremes[-2], extremes[-1]
    last_index = len(closes) - 1
    if not _is_recent(second.index, last_index, recency):
        return None

    error = _relative_diff(first.price, second.price)
    if error > LEVEL_TOLERANCE:
        return None

    between = slice(first.index, second.index + 1)
    if second.index - first.index < 3:
        return None

    if kind == "peak":
        neckline = float(lows[between].min())
        depth = (min(first.price, second.price) - neckline) / max(neckline, 1e-9)
        breakout = closes[-1] < second.price
        pattern = Pattern.DOUBLE_TOP
    else:
        neckline = float(highs[between].max())
        depth = (neckline - max(first.price, second.price)) / max(neckline, 1e-9)
        breakout = closes[-1] > second.price
        pattern = Pattern.DOUBLE_BOTTOM

    if depth < MIN_DEPTH or not breakout:
        return None

    return Detection(
        pattern=pattern,
        confidence=_level_confidence(error, depth),
        source=SOURCE,
        breakout_level=round(neckline, 4),
        meta={
            "level_error": round(error, 4),
            "depth": round(depth, 4),
            "neckline": round(neckline, 4),
            "bars_between": second.index - first.index,
        },
    )


def _head_shoulders(
    pivots: list[Pivot],
    kind: PivotKind,
    closes: np.ndarray,
    lows: np.ndarray,
    highs: np.ndarray,
    recency: int,
) -> Detection | None:
    extremes = [pivot for pivot in pivots if pivot.kind == kind]
    if len(extremes) < 3:
        return None

    left, head, right = extremes[-3], extremes[-2], extremes[-1]
    if not _is_recent(right.index, len(closes) - 1, recency):
        return None

    shoulder_error = _relative_diff(left.price, right.price)
    if shoulder_error > LEVEL_TOLERANCE:
        return None

    if kind == "peak":
        if not (head.price > left.price and head.price > right.price):
            return None
        prominence = (head.price - max(left.price, right.price)) / max(head.price, 1e-9)
        pattern = Pattern.HEAD_SHOULDERS
        # Boyun cizgisi: omuzlar arasindaki en dusuk dip
        neckline = float(lows[left.index : right.index + 1].min())
    else:
        if not (head.price < left.price and head.price < right.price):
            return None
        prominence = (min(left.price, right.price) - head.price) / max(
            min(left.price, right.price), 1e-9
        )
        pattern = Pattern.INV_HEAD_SHOULDERS
        neckline = float(highs[left.index : right.index + 1].max())

    if prominence < MIN_DEPTH / 2.0:
        return None

    return Detection(
        pattern=pattern,
        confidence=_level_confidence(shoulder_error, prominence),
        source=SOURCE,
        breakout_level=round(neckline, 4),
        meta={
            "neckline": round(neckline, 4),
            "shoulder_error": round(shoulder_error, 4),
            "prominence": round(prominence, 4),
            "head_price": round(head.price, 4),
        },
    )


def _triangle(pivots: list[Pivot], closes: np.ndarray, recency: int) -> Detection | None:
    peaks = [pivot for pivot in pivots if pivot.kind == "peak"]
    troughs = [pivot for pivot in pivots if pivot.kind == "trough"]
    if len(peaks) < 2 or len(troughs) < 2:
        return None

    last_index = len(closes) - 1
    newest = max(peaks[-1].index, troughs[-1].index)
    if not _is_recent(newest, last_index, recency):
        return None

    peak_error = _relative_diff(peaks[-2].price, peaks[-1].price)
    trough_error = _relative_diff(troughs[-2].price, troughs[-1].price)
    rising_lows = troughs[-1].price > troughs[-2].price * (1.0 + FLAT_TOLERANCE / 2.0)
    falling_highs = peaks[-1].price < peaks[-2].price * (1.0 - FLAT_TOLERANCE / 2.0)

    if peak_error <= FLAT_TOLERANCE and rising_lows:
        slope = (troughs[-1].price - troughs[-2].price) / max(troughs[-2].price, 1e-9)
        resistance = (peaks[-2].price + peaks[-1].price) / 2.0
        return Detection(
            pattern=Pattern.ASC_TRIANGLE,
            confidence=_level_confidence(peak_error, slope),
            source=SOURCE,
            breakout_level=round(resistance, 4),
            meta={
                "resistance": round(resistance, 4),
                "resistance_error": round(peak_error, 4),
                "support_slope": round(slope, 4),
            },
        )

    if trough_error <= FLAT_TOLERANCE and falling_highs:
        slope = (peaks[-2].price - peaks[-1].price) / max(peaks[-2].price, 1e-9)
        support = (troughs[-2].price + troughs[-1].price) / 2.0
        return Detection(
            pattern=Pattern.DESC_TRIANGLE,
            confidence=_level_confidence(trough_error, slope),
            source=SOURCE,
            breakout_level=round(support, 4),
            meta={
                "support": round(support, 4),
                "support_error": round(trough_error, 4),
                "resistance_slope": round(slope, 4),
            },
        )

    return None


def detect_patterns(
    df: pd.DataFrame,
    lookback: int = LOOKBACK,
    pivot_window: int = PIVOT_WINDOW,
    recency: int = RECENCY_BARS,
) -> list[Detection]:
    """Kural tabanli formasyon tespiti. Deterministik ve modelden bagimsizdir."""
    window = df.tail(lookback)
    if len(window) < pivot_window * 4:
        return []

    highs = window["high"].to_numpy(dtype="float64")
    lows = window["low"].to_numpy(dtype="float64")
    closes = window["close"].to_numpy(dtype="float64")

    pivots = find_pivots(highs, lows, pivot_window)
    if not pivots:
        return []

    candidates = [
        _double_pattern(pivots, "peak", closes, lows, highs, recency),
        _double_pattern(pivots, "trough", closes, lows, highs, recency),
        _head_shoulders(pivots, "peak", closes, lows, highs, recency),
        _head_shoulders(pivots, "trough", closes, lows, highs, recency),
        _triangle(pivots, closes, recency),
    ]
    return deduplicate([item for item in candidates if item is not None])


@register_analyzer
class RuleBasedAnalyzer(PatternAnalyzer):
    """YOLO fine-tune edilene kadar birincil analizci (risk kaydi azaltmasi)."""

    name = "rules"

    async def analyze(self, frame: OHLCVFrame) -> list[Detection]:
        detections = detect_patterns(frame.df)
        if detections:
            logger.info(
                "rules.detected",
                ticker=frame.symbol.yf_ticker,
                patterns=[item.pattern.value for item in detections],
            )
        return detections
