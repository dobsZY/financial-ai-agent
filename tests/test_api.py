from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest

from core import pipeline
from database import db_manager
from main import app
from schemas.market import Interval
from schemas.signal import Detection, Pattern, SignalCandidate


@pytest.fixture
async def client(clean_db: None) -> AsyncIterator[httpx.AsyncClient]:
    """Lifespan calistirmadan ASGI istemcisi (scheduler testte baslatilmaz)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def _seed_signal(ticker: str = "AAPL", score: float = 0.82) -> int:
    candidate = SignalCandidate(
        ticker=ticker,
        interval=Interval.H1.value,
        detection=Detection(pattern=Pattern.BULL_FLAG, confidence=0.9, source="test"),
        bucket_ts=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
        price=210.5,
        final_score=score,
    )
    cutoff = datetime(2026, 8, 4, 0, tzinfo=timezone.utc)
    async with db_manager.session_scope() as session:
        signal = await db_manager.save_signal(session, candidate, cutoff)
        assert signal is not None
        return signal.id


async def test_list_signals_returns_saved_rows(client: httpx.AsyncClient) -> None:
    signal_id = await _seed_signal()

    response = await client.get("/signals")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == signal_id
    assert payload[0]["ticker"] == "AAPL"
    assert payload[0]["pattern"] == "bull_flag"


async def test_list_signals_filters(client: httpx.AsyncClient) -> None:
    await _seed_signal("AAPL", score=0.82)
    await _seed_signal("THYAO.IS", score=0.40)

    by_ticker = await client.get("/signals", params={"ticker": "thyao.is"})
    by_score = await client.get("/signals", params={"min_score": 0.5})

    assert [item["ticker"] for item in by_ticker.json()] == ["THYAO.IS"]
    assert [item["ticker"] for item in by_score.json()] == ["AAPL"]


async def test_get_signal_detail_and_404(client: httpx.AsyncClient) -> None:
    signal_id = await _seed_signal()

    found = await client.get(f"/signals/{signal_id}")
    missing = await client.get("/signals/9999")

    assert found.status_code == 200
    assert found.json()["price_at_signal"] == 210.5
    assert missing.status_code == 404


async def test_symbol_crud_flow(client: httpx.AsyncClient) -> None:
    created = await client.post("/symbols", json={"ticker": "thyao.is", "interval": "1d"})
    assert created.status_code == 201
    assert created.json()["ticker"] == "THYAO.IS"
    assert created.json()["market"] == "BIST"

    listed = await client.get("/symbols")
    assert [item["ticker"] for item in listed.json()] == ["THYAO.IS"]

    patched = await client.patch("/symbols/THYAO.IS", json={"is_active": False})
    assert patched.json()["is_active"] is False
    assert (await client.get("/symbols", params={"active_only": True})).json() == []

    assert (await client.delete("/symbols/THYAO.IS")).status_code == 204
    assert (await client.get("/symbols")).json() == []


async def test_symbol_update_and_delete_404(client: httpx.AsyncClient) -> None:
    assert (await client.patch("/symbols/NOPE", json={"is_active": True})).status_code == 404
    assert (await client.delete("/symbols/NOPE")).status_code == 404


async def test_create_symbol_is_idempotent(client: httpx.AsyncClient) -> None:
    first = await client.post("/symbols", json={"ticker": "AAPL"})
    second = await client.post("/symbols", json={"ticker": "aapl"})

    assert first.json()["id"] == second.json()["id"]


async def test_manual_scan_triggers_pipeline(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_scan(**kwargs: object) -> pipeline.ScanResult:
        calls.append(kwargs)
        return pipeline.ScanResult(scanned=2, detections=1, saved=1, notified=1)

    monkeypatch.setattr(pipeline, "run_scan", fake_scan)

    response = await client.post(
        "/scan", json={"tickers": ["AAPL"], "interval": "1h", "send_notification": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["saved"] == 1
    assert calls[0]["tickers"] == ["AAPL"]
    assert calls[0]["send_notification"] is False


async def test_manual_scan_background_returns_immediately(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_scan(**kwargs: object) -> pipeline.ScanResult:
        return pipeline.ScanResult()

    monkeypatch.setattr(pipeline, "run_scan", fake_scan)

    response = await client.post("/scan", json={"background": True})

    assert response.json() == {"status": "queued"}


async def test_job_runs_endpoint(client: httpx.AsyncClient) -> None:
    job_id = await db_manager.start_job_run("intraday_scan_bist")
    await db_manager.finish_job_run(job_id, status="success", items_processed=3)

    response = await client.get("/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["job_name"] == "intraday_scan_bist"
    assert payload[0]["items_processed"] == 3
    assert payload[0]["status"] == "success"
