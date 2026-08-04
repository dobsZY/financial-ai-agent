from __future__ import annotations

import httpx

from config.settings import get_settings
from core.logger import get_logger
from notifications.base import Notification, Notifier, register_notifier

logger = get_logger(__name__)

API_URL = "https://api.pushover.net/1/messages.json"
TIMEOUT = httpx.Timeout(15.0)
MAX_MESSAGE_CHARS = 1024


@register_notifier
class PushoverNotifier(Notifier):
    """Yedek bildirim kanali; Telegram basarisiz olursa devreye girer."""

    name = "pushover"

    @property
    def is_enabled(self) -> bool:
        return get_settings().pushover_enabled

    async def send(self, notification: Notification) -> bool:
        settings = get_settings()
        if not settings.pushover_enabled:
            logger.warning("pushover.not_configured")
            return False

        data = {
            "token": settings.pushover_token,
            "user": settings.pushover_user,
            "title": notification.title[:250],
            "message": notification.body[:MAX_MESSAGE_CHARS],
            "priority": int(notification.priority),
        }
        if notification.url:
            data["url"] = notification.url
            data["url_title"] = "Detay"

        files = (
            {"attachment": ("chart.png", notification.image_png, "image/png")}
            if notification.image_png
            else None
        )

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(API_URL, data=data, files=files)
        except httpx.HTTPError as exc:
            logger.warning("pushover.request_error", error=str(exc))
            return False

        if response.status_code != 200:
            logger.warning(
                "pushover.api_error", status=response.status_code, body=response.text[:200]
            )
            return False

        try:
            payload = response.json()
        except ValueError:
            logger.warning("pushover.invalid_json")
            return False

        if payload.get("status") != 1:
            logger.warning("pushover.api_not_ok", body=str(payload)[:200])
            return False
        return True
