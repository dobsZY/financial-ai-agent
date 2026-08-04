from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from core import backtest
from database import db_manager
from schemas.market import Interval, OHLCVFrame, SymbolConfig
from schemas.signal import Detection, Direction, Pattern, SignalCandidate

START = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _rising_frame(ticker: str = "AAPL", rows: int = 20, step: float = 1.0) -> OHLCVFrame:
    """Her mumda `step` kadar artan deterministik seri."""
    index = pd.date_range(START, periods=rows, freq="h", tz="UTC", name="ts")
    close = [100.0 + step * i for i in range(rows)]
    df = pd.DataFrame(
        {
            "open": close,
            "high": [value + 0.5 for value in close],
            "low": [value - 0.5 for value in close],
            "close": close,
            "volume": [1000.0] * rows,
        },
        index=index,
    )
    return OHLCVFrame(symbol=SymbolConfig.from_ticker(ticker, interval=Interval.H1), df=df)


def _outcome(direction: Direction, horizon: int = 5, entry: float | None = 100.0):
    return backtest.evaluate_outcome(
        signal_id=1,
        ticker="AAPL",
        pattern=Pattern.BULL_FLAG.value,
        direction=direction.value,
        final_score=0.8,
        bucket_ts=START,
        entry_price=entry,
        frame=_rising_frame(),
        horizon=horizon,
    )


# --- tek sinyal degerlendirmesi -------------------------------------------


def test_long_signal_gains_in_uptrend() -> None:
    outcome = _outcome(Direction.LONG)

    assert outcome is not None
    assert outcome.exit_price == 105.0
    assert outcome.return_pct == 5.0
    assert outcome.is_hit


def test_short_signal_loses_in_uptrend() -> None:
    outcome = _outcome(Direction.SHORT)

    assert outcome is not None
    assert outcome.return_pct == -5.0
    assert not outcome.is_hit


def test_entry_falls_back_to_close_at_signal() -> None:
    outcome = _outcome(Direction.LONG, entry=None)

    assert outcome is not None
    assert outcome.entry_price == 100.0


def test_returns_none_when_horizon_exceeds_data() -> None:
    assert _outcome(Direction.LONG, horizon=100) is None


def test_only_future_candles_are_used() -> None:
    """Sinyal mumunun kendisi cikis olarak kullanilmamali (ileri veri sizintisi yok)."""
    outcome = _outcome(Direction.LONG, horizon=1)

    assert outcome is not None
    assert outcome.exit_price == 101.0


# --- rapor -----------------------------------------------------------------


def test_report_aggregates_hit_rate_and_groups() -> None:
    winner = _outcome(Direction.LONG)
    loser = _outcome(Direction.SHORT)
    assert winner is not None and loser is not None

    report = backtest.build_report(5, [winner, loser], skipped=3)

    assert report.evaluated == 2
    assert report.skipped == 3
    assert report.hit_rate == 0.5
    assert report.avg_return_pct == 0.0
    assert report.best is not None and report.best.return_pct == 5.0
    assert report.worst is not None and report.worst.return_pct == -5.0
    assert report.by_pattern[0].label == Pattern.BULL_FLAG.value
    assert report.by_score[0].label == ">=0.75"


def test_empty_report_explains_itself() -> None:
    report = backtest.build_report(5, [], skipped=2)

    assert report.evaluated == 0
    assert "yok" in report.format_text()


def test_report_text_contains_key_metrics() -> None:
    outcome = _outcome(Direction.LONG)
    assert outcome is not None

    text = backtest.build_report(5, [outcome], skipped=0).format_text()

    assert "Isabet orani" in text
    assert "%100.0" in text


# --- uctan uca (DB) --------------------------------------------------------


@pytest.fixture
async def seeded_db(clean_db: None) -> None:
    frame = _rising_frame()
    await db_manager.save_frames([frame])

    candidate = SignalCandidate(
        ticker="AAPL",
        interval=Interval.H1.value,
        detection=Detection(pattern=Pattern.BULL_FLAG, confidence=0.9, source="test"),
        bucket_ts=START,
        price=100.0,
        final_score=0.8,
    )
    async with db_manager.session_scope() as session:
        await db_manager.save_signal(session, candidate, cutoff=START - timedelta(days=1))


async def test_run_backtest_reads_signals_and_candles(seeded_db: None) -> None:
    report = await backtest.run_backtest(horizon=5)

    assert report.evaluated == 1
    assert report.hit_rate == 1.0
    assert report.avg_return_pct == 5.0


async def test_run_backtest_skips_when_horizon_too_long(seeded_db: None) -> None:
    report = await backtest.run_backtest(horizon=500)

    assert report.evaluated == 0
    assert report.skipped == 1


async def test_min_score_filter_excludes_low_signals(seeded_db: None) -> None:
    report = await backtest.run_backtest(horizon=5, min_score=0.95)

    assert report.evaluated == 0
