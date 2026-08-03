from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from ai_modules import vision_model
from ai_modules.base import get_analyzer
from schemas.signal import Pattern


class _FakeBox:
    def __init__(self, class_id: int, confidence: float, coordinates: list[float]) -> None:
        self.cls = np.array([float(class_id)])
        self.conf = np.array([confidence])
        self.xyxy = np.array([coordinates])


class _FakeResult:
    def __init__(self, boxes: list[_FakeBox]) -> None:
        self.boxes = boxes


class _FakeModel:
    def __init__(self, names: dict[int, str], boxes: list[_FakeBox]) -> None:
        self.names = names
        self._boxes = boxes
        self.predict_kwargs: dict[str, Any] = {}

    def predict(self, **kwargs: Any) -> list[_FakeResult]:
        self.predict_kwargs = kwargs
        return [_FakeResult(self._boxes)]


@pytest.fixture(autouse=True)
def _reset_model() -> None:
    vision_model._model = None
    vision_model._model_path = None


def test_pattern_class_map_skips_unknown() -> None:
    mapping = vision_model._pattern_class_map({0: "Double Top", 1: "kedi", 2: "asc-triangle"})

    assert mapping == {0: Pattern.DOUBLE_TOP, 2: Pattern.ASC_TRIANGLE}


async def test_detect_maps_boxes_to_detections(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _FakeModel(
        names={0: "double_top", 1: "kopek"},
        boxes=[
            _FakeBox(0, 0.81, [10.0, 20.0, 110.0, 120.0]),
            _FakeBox(1, 0.95, [0.0, 0.0, 5.0, 5.0]),
        ],
    )
    monkeypatch.setattr(vision_model, "load_model", lambda *_, **__: model)

    detections = await vision_model.detect(np.zeros((640, 640, 3), dtype=np.uint8), 0.5)

    assert len(detections) == 1
    detection = detections[0]
    assert detection.pattern is Pattern.DOUBLE_TOP
    assert detection.source == "yolo"
    assert detection.box is not None
    assert detection.box.x2 == 110.0
    assert model.predict_kwargs["conf"] == 0.5
    assert model.predict_kwargs["iou"] == vision_model.IOU_THRESHOLD


async def test_detect_returns_empty_without_pattern_classes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _FakeModel(names={0: "person", 1: "car"}, boxes=[_FakeBox(0, 0.99, [1, 2, 3, 4])])
    monkeypatch.setattr(vision_model, "load_model", lambda *_, **__: model)

    detections = await vision_model.detect(np.zeros((64, 64, 3), dtype=np.uint8))

    assert detections == []


def test_analyzer_unavailable_without_model_file() -> None:
    assert get_analyzer("yolo").is_available is False


def test_has_pattern_classes_false_when_file_missing() -> None:
    assert vision_model.has_pattern_classes() is False
