from __future__ import annotations

from sqlalchemy import func, select

from database import db_manager
from database.models import Candle, Symbol
from schemas.market import OHLCVFrame


async def test_upsert_candles_is_idempotent(frame: OHLCVFrame, clean_db: None) -> None:
    first = await db_manager.save_frames([frame])
    second = await db_manager.save_frames([frame])

    assert first == len(frame.df)
    assert second == len(frame.df)

    async with db_manager.session_scope() as session:
        candle_count = await session.scalar(select(func.count()).select_from(Candle))
        symbol_count = await session.scalar(select(func.count()).select_from(Symbol))

    assert candle_count == len(frame.df)
    assert symbol_count == 1


async def test_job_run_lifecycle(clean_db: None) -> None:
    job_id = await db_manager.start_job_run("intraday_scan")
    await db_manager.finish_job_run(job_id, status="success", items_processed=3)

    async with db_manager.session_scope() as session:
        from database.models import JobRun

        job = await session.get(JobRun, job_id)

    assert job is not None
    assert job.status == "success"
    assert job.items_processed == 3
    assert job.finished_at is not None
