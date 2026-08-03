# AI-Driven Financial Command Center (BIST & NASDAQ)

BIST ve NASDAQ piyasalarını asenkron tarayan, grafik formasyonlarını bilgisayarlı görü ile tespit eden,
KAP/SEC bildirimlerini LLM ile özetleyen ve mobil push bildirim gönderen finans asistanı.

- Spesifikasyon: `finance.md`
- Teknik yol haritası ve görev listesi: `ROADMAP.md`

## Teknoloji Yığını

FastAPI · APScheduler · SQLAlchemy 2.0 (async, SQLite) · yfinance · mplfinance + OpenCV ·
Ultralytics YOLO · Gemini API · Pushover / Telegram · Flet

## Kurulum

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

`.env` içindeki `GEMINI_API_KEY`, `PUSHOVER_TOKEN`, `PUSHOVER_USER` alanlarını doldurun.
Bu anahtarlar asla koda veya git'e yazılmaz.

## Veritabanı

```powershell
alembic upgrade head
```

## Çalıştırma

```powershell
uvicorn main:app --reload
```

- API dokümantasyonu: http://127.0.0.1:8000/docs
- Sağlık kontrolü: http://127.0.0.1:8000/health

## Test

```powershell
pytest
```

## Mevcut Durum

- **Faz 0** — iskelet, konfigürasyon, loglama, scheduler lifespan, `/health` ✅
- **Faz 1** — veri akış hattı: async `yfinance` çekimi, RAM-içi grafik üretimi (`BytesIO` → `ndarray`),
  RSI/EMA/MACD indikatörleri, SQLite + Alembic şeması ve idempotent mum yazımı ✅
- **Faz 2** — yapay zeka modülleri: analizci registry'si, kural tabanlı formasyon tespiti
  (double top/bottom, omuz-baş-omuz, üçgenler), YOLO analizcisi (fine-tune edilmiş model
  varsa devreye girer), KAP + SEC scraper'ları, Gemini JSON şemalı özetleme (kota + cache) ✅
- **Sıradaki:** Faz 3 — skorlama, dedup'lı bildirim ve zamanlanmış tarama

### Formasyon tespiti hakkında

Hazır YOLO ağırlıkları grafik formasyonu sınıfları içermediği için varsayılan analizci
kural tabanlıdır (`ai_modules/pattern_rules.py`). Fine-tune için:

```powershell
python training/train_vision.py --epochs 100
```

Eğitim sonrası `.env` içindeki `YOLO_MODEL_PATH` üretilen ağırlığa yönlendirilir ve
`YoloAnalyzer` otomatik olarak etkinleşir.
