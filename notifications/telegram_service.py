from __future__ import annotations

import html

import httpx

from config.settings import get_settings
from core.logger import get_logger
from notifications.base import Notification, Notifier, Priority, register_notifier

logger = get_logger(__name__)

API_BASE = "https://api.telegram.org"
TIMEOUT = httpx.Timeout(15.0)
MAX_CAPTION_CHARS = 1024
MAX_MESSAGE_CHARS = 4096


def _api_url(token: str, method: str) -> str:
    return f"{API_BASE}/bot{token}/{method}"


def _format_html(notification: Notification) -> str:
    lines = [f"<b>{html.escape(notification.title)}</b>", "", html.escape(notification.body)]
    if notification.url:
        lines.extend(["", f'<a href="{html.escape(notification.url, quote=True)}">Detay</a>'])
    return "\n".join(lines)


@register_notifier
class TelegramNotifier(Notifier):
    """Birincil bildirim kanali (kullanici tercihi)."""

    name = "telegram"

    @property
    def is_enabled(self) -> bool:
        return get_settings().telegram_enabled

    async def send(self, notification: Notification) -> bool:
        settings = get_settings()
        if not settings.telegram_enabled:
            logger.warning("telegram.not_configured")
            return False

        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        silent = notification.priority == Priority.LOW
        text = _format_html(notification)

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if notification.image_png:
                return await self._send_photo(client, token, chat_id, text, notification, silent)
            return await self._send_message(client, token, chat_id, text, silent)

    async def _send_message(
        self,
        client: httpx.AsyncClient,
        token: str,
        chat_id: str,
        text: str,
        silent: bool,
    ) -> bool:
        payload = {
            "chat_id": chat_id,
            "text": text[:MAX_MESSAGE_CHARS],
            "parse_mode": "HTML",
            "disable_notification": silent,
            "link_preview_options": {"is_disabled": True},
        }
        return await self._post(client, _api_url(token, "sendMessage"), json=payload)

    async def _send_photo(
        self,
        client: httpx.AsyncClient,
        token: str,
        chat_id: str,
        text: str,
        notification: Notification,
        silent: bool,
    ) -> bool:
        data = {
            "chat_id": chat_id,
            "caption": text[:MAX_CAPTION_CHARS],
            "parse_mode": "HTML",
            "disable_notification": str(silent).lower(),
        }
        files = {"photo": ("chart.png", notification.image_png, "image/png")}
        sent = await self._post(client, _api_url(token, "sendPhoto"), data=data, files=files)
        if sent:
            return True

        logger.warning("telegram.photo_failed_fallback_text")
        return await self._send_message(client, token, chat_id, text, silent)

    async def _post(self, client: httpx.AsyncClient, url: str, **kwargs: object) -> bool:
        try:
            response = await client.post(url, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            logger.warning("telegram.request_error", error=str(exc))
            return False

        if response.status_code != 200:
            logger.warning(
                "telegram.api_error",
                status=response.status_code,
                body=response.text[:200],
            )
            return False

        try:
            payload = response.json()
        except ValueError:
            logger.warning("telegram.invalid_json")
            return False

        if not payload.get("ok"):
            logger.warning("telegram.api_not_ok", body=str(payload)[:200])
            return False
        return True
