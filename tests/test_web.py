from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from database import db_manager
from main import WEB_DIR, app
from schemas.market import OHLCVFrame


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- statik panel ---------------------------------------------------------


def test_web_directory_ships_required_files() -> None:
    assert WEB_DIR.is_dir()
    for name in ("index.html", "app.css", "app.js"):
        assert (WEB_DIR / name).is_file(), name


async def test_root_redirects_to_panel(client: httpx.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code in (307, 308)
    assert response.headers["location"] == "/app/"


async def test_panel_index_is_served(client: httpx.AsyncClient) -> None:
    response = await client.get("/app/")

    assert response.status_code == 200
    assert "Financial Command Center" in response.text
    assert "/app/app.js" in response.text


@pytest.mark.parametrize(
    "path,needle",
    [("/app/app.css", "--brand"), ("/app/app.js", "loadAll")],
)
async def test_static_assets_are_served(
    client: httpx.AsyncClient, path: str, needle: str
) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert needle in response.text


async def test_panel_does_not_shadow_api(client: httpx.AsyncClient) -> None:
    """Statik mount, API uclarini gölgelememeli."""
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/patterns")).status_code == 200


# --- panelin ihtiyac duydugu alanlar --------------------------------------


async def test_health_exposes_market_sessions(client: httpx.AsyncClient) -> None:
    payload = (await client.get("/health")).json()

    assert set(payload["markets"]) == {"BIST", "NASDAQ"}
    assert all(isinstance(v, bool) for v in payload["markets"].values())


async def test_chart_theme_changes_output(
    client: httpx.AsyncClient, frame: OHLCVFrame, clean_db: None
) -> None:
    await db_manager.save_frames([frame])

    dark = await client.get("/charts/AAPL", params={"width": 320, "height": 200, "theme": "dark"})
    light = await client.get("/charts/AAPL", params={"width": 320, "height": 200, "theme": "light"})

    assert dark.status_code == light.status_code == 200
    assert dark.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert dark.content != light.content, "tema onbellek anahtarina dahil olmali"


async def test_chart_rejects_unknown_theme(
    client: httpx.AsyncClient, frame: OHLCVFrame, clean_db: None
) -> None:
    await db_manager.save_frames([frame])

    response = await client.get("/charts/AAPL", params={"theme": "neon"})

    assert response.status_code == 422


async def test_sparkline_height_is_allowed(
    client: httpx.AsyncClient, frame: OHLCVFrame, clean_db: None
) -> None:
    """Liste satirlarindaki mini grafikler 100px yukseklikle istenir."""
    await db_manager.save_frames([frame])

    ok = await client.get("/charts/AAPL", params={"width": 320, "height": 100, "volume": False})
    too_small = await client.get("/charts/AAPL", params={"width": 320, "height": 40})

    assert ok.status_code == 200
    assert too_small.status_code == 422


# --- canlı takip -----------------------------------------------------------


async def test_quote_returns_live_snapshot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, frame: OHLCVFrame, clean_db: None
) -> None:
    async def fake_fetch(configs, **kwargs):
        return {configs[0].yf_ticker: frame}

    monkeypatch.setattr("api.routes.quotes.fetch_many", fake_fetch)

    payload = (await client.get("/quote/AAPL")).json()

    assert payload["ticker"] == "AAPL"
    assert payload["market"] == "NASDAQ"
    assert payload["price"] == pytest.approx(float(frame.df["close"].iloc[-1]), abs=1e-3)
    assert payload["change"] == pytest.approx(
        payload["price"] - payload["previous_close"], abs=1e-3
    )
    assert {"rsi", "ema_50", "macd_hist", "volume_ratio"} <= set(payload["indicators"])


async def test_quote_persists_fetched_candles(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, frame: OHLCVFrame, clean_db: None
) -> None:
    async def fake_fetch(configs, **kwargs):
        return {configs[0].yf_ticker: frame}

    monkeypatch.setattr("api.routes.quotes.fetch_many", fake_fetch)

    await client.get("/quote/AAPL")

    stored = await db_manager.load_frame("AAPL")
    assert stored is not None and not stored.is_empty


async def test_quote_reports_unreachable_source(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, clean_db: None
) -> None:
    async def boom(configs, **kwargs):
        raise RuntimeError("ağ hatası")

    monkeypatch.setattr("api.routes.quotes.fetch_many", boom)

    response = await client.get("/quote/AAPL")

    assert response.status_code == 502
    assert "ulaşılamadı" in response.json()["detail"]


async def test_live_chart_bypasses_cache_and_db(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, frame: OHLCVFrame, clean_db: None
) -> None:
    """live=true DB'yi degil kaynagi kullanmali."""
    calls: list[str] = []

    async def fake_fetch(configs, **kwargs):
        calls.append(configs[0].yf_ticker)
        return {configs[0].yf_ticker: frame}

    monkeypatch.setattr("api.routes.charts.fetch_many", fake_fetch)
    await db_manager.save_frames([frame])

    normal = await client.get("/charts/AAPL", params={"width": 320, "height": 200})
    live = await client.get("/charts/AAPL", params={"width": 320, "height": 200, "live": True})

    assert normal.status_code == live.status_code == 200
    assert calls == ["AAPL"], "yalnizca live cagrisi kaynaga gitmeli"


async def test_turkish_text_survives_the_api(client: httpx.AsyncClient) -> None:
    """Kullaniciya donen metinler Turkce karakterleri korumali."""
    payload = (await client.get("/patterns/asc_triangle")).json()

    assert payload["label"] == "Yükselen Üçgen"
    assert "Direnç" in payload["summary"]
    assert payload["family"] == "devam"
    assert (await client.get("/patterns/double_top")).json()["label"] == "Çift Tepe"
