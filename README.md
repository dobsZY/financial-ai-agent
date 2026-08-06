# AI-Driven Financial Command Center (BIST & NASDAQ)

BIST ve NASDAQ piyasalarını asenkron tarayan, grafik formasyonlarını tespit eden,
KAP/SEC bildirimlerini LLM ile özetleyen ve mobil bildirim gönderen finans asistanı.

> ⚠️ Bu bir **araştırma ve otomasyon aracıdır**, yatırım tavsiyesi değildir. Üretilen sinyaller
> geçmiş fiyat hareketlerinden çıkarılan istatistiksel ipuçlarıdır; alım-satım kararı kullanıcıya aittir.

## Mimari

```
                    ┌──────────────────────────────────────────────┐

   APScheduler ───► │  core/pipeline.py — run_scan()               │
   (seans takvimi)  │                                              │
                    │  fetch ──► chart ──► analiz ──► skor ──► DB   │
                    └───┬─────────┬──────────┬──────────┬──────────┘
                        │         │          │          │
              yfinance ─┘         │          │          └─► notifications/
            (async wrapper)       │          │              Telegram → Pushover
                                  │          │
                    mplfinance ───┘          ├── ai_modules/pattern_rules.py  (kural tabanlı)
                    BytesIO→ndarray          ├── ai_modules/vision_model.py   (YOLO, opsiyonel)
                    (diske yazmaz)           └── ai_modules/text_model.py     (Gemini + RAG)
                                                      ▲
                                             scrapers/ (KAP · SEC)

   SQLite ◄── database/ (symbols, candles, signals, news_items, llm_summaries, job_runs)
      ▲
      └── FastAPI (api/routes) ──► web/ paneli (/app altında statik servis edilir)
                                   UI yalnızca API'yi tüketir; iş mantığı taşımaz
```

**Teknoloji:** FastAPI · APScheduler · SQLAlchemy 2.0 (async, SQLite) · yfinance ·
mplfinance + OpenCV · Ultralytics YOLO · Gemini · Telegram/Pushover · Flet

## Kurulum

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
alembic upgrade head
```

### `.env` doldurma

| Değişken | Zorunlu mu | Açıklama |
|---|---|---|
| `BIST_SYMBOLS`, `NASDAQ_SYMBOLS` | ✅ | Virgülle ayrılmış izleme listesi (`THYAO.IS,ASELS.IS` / `AAPL,NVDA`) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Bildirim için | [@BotFather](https://t.me/BotFather) ile bot açın, bota `/start` yazın |
| `PUSHOVER_TOKEN`, `PUSHOVER_USER` | Opsiyonel | Yedek bildirim kanalı |
| `GEMINI_API_KEY` | Haber özeti için | Boşsa özetleme atlanır, akış düşmez |
| `GEMINI_MODEL` | — | Varsayılan `gemini-3.6-flash`. Kullanılabilir modeller anahtara göre değişir; eski `gemini-2.5-*` yeni projelere kapalı olabilir |
| `LLM_MAX_OUTPUT_TOKENS` | — | Gemini 3.x düşünme tokenlarını da bu bütçeden harcar; dar değer JSON çıktıyı keser (varsayılan 2048) |
| `MIN_CONFIDENCE` / `MIN_NOTIFY_SCORE` | — | Kayıt eşiği (0.55) / bildirim eşiği (0.60) |
| `SIGNAL_COOLDOWN_MINUTES` | — | Aynı sembol+formasyon için tekrar bildirim yasağı (240 dk) |
| `NOTIFY_CHANNEL_ORDER` | — | Sıralı deneme; ilk başarılı kanalda durur (`telegram,pushover`) |

Anahtarlar yalnızca `.env`'de tutulur; `.env` git'e girmez (K-05).

## Çalıştırma

```powershell
.\run.ps1          # API + scheduler + web paneli   -> http://127.0.0.1:8000
```

Betiksiz eşdeğeri: `python main.py`. Tek process hem API'yi hem paneli servis eder.

- **Panel:** http://127.0.0.1:8000 (`/` → `/app/`)
- API dokümantasyonu: http://127.0.0.1:8000/docs

### Panel (`web/`)

Saf HTML/CSS/JS — build adımı, Node bağımlılığı ve CORS ayarı yok. Dört görünüm:
**Sinyaller** (master-detail: solda liste, sağda grafik + skor + haber + formasyon açıklaması),
**İzleme Listesi** (ekle / duraklat / sil / tek sembol tara), **Canlı Takip** (seçilen sembolün
fiyatı, indikatörleri ve grafiği periyodik yenilenir), **Haberler** (LLM özeti + sentiment
rozeti), **Sistem** (sağlık kartları + `job_runs` tablosu).

| Kısayol | İşlev |
|---|---|
| `Ctrl+K` | Komut paleti — sembol, formasyon, sayfa ve komut araması |
| `j` / `k` | Listede aşağı / yukarı |
| `r` | Yenile |
| `Esc` | Palet ve pencereleri kapat |

Açık/koyu tema sağ üstten değişir (tercih `localStorage`'da tutulur, grafikler de temaya uyar).
Otomatik yenileme 30 saniyede bir, `⟳` düğmesiyle kapatılabilir.

Eski Flet paneli `ui/` altında duruyor (`flet run ui/main_app.py`); artık birincil arayüz değil.

### Zamanlanmış işler

| İş | Ne zaman |
|---|---|
| `intraday_scan_bist` | Hafta içi 10:05–17:05 (Europe/Istanbul) |
| `intraday_scan_nasdaq` | Hafta içi 10:05–15:05 (America/New_York) |
| `eod_scan_*` | Kapanış + 15 dk, günlük mumla |
| `news_poll` | 15 dakikada bir (`NEWS_POLL_INTERVAL_MINUTES`) |

Hafta sonu ve sabit tarihli resmî tatiller atlanır (`core/market_hours.py`).

### API uçları

| Uç | Açıklama |
|---|---|
| `GET /health`, `GET /system/model` | Sistem durumu, aktif model sürümü + metrikleri |
| `GET /signals`, `GET /signals/{id}` | Sinyal listesi (ticker / min_score filtreli) |
| `POST /scan`, `POST /news/poll` | Manuel tarama / bildirim yoklaması (`background: true` ile asenkron) |
| `GET /symbols` + `POST` / `PATCH` / `DELETE` | İzleme listesi CRUD |
| `GET /news`, `POST /news/summarize` | Haberler + LLM özetleri; kota kesintisinde özetsiz kalanları tamamlama |
| `GET /charts/{ticker}` | Mum grafiği (PNG, RAM'de üretilir); `live=true` önbelleği atlar, kaynaktan taze çeker |
| `GET /quote/{ticker}` | Canlı fiyat: son fiyat, değişim, yüksek/düşük, hacim, RSI/EMA/MACD anlık görüntüsü |
| `GET /patterns`, `GET /patterns/{pattern}` | Formasyon sözlüğü: ne demek, nasıl teyit edilir, nerede geçersiz olur |
| `GET /jobs` | Son iş çalıştırmaları |

## Backtest

Geçmiş sinyallerin N mum sonraki getirisi ve isabet oranı:

```powershell
python -m core.backtest --horizon 5 --min-score 0.6
```

Yalnızca sinyal mumundan **sonraki** mumlar kullanılır (ileriye dönük veri sızıntısı yok).
Rapor formasyon ve skor grubu bazında kırılım verir; `--json` ile makine okunur çıktı alınır.

## Docker

```bash
docker compose up -d --build
```

`data/` ve `models/` klasörleri konteyner dışında kalır. İlk imaj `ultralytics → torch`
bağımlılığı nedeniyle 2–3 GB'dır. `.env` dosyası imaja **girmez**, çalışma anında okunur.

## Windows'ta servis olarak çalıştırma

[NSSM](https://nssm.cc/) ile:

```powershell
nssm install FinanceAgent "C:\...\Finance\.venv\Scripts\python.exe" "C:\...\Finance\main.py"
nssm set FinanceAgent AppDirectory "C:\...\Finance"
nssm start FinanceAgent
```

## Formasyon tespiti ve model sürümleme

Hazır YOLO ağırlıkları grafik formasyonu sınıfları içermediğinden varsayılan analizci
kural tabanlıdır (`ai_modules/pattern_rules.py`). Fine-tune:

```powershell
python training/train_vision.py --epochs 100
```

Eğitim çıktısı `models/yolov8_patterns_v{N}.pt` olarak **otomatik sürümlenir** ve
`models/model_metrics.json` dosyasına mAP50 / mAP50-95 / precision / recall yazılır.
`.env` içindeki `YOLO_MODEL_PATH` yeni ağırlığa yönlendirildiğinde `YoloAnalyzer`
kendiliğinden etkinleşir; sürüm ve metrikler `GET /system/model` ile görülebilir.

## Geliştirme

```powershell
pytest                       # 184 test
pytest --cov                 # kapsam (eşik %70, güncel %83)
ruff check .
mypy --ignore-missing-imports .
```

Mühendislik kuralları (async zorunluluğu, sıfır disk I/O, hata yalıtımı, dedup, tip güvenliği)
`ROADMAP.md` → "Değişmez Mühendislik Kuralları" bölümünde tanımlıdır.

## Durum

| Faz | Kapsam | Durum |
|---|---|---|
| 0 | İskelet, config, loglama, `/health` | ✅ |
| 1 | Veri akış hattı, grafik üretimi, indikatörler, DB | ✅ |
| 2 | Analizci registry, kural tabanlı tespit, YOLO, KAP/SEC, Gemini | ✅ |
| 3 | Skorlama, dedup, bildirim, seans takvimli scheduler, API | ✅ |
| 4 | Flet dashboard, grafik uçları, oto yenileme | ✅ |
| 5 | Backtest, Docker, servis betiği, model sürümleme, kapsam/mypy | ✅ |
