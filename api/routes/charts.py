from __future__ import annotations

import time
from typing import Final

from fastapi import APIRouter, HTTPException, Query, Response

from core.chart_factory import ChartRenderError, render_chart, to_png_bytes
from core.data_fetcher import fetch_many
from core.logger import get_logger
from database import db_manager
from schemas.market import Interval, OHLCVFrame, SymbolConfig

logger = get_logger(__name__)

router = APIRouter(tags=["charts"])

# Grafik uretimi pahalidir (matplotlib); ayni istek kisa sure icinde tekrarlanirsa
# RAM'deki PNG yeniden kullanilir. Disk kullanilmaz (K-02).
_CACHE_TTL_SECONDS: Final = 300
_CACHE_MAX_ENTRIES: Final = 64
_cache: dict[tuple, tuple[float, bytes]] = {}


def _cache_get(key: tuple) -> bytes | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    created_at, payload = entry
    if time.monotonic() - created_at > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple, payload: bytes) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        oldest = min(_cache, key=lambda item: _cache[item][0])
        _cache.pop(oldest, None)
    _cache[key] = (time.monotonic(), payload)


async def _load_frame(ticker: str, interval: Interval, candles: int) -> OHLCVFrame | None:
    """Once DB'deki mumlar; yoksa canli cekim (K-03: hata yutulur)."""
    frame = await db_manager.load_frame(ticker, interval=interval, limit=max(candles * 2, 200))
    if frame is not None and not frame.is_empty:
        return frame

    try:
        frames = await fetch_many([SymbolConfig.from_ticker(ticker, interval=interval)])
    except Exception as exc:  # noqa: BLE001
        logger.warning("charts.fetch_failed", ticker=ticker, error=str(exc))
        return None
    return next(iter(frames.values()), None)


@router.get(
    "/charts/{ticker}",
    responses={200: {"content": {"image/png": {}}}},
    response_class=Response,
)
async def get_chart(
    ticker: str,
    interval: Interval = Interval.H1,
    candles: int = Query(default=120, ge=20, le=500),
    width: int | None = Query(default=None, ge=160, le=1600),
    # Alt sinir 60: liste satirlarindaki mini grafikler (sparkline) icin
    height: int | None = Query(default=None, ge=60, le=1200),
    volume: bool = True,
    theme: str = Query(default="dark", pattern="^(dark|light)$"),
) -> Response:
    """Sembolun mum grafigini PNG olarak dondurur; diske hicbir sey yazilmaz (K-02)."""
    key = (ticker.strip().upper(), interval.value, candles, width, height, volume, theme)
    cached = _cache_get(key)
    if cached is not None:
        return Response(content=cached, media_type="image/png")

    frame = await _load_frame(ticker, interval, candles)
    if frame is None or frame.is_empty:
        raise HTTPException(status_code=404, detail="Sembol icin veri bulunamadi")

    try:
        array = await render_chart(
            frame, width=width, height=height, candles=candles, volume=volume, theme=theme
        )
        payload = to_png_bytes(array)
    except ChartRenderError as exc:
        logger.warning("charts.render_failed", ticker=ticker, error=str(exc))
        raise HTTPException(status_code=500, detail="Grafik uretilemedi") from exc

    _cache_put(key, payload)
    return Response(content=payload, media_type="image/png")
