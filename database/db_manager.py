from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import get_settings
from core.logger import get_logger
from database.models import Base, Candle, JobRun, Symbol
from schemas.market import OHLCVFrame, SymbolConfig

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, future=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Alembic yoksa/ilk calistirmada semayi olusturur."""
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.info("db.initialized", url=get_settings().database_url)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_or_create_symbol(session: AsyncSession, config: SymbolConfig) -> Symbol:
    ticker = config.yf_ticker
    result = await session.execute(select(Symbol).where(Symbol.ticker == ticker))
    symbol = result.scalar_one_or_none()
    if symbol is not None:
        return symbol

    symbol = Symbol(
        ticker=ticker,
        market=config.market.value,
        interval=config.interval.value,
        is_active=config.is_active,
    )
    session.add(symbol)
    await session.flush()
    logger.info("db.symbol_created", ticker=ticker, market=config.market.value)
    return symbol


async def upsert_candles(session: AsyncSession, frame: OHLCVFrame) -> int:
    """Mumları idempotent sekilde yazar; mevcut satirlar guncellenir (K-08)."""
    if frame.is_empty:
        return 0

    symbol = await get_or_create_symbol(session, frame.symbol)
    interval = frame.interval.value

    rows = [
        {
            "symbol_id": symbol.id,
            "ts": candle.ts,
            "interval": interval,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        for candle in frame.to_candles()
    ]

    statement = sqlite_insert(Candle).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[Candle.symbol_id, Candle.ts, Candle.interval],
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "volume": statement.excluded.volume,
        },
    )
    await session.execute(statement)
    logger.info("db.candles_upserted", ticker=symbol.ticker, rows=len(rows), interval=interval)
    return len(rows)


async def save_frames(frames: Sequence[OHLCVFrame]) -> int:
    total = 0
    async with session_scope() as session:
        for frame in frames:
            total += await upsert_candles(session, frame)
    return total


async def start_job_run(job_name: str) -> int:
    async with session_scope() as session:
        job = JobRun(job_name=job_name, started_at=datetime.now(timezone.utc), status="running")
        session.add(job)
        await session.flush()
        return job.id


async def finish_job_run(
    job_id: int,
    status: str = "success",
    items_processed: int = 0,
    error_text: str | None = None,
) -> None:
    async with session_scope() as session:
        job = await session.get(JobRun, job_id)
        if job is None:
            logger.warning("db.job_run_missing", job_id=job_id)
            return
        job.finished_at = datetime.now(timezone.utc)
        job.status = status
        job.items_processed = items_processed
        job.error_text = error_text
