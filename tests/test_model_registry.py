from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ai_modules import vision_model
from main import app
from schemas.signal import PATTERN_CLASS_NAMES

REGISTRY_SAMPLE = {
    "version": 3,
    "path": "models/yolov8_patterns_v3.pt",
    "trained_at": "2026-08-04T10:00:00+00:00",
    "epochs": 100,
    "classes": list(PATTERN_CLASS_NAMES),
    "metrics": {"mAP50": 0.71, "mAP50-95": 0.44},
}


@pytest.fixture
def model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    weights = tmp_path / "yolov8_patterns_v3.pt"
    weights.write_bytes(b"0" * 2048)
    monkeypatch.setattr(vision_model, "model_path", lambda: weights)
    return tmp_path


def test_model_info_reports_missing_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vision_model, "model_path", lambda: tmp_path / "yok.pt")

    info = vision_model.model_info()

    assert info["exists"] is False
    assert info["size_mb"] is None
    assert info["registry"] is None


def test_model_info_reads_registry(model_dir: Path) -> None:
    (model_dir / "model_metrics.json").write_text(
        json.dumps(REGISTRY_SAMPLE), encoding="utf-8"
    )

    info = vision_model.model_info()

    assert info["exists"] is True
    assert info["registry"]["version"] == 3
    assert info["registry"]["metrics"]["mAP50"] == 0.71


def test_model_info_survives_corrupt_registry(model_dir: Path) -> None:
    (model_dir / "model_metrics.json").write_text("{bozuk json", encoding="utf-8")

    info = vision_model.model_info()

    assert info["exists"] is True
    assert info["registry"] is None, "Bozuk kayit dosyasi uygulamayi dusurmemeli"


def test_model_info_does_not_load_weights(model_dir: Path) -> None:
    """load=False iken agirliklar yuklenmez (ac ilis/health hizli kalmali)."""
    info = vision_model.model_info(load=False)

    assert info["classes"] is None
    assert info["pattern_classes"] is None


async def test_system_model_endpoint(model_dir: Path) -> None:
    (model_dir / "model_metrics.json").write_text(
        json.dumps(REGISTRY_SAMPLE), encoding="utf-8"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/system/model")

    assert response.status_code == 200
    assert response.json()["registry"]["version"] == 3


def test_next_version_increments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import training.train_vision as train_vision

    monkeypatch.setattr(train_vision, "MODELS_DIR", tmp_path)
    assert train_vision.next_version() == 1

    (tmp_path / "yolov8_patterns_v1.pt").write_bytes(b"x")
    (tmp_path / "yolov8_patterns_v7.pt").write_bytes(b"x")
    (tmp_path / "yolov8_patterns_vabc.pt").write_bytes(b"x")

    assert train_vision.next_version() == 8, "Sayisal olmayan surumler atlanmali"


def test_extract_metrics_handles_missing_fields() -> None:
    import training.train_vision as train_vision

    class _Box:
        map50 = 0.66
        map = 0.4

    class _Results:
        box = _Box()

    metrics = train_vision.extract_metrics(_Results())

    assert metrics["mAP50"] == 0.66
    assert metrics["mAP50-95"] == 0.4
    assert "precision" not in metrics

    assert train_vision.extract_metrics(object()) == {}
