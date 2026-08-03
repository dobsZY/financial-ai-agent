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

Faz 0 (iskelet, konfigürasyon, loglama, scheduler lifespan, `/health`) tamamlandı.
Sıradaki adımlar için `ROADMAP.md` içindeki görev listesine bakın.
