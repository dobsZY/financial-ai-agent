from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from config.settings import get_settings
from core.scheduler import get_scheduler

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    scheduler = get_scheduler()
    return {
        "status": "ok",
        "env": settings.app_env,
        "time": datetime.now(timezone.utc).isoformat(),
        "scheduler_running": scheduler.running,
        "jobs": len(scheduler.get_jobs()) if scheduler.running else 0,
        "watchlist_size": len(settings.all_symbols),
        "integrations": {
            "gemini": bool(settings.gemini_api_key),
            "pushover": settings.pushover_enabled,
            "telegram": settings.telegram_enabled,
        },
    }
