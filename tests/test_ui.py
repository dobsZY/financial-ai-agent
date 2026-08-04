from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import flet as ft
import httpx
import pytest

from database import db_manager
from main import app
from schemas.market import Interval, OHLCVFrame
from ui.api_client import ApiClient, ApiError
from ui.components.common import (
    format_dt,
    pattern_label,
    relative_time,
    score_color,
    to_base64,
)
from ui.components.news_card import NewsCard, sentiment_badge
from ui.components.signal_card import SignalCard


@pytest.fixture
async def api(clean_db: None) -> AsyncIterator[ApiClient]:
    """Gercek FastAPI uygulamasina baglanan istemci (ag yok, ASGI transport)."""
    client = ApiClient(base_url="http://test", transport=httpx.ASGITransport(app=app))
    yield client
    await client.close()


# --- bicimlendirme yardimcilari -------------------------------------------


def test_pattern_label_is_translated() -> None:
    assert pattern_label("inv_head_shoulders") == "Ters Omuz Bas Omuz"
    assert pattern_label("bilinmeyen_sey") == "Bilinmeyen Sey"


def test_relative_time_buckets() -> None:
    now = datetime.now(timezone.utc)
    assert relative_time((now - timedelta(seconds=20)).isoformat()) == "az once"
    assert relative_time((now - timedelta(minutes=45)).isoformat()) == "45 dk once"
    assert relative_time((now - timedelta(hours=5)).isoformat()) == "5 sa once"
    assert relative_time((now - timedelta(days=3)).isoformat()) == "3 gun once"
    assert relative_time(None) == "-"


def test_format_dt_handles_bad_input() -> None:
    assert format_dt("bozuk-tarih") == "-"
    assert format_dt(None) == "-"


def test_score_color_thresholds() -> None:
    assert score_color(0.9) == ft.Colors.GREEN_400
    assert score_color(0.65) == ft.Colors.AMBER_400
    assert score_color(0.3) == ft.Colors.ORANGE_300
    assert score_color(None) == ft.Colors.OUTLINE


def test_to_base64_roundtrip() -> None:
    payload = b"\x89PNG\r\n\x1a\n test"
    assert base64.b64decode(to_base64(payload)) == payload


# --- bilesenler -------------------------------------------------------------


def test_signal_card_builds_without_page() -> None:
    async def noop(signal: dict[str, object]) -> None:
        return None

    card = SignalCard(
        {
            "id": 1,
            "ticker": "GARAN.IS",
            "pattern": "asc_triangle",
            "direction": "LONG",
            "confidence": 0.83,
            "final_score": 0.74,
            "price_at_signal": 141.2,
            "bucket_ts": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "notified_at": None,
        },
        client=ApiClient(base_url="http://test"),
        on_open_chart=noop,
    )
    assert isinstance(card.content, ft.Container)


def test_news_card_without_summary_shows_placeholder() -> None:
    card = NewsCard({"id": 1, "source": "KAP", "title": "Test", "bullets": []})
    assert isinstance(card.content, ft.Container)


def test_sentiment_badge_reflects_direction() -> None:
    assert "Olumlu" in sentiment_badge(0.6).content.controls[-1].value
    assert "Olumsuz" in sentiment_badge(-0.6).content.controls[-1].value
    assert "Notr" in sentiment_badge(0.02).content.controls[-1].value
    assert "Ozet yok" in sentiment_badge(None).content.controls[-1].value


# --- API istemcisi ----------------------------------------------------------


async def test_client_reads_health_and_symbols(api: ApiClient) -> None:
    health = await api.health()
    assert health["status"] == "ok"

    created = await api.add_symbol("AAPL")
    symbols = await api.symbols()

    assert created["ticker"] == "AAPL"
    assert [item["ticker"] for item in symbols] == ["AAPL"]


async def test_client_symbol_lifecycle(api: ApiClient) -> None:
    await api.add_symbol("THYAO.IS", interval="1d")
    await api.set_symbol_active("THYAO.IS", False)
    assert (await api.symbols(active_only=True)) == []

    await api.delete_symbol("THYAO.IS")
    assert (await api.symbols()) == []


async def test_client_raises_api_error_on_404(api: ApiClient) -> None:
    with pytest.raises(ApiError):
        await api.set_symbol_active("YOKBOYLE", True)


async def test_client_returns_none_for_missing_chart(api: ApiClient) -> None:
    assert await api.chart_png("YOKBOYLE.IS") is None


async def test_chart_endpoint_renders_from_db(api: ApiClient, frame: OHLCVFrame) -> None:
    await db_manager.save_frames([frame])

    payload = await api.chart_png("AAPL", width=320, height=200, candles=40)

    assert payload is not None
    assert payload[:8] == b"\x89PNG\r\n\x1a\n", "PNG imzasi bekleniyor"


async def test_chart_endpoint_uses_cache(api: ApiClient, frame: OHLCVFrame) -> None:
    await db_manager.save_frames([frame])

    first = await api.chart_png("AAPL", width=320, height=200)
    second = await api.chart_png("AAPL", width=320, height=200)

    assert first == second


async def test_news_endpoint_returns_summary_fields(api: ApiClient) -> None:
    from schemas.news import LLMSummary, NewsItem, NewsSource, RiskLevel

    item = NewsItem(
        source=NewsSource.KAP,
        external_id="42",
        title="ASELSAN sozlesme imzaladi",
        ticker="ASELS.IS",
        url="https://kap.org.tr/x",
        published_at=datetime.now(timezone.utc),
    )
    summary = LLMSummary(
        sentiment=0.7,
        bullets=["250M USD sozlesme", "Ciroya olumlu katki", "Risk dusuk"],
        risk_level=RiskLevel.LOW,
        model="gemini-2.5-flash",
        tokens=120,
    )
    async with db_manager.session_scope() as session:
        await db_manager.save_news_item(session, item, summary)

    news = await api.news()

    assert len(news) == 1
    assert news[0]["ticker"] == "ASELS.IS"
    assert news[0]["sentiment"] == 0.7
    assert len(news[0]["bullets"]) == 3
    assert news[0]["risk_level"] == "low"


async def test_load_frame_returns_utc_index(frame: OHLCVFrame, clean_db: None) -> None:
    await db_manager.save_frames([frame])

    loaded = await db_manager.load_frame("AAPL", interval=Interval.H1, limit=50)

    assert loaded is not None
    assert len(loaded.df) == 50
    assert str(loaded.df.index.tz) == "UTC"
    assert list(loaded.df.columns) == ["open", "high", "low", "close", "volume"]


async def test_load_frame_returns_none_when_empty(clean_db: None) -> None:
    assert await db_manager.load_frame("YOKBOYLE.IS") is None
