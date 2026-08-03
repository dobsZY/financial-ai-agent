from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from api.routes import health
from config.settings import get_settings
from core.logger import get_logger, setup_logging
from core.scheduler import shutdown_scheduler, start_scheduler

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("app.startup", env=settings.app_env, symbols=len(settings.all_symbols))
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        logger.info("app.shutdown")


app = FastAPI(
    title="AI-Driven Financial Command Center",
    description="BIST & NASDAQ otomatik tarama, formasyon tespiti ve bildirim sistemi.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("main:app", host=settings.api_host, port=settings.api_port, reload=True)
