"""Uretilmis sinyallerin gecmis performansi (ROADMAP 5.2).

Her sinyal icin, sinyal mumundan `horizon` mum sonraki kapanisa bakilir ve yone
gore getiri hesaplanir (LONG'da yukselis, SHORT'ta dusus kazanctir). Ileriye
donuk veri sizintisi olmaz: yalnizca `bucket_ts`'ten **sonraki** mumlar kullanilir.

    python -m core.backtest --horizon 5 --min-score 0.6

Not: Bu bir performans olcumudur, yatirim tavsiyesi degildir.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from statistics import mean, median

from pydantic import BaseModel, ConfigDict

from core.logger import get_logger, setup_logging
from database import db_manager
from schemas.market import Interval, OHLCVFrame
from schemas.signal import Direction

logger = get_logger(__name__)

CANDLE_LOOKBACK = 5000

# Skor gruplari: esik ayarinin isabete etkisini gormek icin
SCORE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<0.60", 0.0, 0.60),
    ("0.60-0.75", 0.60, 0.75),
    (">=0.75", 0.75, 1.01),
)


class SignalOutcome(BaseModel):
    """Tek bir sinyalin sonucu."""

    model_config = ConfigDict(frozen=True)

    signal_id: int
    ticker: str
    pattern: str
    direction: str
    final_score: float | None
    bucket_ts: datetime
    entry_price: float
    exit_price: float
    return_pct: float

    @property
    def is_hit(self) -> bool:
        return self.return_pct > 0


class GroupStats(BaseModel):
    """Formasyon veya skor grubu bazinda ozet."""

    model_config = ConfigDict(frozen=True)

    label: str
    count: int
    hit_rate: float
    avg_return_pct: float


class BacktestReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon: int
    evaluated: int
    skipped: int
    hit_rate: float = 0.0
    avg_return_pct: float = 0.0
    median_return_pct: float = 0.0
    best: SignalOutcome | None = None
    worst: SignalOutcome | None = None
    by_pattern: list[GroupStats] = []
    by_score: list[GroupStats] = []

    def format_text(self) -> str:
        if self.evaluated == 0:
            return (
                f"Degerlendirilebilir sinyal yok (atlanan: {self.skipped}).\n"
                "Sinyal mumundan sonra yeterli mum kaydi olmali — once tarama calistirin."
            )

        lines = [
            f"Backtest — {self.horizon} mum sonrasi",
            f"  Degerlendirilen : {self.evaluated} (atlanan: {self.skipped})",
            f"  Isabet orani    : %{self.hit_rate * 100:.1f}",
            f"  Ortalama getiri : %{self.avg_return_pct:+.2f}",
            f"  Medyan getiri   : %{self.median_return_pct:+.2f}",
        ]
        if self.best:
            lines.append(
                f"  En iyi          : {self.best.ticker} {self.best.pattern} "
                f"%{self.best.return_pct:+.2f}"
            )
        if self.worst:
            lines.append(
                f"  En kotu         : {self.worst.ticker} {self.worst.pattern} "
                f"%{self.worst.return_pct:+.2f}"
            )

        for title, groups in (("Formasyon", self.by_pattern), ("Skor", self.by_score)):
            if not groups:
                continue
            lines.append(f"\n  {title} bazinda:")
            for group in groups:
                lines.append(
                    f"    {group.label:<22} n={group.count:<4} "
                    f"isabet=%{group.hit_rate * 100:5.1f}  ort=%{group.avg_return_pct:+.2f}"
                )
        return "\n".join(lines)


def _group(label: str, outcomes: list[SignalOutcome]) -> GroupStats:
    return GroupStats(
        label=label,
        count=len(outcomes),
        hit_rate=sum(1 for item in outcomes if item.is_hit) / len(outcomes),
        avg_return_pct=round(mean(item.return_pct for item in outcomes), 3),
    )


def _as_utc(moment: datetime) -> datetime:
    """SQLite tz-naive dondurur; pandas karsilastirmasi icin UTC'ye tasinir."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _future_close(frame: OHLCVFrame, bucket_ts: datetime, horizon: int) -> float | None:
    """`bucket_ts`'ten sonraki `horizon`. mumun kapanisi; yoksa None."""
    future = frame.df[frame.df.index > bucket_ts]
    if len(future) < horizon:
        return None
    return float(future["close"].iloc[horizon - 1])


def evaluate_outcome(
    signal_id: int,
    ticker: str,
    pattern: str,
    direction: str,
    final_score: float | None,
    bucket_ts: datetime,
    entry_price: float | None,
    frame: OHLCVFrame,
    horizon: int,
) -> SignalOutcome | None:
    """Tek sinyali degerlendirir; veri yetersizse None doner."""
    bucket_ts = _as_utc(bucket_ts)
    exit_price = _future_close(frame, bucket_ts, horizon)
    if exit_price is None:
        return None

    entry = entry_price
    if entry is None:
        at_signal = frame.df[frame.df.index <= bucket_ts]
        if at_signal.empty:
            return None
        entry = float(at_signal["close"].iloc[-1])
    if entry <= 0:
        return None

    change = (exit_price - entry) / entry * 100.0
    if direction == Direction.SHORT.value:
        change = -change

    return SignalOutcome(
        signal_id=signal_id,
        ticker=ticker,
        pattern=pattern,
        direction=direction,
        final_score=final_score,
        bucket_ts=bucket_ts,
        entry_price=round(entry, 4),
        exit_price=round(exit_price, 4),
        return_pct=round(change, 3),
    )


def build_report(horizon: int, outcomes: list[SignalOutcome], skipped: int) -> BacktestReport:
    if not outcomes:
        return BacktestReport(horizon=horizon, evaluated=0, skipped=skipped)

    returns = [item.return_pct for item in outcomes]
    by_pattern: dict[str, list[SignalOutcome]] = {}
    for outcome in outcomes:
        by_pattern.setdefault(outcome.pattern, []).append(outcome)

    by_score: list[GroupStats] = []
    for label, low, high in SCORE_BUCKETS:
        bucket = [
            item for item in outcomes if item.final_score is not None and low <= item.final_score < high
        ]
        if bucket:
            by_score.append(_group(label, bucket))

    return BacktestReport(
        horizon=horizon,
        evaluated=len(outcomes),
        skipped=skipped,
        hit_rate=round(sum(1 for item in outcomes if item.is_hit) / len(outcomes), 4),
        avg_return_pct=round(mean(returns), 3),
        median_return_pct=round(median(returns), 3),
        best=max(outcomes, key=lambda item: item.return_pct),
        worst=min(outcomes, key=lambda item: item.return_pct),
        by_pattern=sorted(
            (_group(name, items) for name, items in by_pattern.items()),
            key=lambda group: group.count,
            reverse=True,
        ),
        by_score=by_score,
    )


async def run_backtest(
    horizon: int = 5,
    min_score: float | None = None,
    pattern: str | None = None,
    limit: int = 500,
) -> BacktestReport:
    """DB'deki sinyalleri `horizon` mum ileriye tasiyarak degerlendirir."""
    rows = await db_manager.signals_for_backtest(
        limit=limit, min_score=min_score, pattern=pattern
    )

    frames: dict[tuple[str, str], OHLCVFrame | None] = {}
    outcomes: list[SignalOutcome] = []
    skipped = 0

    for signal, ticker, interval in rows:
        key = (ticker, interval)
        if key not in frames:
            frames[key] = await db_manager.load_frame(
                ticker, interval=Interval(interval), limit=CANDLE_LOOKBACK
            )
        frame = frames[key]
        if frame is None or frame.is_empty:
            skipped += 1
            continue

        outcome = evaluate_outcome(
            signal_id=signal.id,
            ticker=ticker,
            pattern=signal.pattern,
            direction=signal.direction,
            final_score=signal.final_score,
            bucket_ts=signal.bucket_ts,
            entry_price=signal.price_at_signal,
            frame=frame,
            horizon=horizon,
        )
        if outcome is None:
            skipped += 1
            continue
        outcomes.append(outcome)

    report = build_report(horizon, outcomes, skipped)
    logger.info(
        "backtest.completed",
        horizon=horizon,
        evaluated=report.evaluated,
        skipped=report.skipped,
        hit_rate=report.hit_rate,
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sinyal backtest raporu")
    parser.add_argument("--horizon", type=int, default=5, help="Kac mum sonrasina bakilacak")
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--pattern", type=str, default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json", action="store_true", help="Raporu JSON olarak yaz")
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    report = await run_backtest(
        horizon=args.horizon,
        min_score=args.min_score,
        pattern=args.pattern,
        limit=args.limit,
    )
    await db_manager.dispose_engine()

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(report.format_text())
    return 0


if __name__ == "__main__":
    setup_logging()
    raise SystemExit(asyncio.run(_main()))
