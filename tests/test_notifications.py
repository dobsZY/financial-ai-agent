from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

from config.settings import Settings, get_settings
from notifications import base, push_service, telegram_service
from notifications.base import Notification, Notifier, Priority
from notifications.push_service import PushoverNotifier
from notifications.telegram_service import TelegramNotifier

TELEGRAM_MESSAGE = "https://api.telegram.org/bot%s/sendMessage"
TELEGRAM_PHOTO = "https://api.telegram.org/bot%s/sendPhoto"


@pytest.fixture
def configured_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Her iki kanali da etkin kilan ayar seti."""
    settings = get_settings().model_copy(
        update={
            "telegram_bot_token": "TOKEN",
            "telegram_chat_id": "12345",
            "pushover_token": "PTOKEN",
            "pushover_user": "PUSER",
        }
    )
    for module in (base, push_service, telegram_service):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    yield settings


@pytest.fixture
def notification() -> Notification:
    return Notification(title="Test", body="Govde", priority=Priority.NORMAL)


class _FakeNotifier(Notifier):
    def __init__(self, name: str, enabled: bool = True, succeed: bool = True) -> None:
        self.name = name
        self._enabled = enabled
        self._succeed = succeed
        self.calls = 0

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def send(self, notification: Notification) -> bool:
        self.calls += 1
        return self._succeed


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, _FakeNotifier]:
    registry = {
        "telegram": _FakeNotifier("telegram"),
        "pushover": _FakeNotifier("pushover"),
    }
    monkeypatch.setattr(base, "REGISTRY", registry)
    return registry


async def test_primary_success_skips_backup(
    fake_registry: dict[str, _FakeNotifier], notification: Notification
) -> None:
    delivered = await base.notify(notification)

    assert delivered == ["telegram"]
    assert fake_registry["pushover"].calls == 0


async def test_backup_takes_over_when_primary_fails(
    fake_registry: dict[str, _FakeNotifier], notification: Notification
) -> None:
    fake_registry["telegram"]._succeed = False

    delivered = await base.notify(notification)

    assert delivered == ["pushover"]


async def test_channel_exception_does_not_break_fan_out(
    fake_registry: dict[str, _FakeNotifier],
    notification: Notification,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(notification: Notification) -> bool:
        raise RuntimeError("kanal coktu")

    monkeypatch.setattr(fake_registry["telegram"], "send", boom)

    delivered = await base.notify(notification, fan_out=True)

    assert delivered == ["pushover"]


async def test_fan_out_hits_every_channel(
    fake_registry: dict[str, _FakeNotifier], notification: Notification
) -> None:
    delivered = await base.notify(notification, fan_out=True)

    assert delivered == ["telegram", "pushover"]


async def test_disabled_channels_are_skipped(
    fake_registry: dict[str, _FakeNotifier], notification: Notification
) -> None:
    for notifier in fake_registry.values():
        notifier._enabled = False

    assert await base.notify(notification) == []


async def test_telegram_sends_html_message(
    configured_settings: Settings, notification: Notification
) -> None:
    url = TELEGRAM_MESSAGE % configured_settings.telegram_bot_token
    with respx.mock:
        route = respx.post(url).mock(return_value=httpx.Response(200, json={"ok": True}))
        assert await TelegramNotifier().send(notification) is True

    payload = route.calls[0].request.content.decode()
    assert "<b>Test</b>" in payload
    assert configured_settings.telegram_chat_id in payload


async def test_telegram_falls_back_to_text_when_photo_fails(
    configured_settings: Settings,
) -> None:
    token = configured_settings.telegram_bot_token
    with_image = Notification(title="Test", body="Govde", image_png=b"\x89PNG")

    with respx.mock:
        photo = respx.post(TELEGRAM_PHOTO % token).mock(return_value=httpx.Response(400))
        message = respx.post(TELEGRAM_MESSAGE % token).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        assert await TelegramNotifier().send(with_image) is True

    assert photo.called and message.called


async def test_telegram_returns_false_on_api_error(
    configured_settings: Settings, notification: Notification
) -> None:
    with respx.mock:
        respx.post(TELEGRAM_MESSAGE % configured_settings.telegram_bot_token).mock(
            return_value=httpx.Response(200, json={"ok": False, "description": "chat not found"})
        )
        assert await TelegramNotifier().send(notification) is False


async def test_pushover_posts_credentials(
    configured_settings: Settings, notification: Notification
) -> None:
    with respx.mock:
        route = respx.post(push_service.API_URL).mock(
            return_value=httpx.Response(200, json={"status": 1})
        )
        assert await PushoverNotifier().send(notification) is True

    body = route.calls[0].request.content.decode()
    assert configured_settings.pushover_token in body


async def test_pushover_handles_network_error(
    configured_settings: Settings, notification: Notification
) -> None:
    with respx.mock:
        respx.post(push_service.API_URL).mock(side_effect=httpx.ConnectError("ag hatasi"))
        assert await PushoverNotifier().send(notification) is False


async def test_unconfigured_channel_does_not_call_api(
    monkeypatch: pytest.MonkeyPatch, notification: Notification
) -> None:
    """Anahtar yoksa hicbir ag cagrisi yapilmaz, sadece False doner (K-03)."""
    blank = get_settings().model_copy(update={"telegram_bot_token": "", "telegram_chat_id": ""})
    monkeypatch.setattr(telegram_service, "get_settings", lambda: blank)

    with respx.mock:  # kayitsiz istek olursa respx hata firlatir
        assert await TelegramNotifier().send(notification) is False
