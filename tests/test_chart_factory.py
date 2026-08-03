from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.chart_factory import ChartRenderError, render_chart, to_png_bytes
from schemas.market import OHLCVFrame


async def test_render_chart_returns_bgr_array(frame: OHLCVFrame, no_png_written: Path) -> None:
    array = await render_chart(frame, width=640, height=640)

    assert isinstance(array, np.ndarray)
    assert array.shape == (640, 640, 3)
    assert array.dtype == np.uint8
    assert array.std() > 0


async def test_render_chart_rejects_short_series(frame: OHLCVFrame) -> None:
    short = frame.tail(5)

    with pytest.raises(ChartRenderError):
        await render_chart(short)


async def test_to_png_bytes_roundtrip(frame: OHLCVFrame, no_png_written: Path) -> None:
    array = await render_chart(frame, width=320, height=320)

    payload = to_png_bytes(array)

    assert payload.startswith(b"\x89PNG")
