"""YOLO formasyon modeli fine-tune betigi (ROADMAP 2.4).

Uygulamadan bagimsiz, elle calistirilir:

    python training/train_vision.py --epochs 100 --imgsz 640

Egitim sonunda en iyi agirlik `models/yolov8_patterns_v1.pt` olarak kopyalanir ve
`.env` icindeki YOLO_MODEL_PATH bu dosyaya yonlendirilir. Sinif adlari
`schemas.signal.Pattern` degerleriyle bire bir ayni olmalidir; aksi halde
`ai_modules.vision_model` tespitleri atlar.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from schemas.signal import PATTERN_CLASS_NAMES  # noqa: E402

DEFAULT_DATA = BASE_DIR / "training" / "data.yaml"
MODELS_DIR = BASE_DIR / "models"
MODEL_STEM = "yolov8_patterns_v"
METRICS_FILE = MODELS_DIR / "model_metrics.json"


def next_version() -> int:
    """Mevcut `yolov8_patterns_vN.pt` dosyalarina bakip bir sonraki surumu verir (5.5)."""
    versions = []
    for path in MODELS_DIR.glob(f"{MODEL_STEM}*.pt"):
        suffix = path.stem.removeprefix(MODEL_STEM)
        if suffix.isdigit():
            versions.append(int(suffix))
    return max(versions, default=0) + 1


def extract_metrics(results: object) -> dict[str, float]:
    """Ultralytics sonucundan performans metriklerini cikarir (surum farklarina dayanikli)."""
    box = getattr(getattr(results, "box", None), "__dict__", {})
    candidates = {
        "mAP50": ("map50",),
        "mAP50-95": ("map",),
        "precision": ("mp",),
        "recall": ("mr",),
    }
    metrics: dict[str, float] = {}
    for label, keys in candidates.items():
        for key in keys:
            value = box.get(key, getattr(getattr(results, "box", None), key, None))
            if isinstance(value, (int, float)):
                metrics[label] = round(float(value), 4)
                break
    return metrics


def write_registry(model_path: Path, version: int, args: argparse.Namespace, results: object) -> None:
    """Model kaydi: surum, egitim parametreleri ve metrikler (5.5)."""
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version,
        "path": model_path.relative_to(BASE_DIR).as_posix(),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_model": args.base_model,
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "dataset": Path(args.data).relative_to(BASE_DIR).as_posix(),
        "classes": list(PATTERN_CLASS_NAMES),
        "metrics": extract_metrics(results),
    }
    METRICS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Model kaydi yazildi: {METRICS_FILE}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YOLO formasyon modeli egitimi")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--base-model", type=str, default="yolov8n.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", type=str, default="cpu")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.data.exists():
        print(f"Veri seti tanimi bulunamadi: {args.data}")
        return 1

    from ultralytics import YOLO

    print(f"Beklenen sinif adlari: {', '.join(PATTERN_CLASS_NAMES)}")

    model = YOLO(args.base_model)
    results = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(BASE_DIR / "training" / "runs"),
        name="patterns",
        exist_ok=True,
    )

    best = Path(results.save_dir) / "weights" / "best.pt"
    if not best.exists():
        print("Uyari: best.pt bulunamadi")
        return 1

    version = next_version()
    output_model = MODELS_DIR / f"{MODEL_STEM}{version}.pt"
    output_model.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, output_model)

    metrics = model.val(data=str(args.data), device=args.device, verbose=False)
    write_registry(output_model, version, args, metrics)

    print(f"Model kaydedildi: {output_model}")
    print(f"`.env` icinde YOLO_MODEL_PATH={output_model.relative_to(BASE_DIR).as_posix()} yapin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
