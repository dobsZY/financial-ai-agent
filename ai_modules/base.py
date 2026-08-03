from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, TypeVar

from core.logger import get_logger
from schemas.market import OHLCVFrame
from schemas.signal import Detection

logger = get_logger(__name__)


class PatternAnalyzer(ABC):
    """Formasyon analizcisi sozlesmesi.

    Yeni bir analizci eklemek icin: bu sinifi turet, `name` tanimla,
    `@register_analyzer` ile kaydet. Mevcut dosyalar degismez (K-04).
    """

    name: str = "base"

    @abstractmethod
    async def analyze(self, frame: OHLCVFrame) -> list[Detection]:
        """Verilen OHLCV serisi icin tespit listesi dondurur."""

    @property
    def is_available(self) -> bool:
        """Analizci calisabilir durumda mi (model dosyasi, API anahtari vb.)."""
        return True


REGISTRY: dict[str, PatternAnalyzer] = {}

AnalyzerT = TypeVar("AnalyzerT", bound=PatternAnalyzer)


def register_analyzer(cls: type[AnalyzerT]) -> type[AnalyzerT]:
    instance = cls()
    if instance.name in REGISTRY:
        raise ValueError(f"Analizci adi zaten kayitli: {instance.name}")
    REGISTRY[instance.name] = instance
    logger.info("analyzer.registered", name=instance.name)
    return cls


def get_analyzer(name: str) -> PatternAnalyzer:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"Bilinmeyen analizci: {name}. Kayitli: {sorted(REGISTRY)}") from exc


def available_analyzers() -> list[PatternAnalyzer]:
    return [analyzer for analyzer in REGISTRY.values() if analyzer.is_available]


def deduplicate(detections: list[Detection]) -> list[Detection]:
    """Ayni formasyon icin en yuksek guvenli tespiti tutar."""
    best: dict[str, Detection] = {}
    for detection in detections:
        key = detection.pattern.value
        current = best.get(key)
        if current is None or detection.confidence > current.confidence:
            best[key] = detection
    return sorted(best.values(), key=lambda item: item.confidence, reverse=True)


def filter_by_confidence(detections: list[Detection], threshold: float) -> list[Detection]:
    return [detection for detection in detections if detection.confidence >= threshold]


AnalyzerFactory = Callable[[], PatternAnalyzer]
