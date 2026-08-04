from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import numpy as np

from ai_modules.base import PatternAnalyzer, deduplicate, register_analyzer
from config.settings import get_settings
from core.chart_factory import render_chart
from core.logger import get_logger
from schemas.market import OHLCVFrame
from schemas.signal import BoundingBox, Detection, Pattern

logger = get_logger(__name__)

IOU_THRESHOLD = 0.45
MAX_DETECTIONS = 10
SOURCE = "yolo"

_model: Any | None = None
_model_path: Path | None = None


def model_path() -> Path:
    return Path(get_settings().yolo_model_path)


def metrics_path() -> Path:
    """Egitim sonrasi yazilan model kayit dosyasi (5.5)."""
    return model_path().parent / "model_metrics.json"


def model_info(load: bool = False) -> dict[str, Any]:
    """Aktif model dosyasi + egitim metrikleri. `load=False` iken model yuklenmez."""
    path = model_path()
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_mb": round(path.stat().st_size / 1_048_576, 2) if path.exists() else None,
        "registry": None,
        "classes": None,
        "pattern_classes": None,
    }

    registry_file = metrics_path()
    if registry_file.exists():
        try:
            info["registry"] = json.loads(registry_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logger.warning("yolo.metrics_unreadable", error=str(exc))

    model = _model if not load else (load_model() if path.exists() else None)
    if model is not None:
        names = getattr(model, "names", {}) or {}
        info["classes"] = list(names.values()) if isinstance(names, dict) else list(names)
        info["pattern_classes"] = bool(_pattern_class_map(names))

    return info


def _pattern_class_map(names: dict[int, str] | list[str]) -> dict[int, Pattern]:
    """Model sinif adlarini Pattern enum'una eslestirir; tanimsiz siniflar atlanir."""
    items = names.items() if isinstance(names, dict) else enumerate(names)
    mapping: dict[int, Pattern] = {}
    for class_id, raw_name in items:
        candidate = str(raw_name).strip().lower().replace(" ", "_").replace("-", "_")
        try:
            mapping[int(class_id)] = Pattern(candidate)
        except ValueError:
            continue
    return mapping


def load_model(force: bool = False) -> Any:
    """Ultralytics modelini tek sefer yukler (lazy singleton)."""
    global _model, _model_path
    path = model_path()
    if _model is not None and not force and _model_path == path:
        return _model

    from ultralytics import YOLO  # yerel import: uygulama acilisini yavaslatmamak icin

    _model = YOLO(str(path))
    _model_path = path
    logger.info("yolo.loaded", path=str(path), classes=len(getattr(_model, "names", {}) or {}))
    return _model


def has_pattern_classes() -> bool:
    """Model formasyon siniflari icin fine-tune edilmis mi?"""
    if not model_path().exists():
        return False
    try:
        model = load_model()
    except Exception as exc:  # noqa: BLE001 - model dosyasi bozuk/eksik olabilir
        logger.warning("yolo.load_failed", error=str(exc))
        return False
    return bool(_pattern_class_map(getattr(model, "names", {}) or {}))


def _predict(frame_array: np.ndarray, min_confidence: float) -> list[Detection]:
    """Bloklayan inference. Sadece to_thread icinden cagrilmalidir (K-01)."""
    model = load_model()
    class_map = _pattern_class_map(getattr(model, "names", {}) or {})
    if not class_map:
        return []

    results = model.predict(
        source=frame_array,
        conf=min_confidence,
        iou=IOU_THRESHOLD,
        max_det=MAX_DETECTIONS,
        verbose=False,
    )

    detections: list[Detection] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        for box in boxes:
            class_id = int(box.cls.item())
            pattern = class_map.get(class_id)
            if pattern is None:
                continue
            coordinates = box.xyxy.flatten().tolist()
            detections.append(
                Detection(
                    pattern=pattern,
                    confidence=float(box.conf.item()),
                    source=SOURCE,
                    box=BoundingBox(
                        x1=coordinates[0],
                        y1=coordinates[1],
                        x2=coordinates[2],
                        y2=coordinates[3],
                    ),
                )
            )
    return deduplicate(detections)


async def detect(frame_array: np.ndarray, min_confidence: float | None = None) -> list[Detection]:
    threshold = min_confidence if min_confidence is not None else get_settings().min_confidence
    return await asyncio.to_thread(_predict, frame_array, threshold)


@register_analyzer
class YoloAnalyzer(PatternAnalyzer):
    """Grafik goruntusu uzerinden formasyon tespiti.

    Yalnizca `YOLO_MODEL_PATH` formasyon siniflarina sahipse devreye girer;
    aksi halde `is_available` False doner ve pipeline kural tabanli analizciyi kullanir.
    """

    name = "yolo"

    @property
    def is_available(self) -> bool:
        return has_pattern_classes()

    async def analyze(self, frame: OHLCVFrame) -> list[Detection]:
        array = await render_chart(frame)
        detections = await detect(array)
        if detections:
            logger.info(
                "yolo.detected",
                ticker=frame.symbol.yf_ticker,
                patterns=[item.pattern.value for item in detections],
            )
        return detections
