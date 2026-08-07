"""Telegram komut isleyicisi (Faz 6.4) — ag katmani mock'lanir."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import db_manager
from notifications import telegram_commands as tc
from schemas.market import Interval
from schemas.signal import Detection, Pattern, SignalCandidate

START = datetime(2026, 8, 1, tzinfo=timezone.utc)


async def _seed_signal(ticker: str = "GARAN.IS") -> None:
    candidate = SignalCandidate(
        ticker=ticker,
        interval=Interval.H1.value,
        detection=Detection(pattern=Pattern.ASC_TRIANGLE, confidence=0.83, source="rules"),
        bucket_ts=START,
        price=141.2,
        final_score=0.74,
    )
    async with db_manager.session_scope() as session:
        await db_manager.save_signal(session, candidate, cutoff=START - timedelta(days=1))


async def test_help_lists_commands() -> None:
    reply = await tc.handle_command("/yardim")

    assert "/tara" in reply and "/alarm" in reply and "/canli" in reply


async def test_unknown_command_falls_back_to_help() -> None:
    reply = await tc.handle_command("/nedir")

    assert "Bilinmeyen komut" in reply
    assert "/durum" in reply


async def test_empty_input_is_safe() -> None:
    assert "/durum" in await tc.handle_command("   ")


async def test_status_reports_counts(clean_db: None) -> None:
    await _seed_signal()
    await db_manager.create_alert("AAPL", "above", 200.0)

    reply = await tc.handle_command("/durum")

    assert "Sinyal: 1" in reply
    assert "Açık alarm: 1" in reply


async def test_signals_command_lists_recent(clean_db: None) -> None:
    await _seed_signal()

    reply = await tc.handle_command("/sinyaller")

    assert "GARAN.IS" in reply
    assert "Yükselen Üçgen" in reply
    assert "0.74" in reply


async def test_signals_command_when_empty(clean_db: None) -> None:
    assert "yok" in await tc.handle_command("/sinyaller")


async def test_alert_command_creates_alert(
    monkeypatch: pytest.MonkeyPatch, clean_db: None
) -> None:
    class _Quote:
        price = 120.0

    async def fake_quote(ticker: str, *args, **kwargs):
        return _Quote()

    monkeypatch.setattr("api.routes.quotes.get_quote", fake_quote)

    reply = await tc.handle_command("/alarm GARAN.IS 130")

    assert "GARAN.IS" in reply and "130" in reply
    alerts = await db_manager.list_alerts(active_only=True)
    assert len(alerts) == 1
    assert alerts[0].direction == "above", "hedef fiyat guncel fiyatin ustunde"


async def test_alert_command_infers_below_direction(
    monkeypatch: pytest.MonkeyPatch, clean_db: None
) -> None:
    class _Quote:
        price = 140.0

    async def fake_quote(ticker: str, *args, **kwargs):
        return _Quote()

    monkeypatch.setattr("api.routes.quotes.get_quote", fake_quote)

    await tc.handle_command("/alarm GARAN.IS 130")

    alerts = await db_manager.list_alerts(active_only=True)
    assert alerts[0].direction == "below"


async def test_alert_command_validates_price(clean_db: None) -> None:
    assert "sayısal" in await tc.handle_command("/alarm GARAN.IS abc")
    assert "Kullanım" in await tc.handle_command("/alarm")


async def test_alerts_command_lists_open(clean_db: None) -> None:
    await db_manager.create_alert("THYAO.IS", "below", 300.0)

    reply = await tc.handle_command("/alarmlar")

    assert "THYAO.IS" in reply and "300" in reply


async def test_scan_command_runs_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import pipeline

    async def fake_scan(job_name: str, **kwargs):
        return pipeline.ScanResult(scanned=6, saved=2, notified=1, confirmed=1)

    monkeypatch.setattr(pipeline, "run_tracked_scan", fake_scan)

    reply = await tc.handle_command("/tara")

    assert "Taranan: 6" in reply
    assert "Kırılım: 1" in reply


async def test_live_command_formats_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Quote:
        ticker, price, change, change_pct = "GARAN.IS", 127.7, -0.4, -0.31
        high, low = 128.5, 127.0
        indicators = {"rsi": 43.8}

    async def fake_quote(ticker: str, *args, **kwargs):
        return _Quote()

    monkeypatch.setattr("api.routes.quotes.get_quote", fake_quote)

    reply = await tc.handle_command("/canli GARAN.IS")

    assert "127.70" in reply and "▼" in reply and "43.8" in reply


async def test_live_command_needs_symbol() -> None:
    assert "Kullanım" in await tc.handle_command("/canli")


async def test_live_command_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(ticker: str, *args, **kwargs):
        raise RuntimeError("ağ yok")

    monkeypatch.setattr("api.routes.quotes.get_quote", boom)

    assert "alınamadı" in await tc.handle_command("/canli GARAN.IS")


async def test_stats_command_without_data(clean_db: None) -> None:
    assert "yok" in await tc.handle_command("/istatistik")


async def test_command_accepts_bot_suffix() -> None:
    """Gruplarda komutlar /tara@botadi seklinde gelir."""
    reply = await tc.handle_command("/yardim@dobs_finance_bot")

    assert "/durum" in reply
