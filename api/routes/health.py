from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ai_modules.vision_model import model_info
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


@router.get("/system/model")
async def vision_model() -> dict[str, object]:
    """Aktif YOLO modelinin surumu ve egitim metrikleri (5.5).

    `load=false`: model dosyasi diske dokunmadan raporlanir; agirliklari yuklemez.
    """
    return model_info(load=False)
