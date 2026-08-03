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
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from schemas.signal import PATTERN_CLASS_NAMES  # noqa: E402

DEFAULT_DATA = BASE_DIR / "training" / "data.yaml"
OUTPUT_MODEL = BASE_DIR / "models" / "yolov8_patterns_v1.pt"


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
    if best.exists():
        OUTPUT_MODEL.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, OUTPUT_MODEL)
        print(f"Model kaydedildi: {OUTPUT_MODEL}")
        print("`.env` icinde YOLO_MODEL_PATH=models/yolov8_patterns_v1.pt olarak guncelleyin.")
    else:
        print("Uyari: best.pt bulunamadi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
