from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum

from pydantic import BaseModel, ConfigDict

from config.settings import get_settings
from core.logger import get_logger

logger = get_logger(__name__)


class Priority(IntEnum):
    LOW = -1
    NORMAL = 0
    HIGH = 1


class Notification(BaseModel):
    """Kanaldan bagimsiz bildirim govdesi."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    title: str
    body: str
    url: str | None = None
    priority: Priority = Priority.NORMAL
    image_png: bytes | None = None

    @property
    def plain_text(self) -> str:
        parts = [self.title, "", self.body]
        if self.url:
            parts.extend(["", self.url])
        return "\n".join(parts)


class Notifier(ABC):
    """Bildirim kanali sozlesmesi. Yeni kanal eklemek icin turet ve kaydet."""

    name: str = "base"

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """Kanal icin gerekli anahtarlar tanimli mi."""

    @abstractmethod
    async def send(self, notification: Notification) -> bool:
        """Basarili gonderimde True doner; istisna firlatmaz."""


REGISTRY: dict[str, Notifier] = {}


def register_notifier(cls: type[Notifier]) -> type[Notifier]:
    instance = cls()
    if instance.name in REGISTRY:
        raise ValueError(f"Bildirim kanali zaten kayitli: {instance.name}")
    REGISTRY[instance.name] = instance
    return cls


def ordered_notifiers() -> list[Notifier]:
    """`NOTIFY_CHANNEL_ORDER` sirasina gore etkin kanallar."""
    channels = get_settings().notify_channels
    ordered = [REGISTRY[name] for name in channels if name in REGISTRY]
    extras = [notifier for key, notifier in REGISTRY.items() if key not in channels]
    return [notifier for notifier in [*ordered, *extras] if notifier.is_enabled]


async def notify(notification: Notification, fan_out: bool = False) -> list[str]:
    """Bildirimi gonderir.

    `fan_out=False` (varsayilan): ilk basarili kanalda durur, yani birincil kanal
    calisirsa yedek kanala ayni bildirim dusmez (K-09 tek bildirim kurali).
    `fan_out=True`: tum etkin kanallara gonderir (kritik hata uyarilari icin).
    """
    notifiers = ordered_notifiers()
    if not notifiers:
        logger.warning("notify.no_channel_configured", title=notification.title)
        return []

    delivered: list[str] = []
    for notifier in notifiers:
        try:
            success = await notifier.send(notification)
        except Exception as exc:  # noqa: BLE001 - kanal hatasi akisi durdurmaz
            logger.warning("notify.channel_error", channel=notifier.name, error=str(exc))
            continue

        if success:
            delivered.append(notifier.name)
            if not fan_out:
                break
        else:
            logger.warning("notify.channel_failed", channel=notifier.name)

    if delivered:
        logger.info("notify.delivered", channels=delivered, title=notification.title)
    else:
        logger.warning("notify.all_channels_failed", title=notification.title)
    return delivered
