"""Kaydedilmis sinyal sonuclarindan isabet istatistikleri (Faz 6.2).

`core/backtest.py` gecmise donuk tek seferlik rapor uretir; bu modul ise
`signal_outcomes` tablosuna surekli yazilan sonuclari ozetler ve panele besler.
"""

from __future__ import annotations

from statistics import mean, median
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict

from core.pattern_glossary import get_info_safe

SCORE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<0.60", 0.0, 0.60),
    ("0.60-0.75", 0.60, 0.75),
    (">=0.75", 0.75, 1.01),
)


class GroupStat(BaseModel):
    """Bir kirilim grubunun ozeti (formasyon, skor araligi, yön…)."""

    model_config = ConfigDict(frozen=True)

    label: str
    count: int
    hit_rate: float
    avg_return_pct: float


class StatsReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluated: int = 0
    hit_rate: float = 0.0
    avg_return_pct: float = 0.0
    median_return_pct: float = 0.0
    horizon: int | None = None
    by_pattern: list[GroupStat] = []
    by_score: list[GroupStat] = []
    by_direction: list[GroupStat] = []
    by_confirmation: list[GroupStat] = []


def _group(label: str, returns: list[float]) -> GroupStat:
    return GroupStat(
        label=label,
        count=len(returns),
        hit_rate=round(sum(1 for value in returns if value > 0) / len(returns), 4),
        avg_return_pct=round(mean(returns), 3),
    )


def _grouped(pairs: Iterable[tuple[str, float]]) -> list[GroupStat]:
    buckets: dict[str, list[float]] = {}
    for label, value in pairs:
        buckets.setdefault(label, []).append(value)
    return sorted(
        (_group(label, values) for label, values in buckets.items()),
        key=lambda item: item.count,
        reverse=True,
    )


def build_stats(rows: list[tuple[Any, Any, str]]) -> StatsReport:
    """rows: (SignalOutcome, Signal, ticker) uclusu."""
    if not rows:
        return StatsReport()

    returns = [float(outcome.return_pct) for outcome, _, _ in rows]

    def pattern_label(signal: Any) -> str:
        info = get_info_safe(signal.pattern)
        return info.label if info else str(signal.pattern)

    def score_bucket(signal: Any) -> str | None:
        score = signal.final_score
        if score is None:
            return None
        for label, low, high in SCORE_BUCKETS:
            if low <= score < high:
                return label
        return None

    return StatsReport(
        evaluated=len(rows),
        hit_rate=round(sum(1 for value in returns if value > 0) / len(returns), 4),
        avg_return_pct=round(mean(returns), 3),
        median_return_pct=round(median(returns), 3),
        horizon=rows[0][0].horizon,
        by_pattern=_grouped(
            (pattern_label(signal), float(outcome.return_pct)) for outcome, signal, _ in rows
        ),
        by_score=_grouped(
            (bucket, float(outcome.return_pct))
            for outcome, signal, _ in rows
            if (bucket := score_bucket(signal)) is not None
        ),
        by_direction=_grouped(
            (str(signal.direction), float(outcome.return_pct)) for outcome, signal, _ in rows
        ),
        by_confirmation=_grouped(
            (
                "Kırılım teyitli" if signal.confirmed_at else "Teyitsiz",
                float(outcome.return_pct),
            )
            for outcome, signal, _ in rows
        ),
    )
