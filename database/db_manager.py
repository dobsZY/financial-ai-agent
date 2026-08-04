from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import get_settings
from core.logger import get_logger
from database.models import Base, Candle, JobRun, LLMSummary, NewsItem, Signal, Symbol
from schemas.market import OHLCV_COLUMNS, Interval, OHLCVFrame, SymbolConfig
from schemas.news import LLMSummary as LLMSummarySchema
from schemas.news import NewsItem as NewsItemSchema
from schemas.signal import SignalCandidate

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


async def find_recent_signal(
    session: AsyncSession,
    symbol_id: int,
    pattern: str,
    bucket_ts: datetime,
    cutoff: datetime,
) -> Signal | None:
    """Ayni kova veya cooldown penceresi icinde sinyal var mi (3.6)."""
    statement = (
        select(Signal)
        .where(Signal.symbol_id == symbol_id)
        .where(Signal.pattern == pattern)
        .where(or_(Signal.bucket_ts == bucket_ts, Signal.created_at >= cutoff))
        .order_by(Signal.created_at.desc())
        .limit(1)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def save_signal(
    session: AsyncSession,
    candidate: SignalCandidate,
    cutoff: datetime,
    notified: bool = False,
) -> Signal | None:
    """Sinyali yazar; dedup/cooldown ihlalinde None doner ve hicbir sey yazilmaz."""
    symbol_config = SymbolConfig.from_ticker(candidate.ticker, interval=Interval(candidate.interval))
    symbol = await get_or_create_symbol(session, symbol_config)

    existing = await find_recent_signal(
        session, symbol.id, candidate.pattern.value, candidate.bucket_ts, cutoff
    )
    if existing is not None:
        logger.info(
            "db.signal_deduplicated",
            ticker=candidate.ticker,
            pattern=candidate.pattern.value,
            existing_id=existing.id,
        )
        return None

    signal = Signal(
        symbol_id=symbol.id,
        pattern=candidate.pattern.value,
        direction=candidate.direction.value,
        confidence=candidate.detection.confidence,
        final_score=candidate.final_score,
        price_at_signal=candidate.price,
        bucket_ts=candidate.bucket_ts,
        chart_hash=candidate.chart_hash,
        notified_at=datetime.now(timezone.utc) if notified else None,
    )
    session.add(signal)
    await session.flush()
    logger.info(
        "db.signal_saved",
        ticker=candidate.ticker,
        pattern=candidate.pattern.value,
        score=candidate.final_score,
        signal_id=signal.id,
    )
    return signal


async def mark_notified(session: AsyncSession, signal_id: int) -> None:
    signal = await session.get(Signal, signal_id)
    if signal is not None:
        signal.notified_at = datetime.now(timezone.utc)


async def list_signals(
    limit: int = 50,
    ticker: str | None = None,
    min_score: float | None = None,
) -> list[tuple[Signal, str]]:
    """(Signal, ticker) ciftleri; en yeni once."""
    async with session_scope() as session:
        statement = (
            select(Signal, Symbol.ticker)
            .join(Symbol, Signal.symbol_id == Symbol.id)
            .order_by(Signal.created_at.desc())
            .limit(limit)
        )
        if ticker:
            statement = statement.where(Symbol.ticker == ticker.strip().upper())
        if min_score is not None:
            statement = statement.where(Signal.final_score >= min_score)
        result = await session.execute(statement)
        return [(row[0], row[1]) for row in result.all()]


async def get_signal(signal_id: int) -> tuple[Signal, str] | None:
    async with session_scope() as session:
        statement = (
            select(Signal, Symbol.ticker)
            .join(Symbol, Signal.symbol_id == Symbol.id)
            .where(Signal.id == signal_id)
        )
        row = (await session.execute(statement)).first()
        return (row[0], row[1]) if row is not None else None


async def signals_for_backtest(
    limit: int = 500,
    min_score: float | None = None,
    pattern: str | None = None,
) -> list[tuple[Signal, str, str]]:
    """(Signal, ticker, interval) uclusu; backtest icin en eski once."""
    async with session_scope() as session:
        statement = (
            select(Signal, Symbol.ticker, Symbol.interval)
            .join(Symbol, Signal.symbol_id == Symbol.id)
            .order_by(Signal.bucket_ts.asc())
            .limit(limit)
        )
        if min_score is not None:
            statement = statement.where(Signal.final_score >= min_score)
        if pattern:
            statement = statement.where(Signal.pattern == pattern)
        result = await session.execute(statement)
        return [(row[0], row[1], row[2]) for row in result.all()]


async def list_symbols(active_only: bool = False) -> list[Symbol]:
    async with session_scope() as session:
        statement = select(Symbol).order_by(Symbol.ticker)
        if active_only:
            statement = statement.where(Symbol.is_active.is_(True))
        result = await session.execute(statement)
        return list(result.scalars().all())


async def add_symbol(
    ticker: str,
    interval: Interval = Interval.H1,
    name: str | None = None,
) -> Symbol:
    """Izleme listesine ekler; zaten varsa mevcut kaydi doner (idempotent)."""
    config = SymbolConfig.from_ticker(ticker, interval=interval)
    async with session_scope() as session:
        symbol = await get_or_create_symbol(session, config)
        if name is not None:
            symbol.name = name
        return symbol


async def update_symbol(
    ticker: str,
    is_active: bool | None = None,
    interval: Interval | None = None,
    name: str | None = None,
) -> Symbol | None:
    normalized = SymbolConfig.from_ticker(ticker).yf_ticker
    async with session_scope() as session:
        result = await session.execute(select(Symbol).where(Symbol.ticker == normalized))
        symbol = result.scalar_one_or_none()
        if symbol is None:
            return None
        if is_active is not None:
            symbol.is_active = is_active
        if interval is not None:
            symbol.interval = interval.value
        if name is not None:
            symbol.name = name
        await session.flush()
        logger.info("db.symbol_updated", ticker=normalized, is_active=symbol.is_active)
        return symbol


async def delete_symbol(ticker: str) -> bool:
    """Sembolu ve bagli mum/sinyallerini siler (cascade)."""
    normalized = SymbolConfig.from_ticker(ticker).yf_ticker
    async with session_scope() as session:
        result = await session.execute(select(Symbol).where(Symbol.ticker == normalized))
        symbol = result.scalar_one_or_none()
        if symbol is None:
            return False
        await session.delete(symbol)
        logger.info("db.symbol_deleted", ticker=normalized)
        return True


async def list_job_runs(limit: int = 20, job_name: str | None = None) -> list[JobRun]:
    async with session_scope() as session:
        statement = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
        if job_name:
            statement = statement.where(JobRun.job_name == job_name)
        result = await session.execute(statement)
        return list(result.scalars().all())


async def save_news_item(
    session: AsyncSession,
    item: NewsItemSchema,
    summary: LLMSummarySchema | None = None,
) -> NewsItem | None:
    """Haberi idempotent yazar; zaten varsa None doner (tekrar LLM cagrisi onlenir)."""
    existing = await session.execute(
        select(NewsItem)
        .where(NewsItem.source == item.source.value)
        .where(NewsItem.external_id == item.external_id)
    )
    if existing.scalar_one_or_none() is not None:
        return None

    symbol_id: int | None = None
    if item.ticker:
        config = SymbolConfig.from_ticker(item.ticker)
        symbol = await get_or_create_symbol(session, config)
        symbol_id = symbol.id

    news = NewsItem(
        symbol_id=symbol_id,
        source=item.source.value,
        external_id=item.external_id,
        title=item.title[:512],
        url=item.url,
        published_at=item.published_at,
        raw_text=item.raw_text,
    )
    session.add(news)
    await session.flush()

    if summary is not None:
        session.add(
            LLMSummary(
                news_id=news.id,
                sentiment=summary.sentiment,
                bullets_json=json.dumps(summary.bullets, ensure_ascii=False),
                risk_level=summary.risk_level.value,
                model=summary.model,
                tokens=summary.tokens,
            )
        )
        await session.flush()

    logger.info("db.news_saved", source=item.source.value, external_id=item.external_id)
    return news


async def load_frame(
    ticker: str,
    interval: Interval = Interval.H1,
    limit: int = 200,
) -> OHLCVFrame | None:
    """Kaydedilmis mumlardan OHLCVFrame kurar (UI grafigi icin; yeniden cekim yok)."""
    config = SymbolConfig.from_ticker(ticker, interval=interval)

    async with session_scope() as session:
        statement = (
            select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
            .join(Symbol, Candle.symbol_id == Symbol.id)
            .where(Symbol.ticker == config.yf_ticker)
            .where(Candle.interval == interval.value)
            .order_by(Candle.ts.desc())
            .limit(limit)
        )
        rows = (await session.execute(statement)).all()

    if not rows:
        return None

    frame = pd.DataFrame(
        [row[1:] for row in reversed(rows)],
        columns=list(OHLCV_COLUMNS),
        index=pd.DatetimeIndex(
            [row[0] for row in reversed(rows)], name="ts"
        ).tz_localize(timezone.utc, ambiguous="raise", nonexistent="raise"),
    )
    return OHLCVFrame(symbol=config, df=frame)


async def list_news(
    limit: int = 50,
    ticker: str | None = None,
    source: str | None = None,
) -> list[tuple[NewsItem, str | None, LLMSummary | None]]:
    """(haber, sembol kodu, LLM ozeti) uclusu; en yeni once."""
    async with session_scope() as session:
        statement = (
            select(NewsItem, Symbol.ticker, LLMSummary)
            .outerjoin(Symbol, NewsItem.symbol_id == Symbol.id)
            .outerjoin(LLMSummary, LLMSummary.news_id == NewsItem.id)
            .order_by(NewsItem.created_at.desc())
            .limit(limit)
        )
        if ticker:
            statement = statement.where(Symbol.ticker == ticker.strip().upper())
        if source:
            statement = statement.where(NewsItem.source == source.strip().upper())
        result = await session.execute(statement)
        return [(row[0], row[1], row[2]) for row in result.all()]


async def attach_summary(
    session: AsyncSession,
    news_id: int,
    summary: LLMSummarySchema,
) -> LLMSummary | None:
    """Kaydedilmis habere LLM ozetini baglar; ozet zaten varsa uzerine yazar."""
    news = await session.get(NewsItem, news_id)
    if news is None:
        logger.warning("db.news_missing_for_summary", news_id=news_id)
        return None

    existing = await session.execute(
        select(LLMSummary).where(LLMSummary.news_id == news_id)
    )
    row = existing.scalar_one_or_none()
    bullets_json = json.dumps(summary.bullets, ensure_ascii=False)

    if row is not None:
        row.sentiment = summary.sentiment
        row.bullets_json = bullets_json
        row.risk_level = summary.risk_level.value
        row.model = summary.model
        row.tokens = summary.tokens
        await session.flush()
        return row

    record = LLMSummary(
        news_id=news_id,
        sentiment=summary.sentiment,
        bullets_json=bullets_json,
        risk_level=summary.risk_level.value,
        model=summary.model,
        tokens=summary.tokens,
    )
    session.add(record)
    await session.flush()
    logger.info("db.summary_attached", news_id=news_id, sentiment=summary.sentiment)
    return record


async def recent_sentiment(ticker: str, hours: int | None = None) -> float:
    """Sembol icin son N saatteki ortalama haber duyarliligi (skorlama girdisi)."""
    window_hours = hours if hours is not None else get_settings().sentiment_lookback_hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    normalized = ticker.strip().upper()

    async with session_scope() as session:
        statement = (
            select(func.avg(LLMSummary.sentiment))
            .join(NewsItem, LLMSummary.news_id == NewsItem.id)
            .join(Symbol, NewsItem.symbol_id == Symbol.id)
            .where(Symbol.ticker == normalized)
            .where(NewsItem.created_at >= cutoff)
        )
        value = await session.scalar(statement)

    return float(value) if value is not None else 0.0


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
