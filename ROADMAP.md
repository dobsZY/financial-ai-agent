# AI-Driven Financial Command Center — Teknik Yol Haritası

> Bu doküman hem insan geliştirici hem de yapay zeka agent'ı için **tek doğruluk kaynağıdır (single source of truth)**.
> Her görev tamamlandığında ilgili kutucuk `[x]` yapılır ve "Durum Günlüğü" bölümüne satır eklenir.
> Kaynak spesifikasyon: `finance.md`
> Depo: https://github.com/dobsZY/financial-ai-agent (`main` dalı)

---

## 0. Karar Kayıtları (ADR — Architecture Decision Records)

MVP kapsamında kilitlenen teknik kararlar. Değişiklik gerekirse bu tablo güncellenir.

| # | Konu | Karar (MVP) | Gerekçe | Alternatif (v2) |
|---|------|-------------|---------|-----------------|
| ADR-01 | Runtime | Python 3.12 | Makinede kurulu sürümler 3.12/3.13; `ultralytics`+`numpy 1.26` tekerlek uyumu 3.12'de stabil | 3.13 (numpy 2.x gerekir) |
| ADR-02 | API Katmanı | FastAPI + Uvicorn | Async native, otomatik OpenAPI | — |
| ADR-03 | Zamanlayıcı | APScheduler (`AsyncIOScheduler`) | Tek process, Redis bağımlılığı yok | Celery + Redis (yatay ölçek) |
| ADR-04 | Veritabanı | SQLite + SQLAlchemy 2.0 (async, `aiosqlite`) | Sıfır kurulum, tek dosya | PostgreSQL (aynı ORM ile migration'sız geçiş) |
| ADR-05 | Migration | Alembic | Şema evrimi kontrolü | — |
| ADR-06 | Görsel Üretim | `mplfinance` → `io.BytesIO` → `numpy` | Disk I/O yasağı (bkz. Kural K-02) | — |
| ADR-07 | Vision Model | Ultralytics YOLOv8n (başta pretrained, sonra fine-tune) | Hafif, CPU'da çalışır | YOLOv10 / RT-DETR |
| ADR-08 | LLM | Gemini (`gemini-2.0-flash`) | Ucuz, hızlı, JSON mode desteği | OpenAI / yerel Ollama |
| ADR-09 | Bildirim | Pushover (birincil), Telegram (yedek) | Basit REST, mobil push | Simplepush |
| ADR-10 | UI | Flet (masaüstü + web aynı kod) | Tek dilde (Python) tam yığın | Next.js + Tailwind |
| ADR-11 | Konfigürasyon | Pydantic Settings + `.env` | Tip güvenli, sırlar kodda değil | — |
| ADR-12 | Paket yönetimi | `venv` + `requirements.txt` (+ `requirements-dev.txt`) | Düşük sürtünme | Poetry / uv |
| ADR-13 | Versiyon kontrolü | GitHub public repo `dobsZY/financial-ai-agent`, tek dal `main` | Basit akış; her faz sonunda push | feature branch + PR |

---

## 1. Değişmez Mühendislik Kuralları (Agent Constraints)

Her PR/commit bu kurallara karşı denetlenir.

- **K-01 — Async her yerde:** Ağ çağrıları (`yfinance`, Gemini, Pushover, scraper) `async/await` ile. Bloklayan senkron kütüphaneler (`yfinance`, `matplotlib`, `ultralytics`) **`asyncio.to_thread()`** veya `run_in_executor` ile thread pool'a alınır. Event loop asla bloklanmaz.
- **K-02 — Sıfır disk I/O (grafik):** `.png` diske yazılmaz. Zincir: `DataFrame → mplfinance(savefig=BytesIO) → PIL/np.frombuffer → cv2 (BGR ndarray)`.
- **K-03 — Hata yalıtımı:** Her dış çağrı `try/except` + `tenacity` retry (exponential backoff) ile sarılır. Bir sembolün hatası tüm taramayı düşürmez (`asyncio.gather(..., return_exceptions=True)`).
- **K-04 — Gevşek bağlılık:** Yeni indikatör/model eklemek = `ai_modules/` altına yeni dosya + registry'ye kayıt. Mevcut dosyalarda değişiklik gerekmemeli (Strategy + Registry pattern).
- **K-05 — Sır yönetimi:** API anahtarları yalnız `.env`'de. `.env` git'e girmez; `.env.example` girer.
- **K-06 — Tip güvenliği:** Tüm public fonksiyonlar type hint'li. Veri sözleşmeleri Pydantic modelleri (`schemas/`).
- **K-07 — Yapılandırılmış log:** `structlog`/`logging` JSON formatı; `print()` yasak.
- **K-08 — Idempotency:** Aynı sembol + zaman dilimi + formasyon için tekrar bildirim gönderilmez (DB'de unique constraint + dedup penceresi).
- **K-09 — Test:** Her modül için `pytest` + `pytest-asyncio` birim testi. Dış API'ler mock'lanır (`respx`/`unittest.mock`).
- **K-10 — Rate limit:** Sembol taramalarında `asyncio.Semaphore` ile eşzamanlılık sınırı (varsayılan 5).
- **K-11 — Versiyon kontrolü:** Her tamamlanan görev (veya görev kümesi) için `pytest` + `ruff check` yeşil olduğunda commit atılır ve `origin/main`'e push edilir. Commit mesajı formatı: `Faz X.Y: <kısa açıklama>`. `.env`, `*.db`, `models/*.pt` asla commit'lenmez.

---

## 2. Hedef Dosya Ağacı

```
Finance/
├── .env.example
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── ROADMAP.md                  # bu dosya
├── main.py                     # FastAPI app + scheduler lifespan
│
├── config/
│   ├── __init__.py
│   └── settings.py             # Pydantic BaseSettings
│
├── schemas/                    # Pydantic veri sözleşmeleri
│   ├── market.py               # OHLCV, SymbolConfig
│   ├── signal.py               # Signal, PatternDetection, Confidence
│   └── news.py                 # NewsItem, LLMSummary
│
├── core/
│   ├── logger.py               # structlog kurulumu
│   ├── data_fetcher.py         # yfinance async wrapper
│   ├── chart_factory.py        # DataFrame -> BytesIO -> np.ndarray
│   ├── indicators.py           # RSI/EMA/MACD/Hacim (pandas-ta veya el yazımı)
│   ├── scheduler.py            # AsyncIOScheduler job tanımları
│   └── pipeline.py             # Orkestrasyon: fetch -> chart -> AI -> signal -> notify
│
├── ai_modules/
│   ├── base.py                 # AnalyzerProtocol (ABC) + registry
│   ├── vision_model.py         # YOLO inference (to_thread)
│   ├── text_model.py           # Gemini istemcisi + prompt şablonları
│   └── rag/
│       ├── retriever.py        # KAP/SEC doküman getirme
│       └── prompts.py
│
├── scrapers/
│   ├── kap_scraper.py          # KAP bildirimleri (BIST)
│   └── sec_scraper.py          # SEC EDGAR (NASDAQ)
│
├── database/
│   ├── models.py               # SQLAlchemy ORM
│   ├── db_manager.py           # AsyncSession, CRUD
│   └── migrations/             # Alembic
│
├── notifications/
│   ├── base.py                 # NotifierProtocol
│   ├── push_service.py         # Pushover
│   └── telegram_service.py     # yedek kanal
│
├── api/
│   └── routes/
│       ├── signals.py          # GET /signals, /signals/{id}
│       ├── symbols.py          # CRUD izleme listesi
│       └── health.py           # /health, /metrics
│
├── ui/
│   ├── main_app.py             # Flet dashboard
│   └── components/
│
└── tests/
    ├── conftest.py
    ├── test_data_fetcher.py
    ├── test_chart_factory.py
    ├── test_vision_model.py
    ├── test_text_model.py
    └── test_pipeline.py
```

---

## 3. Veri Modeli (SQLite / SQLAlchemy)

| Tablo | Alanlar | Not |
|-------|---------|-----|
| `symbols` | `id, ticker, market(BIST/NASDAQ), name, is_active, timeframe, created_at` | İzleme listesi |
| `candles` | `id, symbol_id(FK), ts, open, high, low, close, volume, interval` | UNIQUE(symbol_id, ts, interval) |
| `signals` | `id, symbol_id(FK), pattern, confidence, direction(LONG/SHORT), price_at_signal, chart_hash, created_at, notified_at` | UNIQUE(symbol_id, pattern, bucket_ts) → K-08 |
| `news_items` | `id, symbol_id, source(KAP/SEC), external_id, title, url, published_at, raw_text` | UNIQUE(source, external_id) |
| `llm_summaries` | `id, news_id(FK), sentiment(-1..1), bullets_json, model, tokens, created_at` | |
| `job_runs` | `id, job_name, started_at, finished_at, status, error_text, items_processed` | Gözlemlenebilirlik |

---

## 4. Fazlar ve Görev Listesi

### 🔹 Faz 0 — Proje İskeleti & Ortam
- [x] `0.1` Python 3.12 `venv` oluştur, aktifleştir
- [x] `0.2` Klasör ağacını + `__init__.py` dosyalarını oluştur (Bölüm 2)
- [x] `0.3` `requirements.txt` ve `requirements-dev.txt` yaz, kur
- [x] `0.4` `.gitignore` + `.env.example` (GEMINI_API_KEY, PUSHOVER_TOKEN, PUSHOVER_USER, TELEGRAM_*, DB_URL, LOG_LEVEL)
- [x] `0.5` `config/settings.py` — Pydantic `BaseSettings`, `@lru_cache get_settings()`
- [x] `0.6` `core/logger.py` — structlog, JSON + renkli konsol
- [x] `0.7` `main.py` — FastAPI + `lifespan` (scheduler start/stop), `/health` endpoint
- [x] `0.8` `git init` + ilk commit
- **Kabul kriteri:** ✅ `pytest` yeşil (`tests/test_health.py`), `ruff check` temiz, `GET /health` → `{"status":"ok"}`
- **Not:** `pydantic-settings` liste alanlarını JSON olarak parse ettiğinden `BIST_SYMBOLS`/`NASDAQ_SYMBOLS` CSV string olarak okunur; `bist_tickers` / `nasdaq_tickers` property'leri listeye çevirir.

### 🔹 Faz 1 — Veri Akış Hattı
- [ ] `1.1` `schemas/market.py` — `Candle`, `OHLCVFrame`, `SymbolConfig`
- [ ] `1.2` `core/data_fetcher.py` — `async fetch_ohlcv(ticker, interval, period)`; `yfinance` çağrısı `asyncio.to_thread` içinde; BIST için `.IS` suffix normalizasyonu
- [ ] `1.3` Retry + timeout (`tenacity`), `Semaphore(5)` ile toplu çekim `fetch_many()`
- [ ] `1.4` `core/chart_factory.py` — `render_chart(df) -> np.ndarray`; `mplfinance` `savefig=BytesIO`, dark style, sabit `figsize/dpi` (model girdisi determinizmi)
- [ ] `1.5` `cv2.imdecode` ile BGR ndarray dönüşümü + boyut doğrulaması (örn. 640×640)
- [ ] `1.6` `core/indicators.py` — RSI(14), EMA(20/50/200), MACD, hacim ortalaması
- [ ] `1.7` `database/models.py` + `db_manager.py` + Alembic ilk migration; `candles` upsert
- [ ] `1.8` Testler: `test_data_fetcher.py`, `test_chart_factory.py` (disk yazımı olmadığını assert et)
- **Kabul kriteri:** `THYAO.IS` ve `AAPL` için 1h veri çekilip RAM'de grafik ndarray üretilir, DB'ye yazılır; hiçbir `.png` oluşmaz

### 🔹 Faz 2 — Yapay Zeka Modülleri
- [ ] `2.1` `ai_modules/base.py` — `Analyzer` protokolü (`async analyze(payload) -> list[Detection]`) + `REGISTRY` decorator
- [ ] `2.2` `ai_modules/vision_model.py` — Ultralytics yükleme (singleton, lazy), `async detect(frame)` → `to_thread`
- [ ] `2.3` Formasyon sınıf listesi: `double_top, double_bottom, head_shoulders, inv_head_shoulders, asc_triangle, desc_triangle, bull_flag, bear_flag, cup_handle`
- [ ] `2.4` Fine-tune hattı taslağı: `datasets/` YOLO formatı, `data.yaml`, `train.py` (opsiyonel, ayrı çalıştırılır)
- [ ] `2.5` Güven eşiği + NMS ayarı; `confidence < settings.MIN_CONFIDENCE` olanlar elenir
- [ ] `2.6` `scrapers/kap_scraper.py` — KAP bildirim listesi (httpx + selectolax), `external_id` dedup
- [ ] `2.7` `scrapers/sec_scraper.py` — SEC EDGAR JSON API (User-Agent zorunlu), 8-K/10-Q filtreleri
- [ ] `2.8` `ai_modules/text_model.py` — Gemini async çağrı, **JSON şema zorlaması**: `{sentiment: float, bullets: [3 madde], risk_level: str}`
- [ ] `2.9` `ai_modules/rag/` — haber + son fiyat hareketi + indikatörleri prompt'a bağlayan context builder
- [ ] `2.10` Token/maliyet logu (`llm_summaries.tokens`), günlük çağrı limiti
- [ ] `2.11` Testler: mock'lu `test_vision_model.py`, `test_text_model.py`
- **Kabul kriteri:** Bir grafik ndarray → tespit listesi; bir KAP metni → 3 maddelik JSON özet + sentiment skoru

### 🔹 Faz 3 — Otomasyon & Bildirim
- [ ] `3.1` `notifications/base.py` — `Notifier` protokolü; çoklu kanal fan-out
- [ ] `3.2` `notifications/push_service.py` — Pushover async POST, öncelik/ses, grafik eki (opsiyonel)
- [ ] `3.3` `notifications/telegram_service.py` — yedek kanal, birincil başarısızsa devreye girer
- [ ] `3.4` `core/pipeline.py` — `run_scan()`: fetch → chart → vision → news → LLM → skorlama → persist → notify
- [ ] `3.5` Skorlama: `final_score = w1*vision_conf + w2*sentiment + w3*indicator_confirm` (ağırlıklar `settings`'te)
- [ ] `3.6` Dedup/idempotency: aynı sembol+formasyon için `SIGNAL_COOLDOWN_MINUTES` içinde tekrar yok
- [ ] `3.7` `core/scheduler.py` — job'lar: `intraday_scan` (saatlik, seans içi), `eod_scan` (kapanış), `news_poll` (15 dk). BIST (Europe/Istanbul) ve NASDAQ (America/New_York) seans takvimi + hafta sonu/tatil atlama
- [ ] `3.8` `job_runs` tablosuna her koşu kaydı; hata durumunda uyarı bildirimi
- [ ] `3.9` `api/routes/signals.py`, `symbols.py` — listeleme, filtreleme, manuel tarama tetikleme (`POST /scan`)
- [ ] `3.10` Testler: `test_pipeline.py` uçtan uca (tüm dış bağımlılıklar mock)
- **Kabul kriteri:** Scheduler açıkken sinyal üretilir, DB'ye yazılır ve telefona tek bir push düşer (tekrar bildirim yok)

### 🔹 Faz 4 — Dashboard (Flet)
- [ ] `4.1` `ui/main_app.py` — dark theme, sol navigasyon (Sinyaller / İzleme Listesi / Haberler / Loglar)
- [ ] `4.2` Sinyal kartı bileşeni: sembol, formasyon, güven %, yön, zaman, mini grafik
- [ ] `4.3` Grafik görüntüleyici: pipeline'daki ndarray → base64 PNG (yalnız UI katmanında, diske değil)
- [ ] `4.4` İzleme listesi CRUD (API'ye bağlı)
- [ ] `4.5` Haber/LLM özet paneli + sentiment rozeti
- [ ] `4.6` `job_runs` tabanlı sistem sağlığı görünümü
- [ ] `4.7` Otomatik yenileme (polling veya WebSocket `/ws/signals`)
- **Kabul kriteri:** `flet run ui/main_app.py` ile panel açılır, canlı sinyaller listelenir

### 🔹 Faz 5 — Sağlamlaştırma & Dağıtım
- [ ] `5.1` `README.md` — kurulum, `.env` doldurma, çalıştırma, mimari şeması
- [ ] `5.2` Backtest betiği: geçmiş sinyallerin N mum sonrası getirisi (isabet oranı)
- [ ] `5.3` Dockerfile + `docker-compose.yml` (app + opsiyonel Redis/Postgres)
- [ ] `5.4` Windows için `run.ps1` / servis (NSSM) veya systemd unit
- [ ] `5.5` Model versiyonlama (`models/yolov8_patterns_v1.pt`) + performans metrikleri
- [ ] `5.6` `pytest --cov` ≥ %70, `ruff` + `mypy` temiz

---

## 5. Risk Kaydı

| Risk | Etki | Azaltma |
|------|------|---------|
| `yfinance` BIST verisi gecikmeli/eksik | Yanlış sinyal | Veri tazelik kontrolü; bayat veriyle sinyal üretme |
| YOLO pretrained modelde formasyon sınıfı yok | Faz 2 tıkanır | Önce kural-tabanlı formasyon tespiti (fallback), paralelde etiketli veri toplayıp fine-tune |
| Gemini rate limit / maliyet | Analiz durur | Günlük kota, cache (aynı `news_id` tekrar özetlenmez), backoff |
| KAP/SEC HTML yapısı değişir | Scraper kırılır | Seçiciler tek dosyada izole; parse hatasında uyarı bildirimi |
| Bildirim spam'i | Kullanıcı kapatır | K-08 dedup + cooldown + minimum güven eşiği |
| Event loop bloklanması | Sistem donar | Ağır işler `to_thread`; job süresi ölçümü ve loglama |

---

## 6. Durum Günlüğü

| Tarih | Faz/Görev | Yapılan | Not |
|-------|-----------|---------|-----|
| 2026-08-03 | — | Yol haritası oluşturuldu | ADR'ler kilitlendi |
| 2026-08-03 | Altyapı | GitHub public repo oluşturuldu, `main` push edildi | `gh` ile; `.env` takip edilmiyor (doğrulandı) |
| 2026-08-03 | Faz 0 (0.1–0.8) | İskelet, `.env.example`, `settings.py`, `logger.py`, `scheduler.py` (job'suz), `/health`, `tests/test_health.py`, git init | Python 3.12 venv; 1 test geçti, ruff temiz |

---

## 7. Sonraki Adım

**Faz 1 → görev `1.1`–`1.8`.** Veri akış hattı: `schemas/market.py`, async `data_fetcher`, `chart_factory` (BytesIO → ndarray), indikatörler, DB modelleri ve testler.
