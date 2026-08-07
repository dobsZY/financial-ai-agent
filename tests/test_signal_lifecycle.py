"""Kirilim teyidi, fiyat alarmlari, sonuc takibi ve istatistik (Faz 6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest

from core import pipeline
from core.stats import build_stats
from database import db_manager
from main import app
from schemas.market import Interval, OHLCVFrame, SymbolConfig
from schemas.signal import Detection, Direction, Pattern, SignalCandidate

START = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _frame(closes: list[float], ticker: str = "AAPL", volume: float = 1000.0) -> OHLCVFrame:
    index = pd.date_range(START, periods=len(closes), freq="h", tz="UTC", name="ts")
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [volume] * len(closes),
        },
        index=index,
    )
    return OHLCVFrame(symbol=SymbolConfig.from_ticker(ticker, interval=Interval.H1), df=df)


async def _seed_signal(
    pattern: Pattern = Pattern.ASC_TRIANGLE,
    direction: Direction = Direction.LONG,
    breakout_level: float | None = 105.0,
    bucket_ts: datetime = START,
    price: float = 100.0,
) -> int:
    detection = Detection(
        pattern=pattern, confidence=0.8, source="test", breakout_level=breakout_level
    )
    candidate = SignalCandidate(
        ticker="AAPL",
        interval=Interval.H1.value,
        detection=detection,
        bucket_ts=bucket_ts,
        price=price,
        indicator_score=0.3,
        sentiment=0.2,
        mtf_score=0.5,
        final_score=0.72,
    )
    async with db_manager.session_scope() as session:
        signal = await db_manager.save_signal(
            session, candidate, cutoff=START - timedelta(days=1)
        )
        assert signal is not None
        return signal.id


@pytest.fixture
def notify_spy(monkeypatch: pytest.MonkeyPatch) -> list:
    sent: list = []

    async def fake_notify(notification, fan_out: bool = False):
        sent.append(notification)
        return ["telegram"]

    monkeypatch.setattr(pipeline, "notify", fake_notify)
    return sent


# --- skor bilesenleri kaydi ------------------------------------------------


async def test_signal_persists_score_components(clean_db: None) -> None:
    """Bilesenler artik toplamda kaybolmuyor, ayri ayri saklaniyor."""
    signal_id = await _seed_signal()

    row = await db_manager.get_signal(signal_id)

    assert row is not None
    signal = row[0]
    assert signal.indicator_score == 0.3
    assert signal.sentiment == 0.2
    assert signal.mtf_score == 0.5
    assert signal.breakout_level == 105.0
    assert signal.interval == "1h"


# --- kirilim teyidi --------------------------------------------------------


async def test_breakout_confirms_when_level_is_crossed(
    notify_spy: list, clean_db: None
) -> None:
    signal_id = await _seed_signal(breakout_level=105.0)
    frames = {"AAPL": _frame([100, 101, 102, 104, 106, 107])}

    confirmed = await pipeline.check_breakouts(frames)

    assert confirmed == 1
    row = await db_manager.get_signal(signal_id)
    assert row is not None and row[0].confirmed_at is not None
    assert row[0].confirmed_price == 106.0
    assert len(notify_spy) == 1
    assert "KIRILIM" in notify_spy[0].title


async def test_breakout_waits_when_level_not_reached(
    notify_spy: list, clean_db: None
) -> None:
    signal_id = await _seed_signal(breakout_level=120.0)
    frames = {"AAPL": _frame([100, 101, 102, 104, 106])}

    assert await pipeline.check_breakouts(frames) == 0

    row = await db_manager.get_signal(signal_id)
    assert row is not None and row[0].confirmed_at is None
    assert notify_spy == []


async def test_short_breakout_needs_price_below_level(
    notify_spy: list, clean_db: None
) -> None:
    await _seed_signal(
        pattern=Pattern.DESC_TRIANGLE, direction=Direction.SHORT, breakout_level=98.0
    )
    rising = {"AAPL": _frame([100, 101, 102, 103])}
    falling = {"AAPL": _frame([100, 99, 97, 96])}

    assert await pipeline.check_breakouts(rising) == 0
    assert await pipeline.check_breakouts(falling) == 1


async def test_breakout_is_confirmed_only_once(notify_spy: list, clean_db: None) -> None:
    await _seed_signal(breakout_level=105.0)
    frames = {"AAPL": _frame([100, 102, 106, 108])}

    first = await pipeline.check_breakouts(frames)
    second = await pipeline.check_breakouts(frames)

    assert (first, second) == (1, 0)
    assert len(notify_spy) == 1


async def test_bars_before_the_signal_do_not_count(notify_spy: list, clean_db: None) -> None:
    """Sinyal mumundan onceki kirilim sayilmamali (ileriye donuk veri yok)."""
    late = START + timedelta(hours=4)
    await _seed_signal(breakout_level=105.0, bucket_ts=late)
    frames = {"AAPL": _frame([100, 106, 107, 101, 102])}  # kirilim sinyalden once

    assert await pipeline.check_breakouts(frames) == 0


# --- fiyat alarmlari -------------------------------------------------------


async def test_alert_fires_above_and_closes(notify_spy: list, clean_db: None) -> None:
    alert = await db_manager.create_alert("AAPL", "above", 105.0, note="hedef")
    frames = {"AAPL": _frame([100, 103, 107])}

    fired = await pipeline.check_alerts(frames)

    assert fired == 1
    assert len(notify_spy) == 1
    assert "AAPL" in notify_spy[0].title
    assert "hedef" in notify_spy[0].body

    stored = await db_manager.list_alerts()
    assert stored[0].is_active is False
    assert stored[0].triggered_price == 107.0
    assert alert.id == stored[0].id

    # tek atimlik: ikinci kontrolde tekrar tetiklenmez
    assert await pipeline.check_alerts(frames) == 0


async def test_alert_below_direction(notify_spy: list, clean_db: None) -> None:
    await db_manager.create_alert("AAPL", "below", 95.0)

    assert await pipeline.check_alerts({"AAPL": _frame([100, 98, 96])}) == 0
    assert await pipeline.check_alerts({"AAPL": _frame([100, 98, 94])}) == 1


# --- sonuc takibi ve istatistik -------------------------------------------


async def test_outcome_evaluation_and_stats(clean_db: None) -> None:
    frame = _frame([100 + i for i in range(20)])
    await db_manager.save_frames([frame])
    await _seed_signal(bucket_ts=START, price=100.0)

    stats = await pipeline.evaluate_outcomes(horizon=5)

    assert stats["evaluated"] == 1
    rows = await db_manager.outcome_rows()
    assert len(rows) == 1
    assert rows[0][0].return_pct == pytest.approx(5.0, abs=0.01)
    assert rows[0][0].is_hit is True

    report = build_stats(rows)
    assert report.evaluated == 1
    assert report.hit_rate == 1.0
    assert report.by_pattern[0].label == "Yükselen Üçgen"
    assert report.by_confirmation[0].label == "Teyitsiz"


async def test_outcome_is_written_once(clean_db: None) -> None:
    frame = _frame([100 + i for i in range(20)])
    await db_manager.save_frames([frame])
    await _seed_signal()

    first = await pipeline.evaluate_outcomes(horizon=5)
    second = await pipeline.evaluate_outcomes(horizon=5)

    assert first["evaluated"] == 1
    assert second["pending"] == 0


async def test_outcome_skips_when_data_is_short(clean_db: None) -> None:
    await db_manager.save_frames([_frame([100, 101, 102])])
    await _seed_signal()

    stats = await pipeline.evaluate_outcomes(horizon=50)

    assert stats["evaluated"] == 0
    assert stats["not_ready"] == 1


def test_stats_groups_by_confirmation() -> None:
    class _Outcome:
        def __init__(self, ret: float) -> None:
            self.return_pct = ret
            self.horizon = 5

    class _Signal:
        def __init__(self, confirmed: bool, score: float) -> None:
            self.pattern = "asc_triangle"
            self.direction = "LONG"
            self.final_score = score
            self.confirmed_at = datetime.now(timezone.utc) if confirmed else None

    rows = [
        (_Outcome(4.0), _Signal(True, 0.8), "AAPL"),
        (_Outcome(2.0), _Signal(True, 0.8), "AAPL"),
        (_Outcome(-3.0), _Signal(False, 0.62), "AAPL"),
    ]

    report = build_stats(rows)

    confirmed = next(g for g in report.by_confirmation if g.label == "Kırılım teyitli")
    unconfirmed = next(g for g in report.by_confirmation if g.label == "Teyitsiz")
    assert confirmed.hit_rate == 1.0
    assert unconfirmed.hit_rate == 0.0
    assert report.by_score[0].label == ">=0.75"


# --- API -------------------------------------------------------------------


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_alert_api_crud(client: httpx.AsyncClient, clean_db: None) -> None:
    created = await client.post(
        "/alerts", json={"ticker": "garan.is", "direction": "above", "price": 130}
    )
    assert created.status_code == 201
    assert created.json()["ticker"] == "GARAN.IS"

    listed = (await client.get("/alerts")).json()
    assert len(listed) == 1

    alert_id = created.json()["id"]
    assert (await client.delete(f"/alerts/{alert_id}")).status_code == 204
    assert (await client.get("/alerts")).json() == []
    assert (await client.delete(f"/alerts/{alert_id}")).status_code == 404


async def test_alert_api_rejects_bad_direction(
    client: httpx.AsyncClient, clean_db: None
) -> None:
    response = await client.post(
        "/alerts", json={"ticker": "AAPL", "direction": "sideways", "price": 10}
    )
    assert response.status_code == 422


async def test_stats_endpoint_is_empty_without_outcomes(
    client: httpx.AsyncClient, clean_db: None
) -> None:
    payload = (await client.get("/stats")).json()

    assert payload["evaluated"] == 0
    assert payload["by_pattern"] == []


async def test_stats_endpoint_after_evaluation(
    client: httpx.AsyncClient, clean_db: None
) -> None:
    await db_manager.save_frames([_frame([100 + i for i in range(20)])])
    await _seed_signal()

    await client.post("/stats/evaluate", params={"horizon": 5})
    payload = (await client.get("/stats")).json()

    assert payload["evaluated"] == 1
    assert payload["hit_rate"] == 1.0


async def test_api_exposes_score_components(client: httpx.AsyncClient, clean_db: None) -> None:
    """Kaydedilen bilesenler API'ye de yansimali (donusturucu alanlari atlamamali)."""
    await _seed_signal()

    payload = (await client.get("/signals")).json()[0]

    assert payload["indicator_score"] == 0.3
    assert payload["sentiment"] == 0.2
    assert payload["mtf_score"] == 0.5
    assert payload["breakout_level"] == 105.0
    assert payload["interval"] == "1h"
    assert payload["confirmed_at"] is None


async def test_api_reports_confirmation(client: httpx.AsyncClient, clean_db: None) -> None:
    signal_id = await _seed_signal(breakout_level=105.0)
    await pipeline.check_breakouts({"AAPL": _frame([100, 103, 107])}, send_notification=False)

    payload = (await client.get(f"/signals/{signal_id}")).json()

    assert payload["confirmed_at"] is not None
    assert payload["confirmed_price"] == 107.0
