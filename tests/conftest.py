from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pandas as pd
import pytest

from helpers import make_ohlcv_df

_TMP_DB = Path(tempfile.gettempdir()) / "finance_test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["BIST_SYMBOLS"] = "THYAO.IS"
os.environ["NASDAQ_SYMBOLS"] = "AAPL"

from config.settings import get_settings  # noqa: E402
from schemas.market import Interval, OHLCVFrame, SymbolConfig  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
async def clean_db() -> AsyncIterator[None]:
    """Her testte bos sema; testler birbirinin kaydini gormez."""
    from database.db_manager import dispose_engine, get_engine
    from database.models import Base

    await dispose_engine()
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    return make_ohlcv_df()


@pytest.fixture
def symbol() -> SymbolConfig:
    return SymbolConfig.from_ticker("AAPL", interval=Interval.H1)


@pytest.fixture
def frame(symbol: SymbolConfig, ohlcv_df: pd.DataFrame) -> OHLCVFrame:
    return OHLCVFrame(symbol=symbol, df=ohlcv_df)


@pytest.fixture
def no_png_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Calisma dizinini izole eder; K-02 ihlali (diske .png yazimi) tespit edilir."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    assert list(tmp_path.rglob("*.png")) == [], "K-02 ihlali: diske PNG yazildi"
