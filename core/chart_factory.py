from __future__ import annotations

import asyncio
import io

import matplotlib

matplotlib.use("Agg")

import cv2  # noqa: E402
import mplfinance as mpf  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from config.settings import get_settings  # noqa: E402
from core.logger import get_logger  # noqa: E402
from schemas.market import OHLCVFrame  # noqa: E402

logger = get_logger(__name__)

DPI = 100
MIN_CANDLES = 20

_MPF_COLUMNS = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
}


class ChartRenderError(RuntimeError):
    """Grafik uretilemedigi durumlarda firlatilir."""


def _build_style() -> dict:
    market_colors = mpf.make_marketcolors(
        up="#26a69a",
        down="#ef5350",
        edge="inherit",
        wick="inherit",
        volume="in",
    )
    return mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=market_colors,
        gridstyle="",
        facecolor="#0e1117",
        figcolor="#0e1117",
    )


def _render_png_bytes(df: pd.DataFrame, width: int, height: int, volume: bool) -> bytes:
    """DataFrame -> PNG baytlari. Diske hicbir dosya yazilmaz (K-02)."""
    buffer = io.BytesIO()
    plot_df = df.rename(columns=_MPF_COLUMNS)
    mpf.plot(
        plot_df,
        type="candle",
        style=_build_style(),
        volume=volume,
        axisoff=True,
        tight_layout=True,
        figsize=(width / DPI, height / DPI),
        closefig=True,
        savefig={"fname": buffer, "dpi": DPI, "format": "png", "pad_inches": 0},
    )
    buffer.seek(0)
    return buffer.getvalue()


def _to_bgr_array(png_bytes: bytes, width: int, height: int) -> np.ndarray:
    array = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if array is None:
        raise ChartRenderError("PNG baytlari cozumlenemedi")
    if array.shape[0] != height or array.shape[1] != width:
        array = cv2.resize(array, (width, height), interpolation=cv2.INTER_AREA)
    return array


def render_chart_sync(
    frame: OHLCVFrame,
    width: int | None = None,
    height: int | None = None,
    candles: int = 120,
    volume: bool = True,
) -> np.ndarray:
    settings = get_settings()
    target_width = width or settings.chart_width
    target_height = height or settings.chart_height

    df = frame.df.tail(candles)
    if len(df) < MIN_CANDLES:
        raise ChartRenderError(
            f"{frame.symbol.yf_ticker}: grafik icin yetersiz mum ({len(df)} < {MIN_CANDLES})"
        )

    png_bytes = _render_png_bytes(df, target_width, target_height, volume)
    return _to_bgr_array(png_bytes, target_width, target_height)


async def render_chart(
    frame: OHLCVFrame,
    width: int | None = None,
    height: int | None = None,
    candles: int = 120,
    volume: bool = True,
) -> np.ndarray:
    """matplotlib bloklayicidir; thread pool'a alinir (K-01)."""
    array = await asyncio.to_thread(
        render_chart_sync, frame, width, height, candles, volume
    )
    logger.info(
        "chart.rendered",
        ticker=frame.symbol.yf_ticker,
        shape=tuple(array.shape),
        candles=min(candles, len(frame.df)),
    )
    return array


def to_png_bytes(array: np.ndarray) -> bytes:
    """ndarray -> PNG bayt (yalnizca UI/bildirim katmani icin, diske yazilmaz)."""
    success, encoded = cv2.imencode(".png", array)
    if not success:
        raise ChartRenderError("ndarray PNG'ye kodlanamadi")
    return encoded.tobytes()
