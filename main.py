from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.routes import charts, health, news, patterns, signals, symbols
from config.settings import get_settings
from core.logger import get_logger, setup_logging
from core.scheduler import shutdown_scheduler, start_scheduler
from database.db_manager import dispose_engine, init_db

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("app.startup", env=settings.app_env, symbols=len(settings.all_symbols))
    await init_db()
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        await dispose_engine()
        logger.info("app.shutdown")


app = FastAPI(
    title="AI-Driven Financial Command Center",
    description="BIST & NASDAQ otomatik tarama, formasyon tespiti ve bildirim sistemi.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(signals.router)
app.include_router(symbols.router)
app.include_router(news.router)
app.include_router(charts.router)
app.include_router(patterns.router)

# Web paneli ayni process'ten servis edilir: tek komut, CORS yok, ayni Docker imaji.
WEB_DIR = Path(__file__).resolve().parent / "web"
if WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/app/" if WEB_DIR.is_dir() else "/docs")


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("main:app", host=settings.api_host, port=settings.api_port, reload=True)
