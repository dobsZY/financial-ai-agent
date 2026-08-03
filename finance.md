AI-Driven Financial Command Center (BIST & NASDAQ)
Bu proje; Borsa İstanbul (BIST) ve NASDAQ piyasalarını 7/24 asenkron olarak tarayan, teknik grafik formasyonlarını bilgisayarlı görü (YOLO) ile tespit eden, KAP/SEC raporlarını LLM (Gemini) ile özetleyen ve kullanıcıya masaüstü panel ile anlık mobil bildirim (Pushover/Simplepush) gönderen tam otomatik, ucu açık ve genişletilebilir bir yapay zeka finans asistanıdır.
🏛️ 1. Sistem Mimarisi & Teknoloji Yığını
Proje, birbirini engellemeyen (non-blocking) asenkron mikroservis mimarisine dayanmaktadır.

Backend & API Gateway: FastAPI (Asenkron, Hızlı, Otomatik Dokümantasyon)

Veri Kazıma & Görev Yönetimi: Celery + Redis veya Asyncio APScheduler (7/24 Otomatik Tarama)

Grafik & Analiz Motoru: Python yfinance + mplfinance + OpenCV

Yapay Zeka Modülleri: YOLO (v8/v10) (Grafik Nesne Tespiti) + Gemini API (Haber & Rapor RAG Sistemi)

Bildirim Sistemi: Pushover API / Simplepush / Telegram Bot API

Arayüz (UI): Flet (Python tabanlı cross-platform) veya Next.js + Tailwind CSS (Responsive Web)

📂 2. Proje Klasör Yapısı
Agent'ın dosyaları doğru yerleştirmesi için bu yapıyı koruması zorunludur:
Plaintext
financial-ai-agent/
│
├── config/                  # API Anahtarları ve Sistem Ayarları
│   └── settings.py
│
├── core/                    # Arka Plan Servisleri ve Zamanlayıcılar
│   ├── scheduler.py         # 7/24 Cron/Task yöneticisi
│   └── data_fetcher.py      # yfinance ve Scraper modülleri
│
├── ai_modules/              # Yapay Zeka Servisleri
│   ├── vision_model.py      # YOLO Grafik Analiz Pipeline
│   └── text_model.py        # Gemini API / NLP Analiz Hattı
│
├── database/                # Veri Saklama Katmanı
│   └── db_manager.py        # Sinyaller, Loglar ve Geçmiş Veriler
│
├── notifications/           # Bildirim Gönderim Motoru
│   └── push_service.py      # Mobil Push Notification entegrasyonu
│
├── ui/                      # Kullanıcı Arayüzü
│   └── main_app.py          # Masaüstü/Mobil uyumlu dashboard
│
├── requirements.txt         # Bağımlılıklar
└── README.md                # Proje Kılavuzu

3. Geliştirme Yol Haritası (MVP Adımları)
Agent, projeyi sırasıyla şu fazlara bölerek inşa edecektir:

🔹 Faz 1: Altyapı ve Veri Akış Hattı (Data Pipeline)
yfinance entegrasyonunu tamamla. Belirtilen hisse kodlarının geçmiş ve canlı mum verilerini (OHLCV) asenkron çek.

mplfinance kullanarak sayısal verileri RAM üzerinde (Diske yazmadan BytesIO ile) grafik görseline dönüştür.

Görseli OpenCV formatına (numpy array) çeviren pipeline'ı kur.
🔹 Faz 2: Yapay Zeka Modüllerinin Kurulumu
Metin Modülü: KAP ve SEC bildirim metinlerini/haberlerini yakalayacak bir taslak kur. Gelen metni Gemini API'ye gönderen, finansal duygu analizi yaptıran ve 3 maddelik hap özet dönen RAG yapısını kodla.

Görsel Modülü: RAM'de üretilen grafik matrislerini kabul edecek ve eğitilecek YOLO modeline (ultralytics) girdi olarak besleyecek fonksiyonları hazırla.

🔹 Faz 3: Otomasyon ve Bildirim Motoru
Arka planda belirli periyotlarda (Örn: saatlik veya seans kapanışında) çalışacak zamanlayıcıyı (APScheduler veya Celery) kur.

Yapay zeka modüllerinden gelen pozitif sinyalleri yakala.

Pushover/Simplepush entegrasyonunu tamamla; sinyalleri, güven skorlarını ve analiz özetlerini anlık olarak telefona push bildirim atacak şekilde kodla.

🔹 Faz 4: Dashboard Arayüzü
Toplanan verileri, geçmiş sinyalleri ve yapay zekanın ürettiği raporları listeleyen minimalist, koyu tema (dark mode) destekli bir arayüz tasırla.

🚨 Geliştirici Agent İçin Kesin Kurallar (Prompt Instructions)
Asenkron Mimari: Ağ istekleri (yfinance, Gemini API, Push API) kesinlikle asenkron (async/await) olarak kurgulanmalı, ana sistemi bloklamamalıdır.

I/O Optimizasyonu: Grafik görselleri oluşturulurken diske .png yazıp silme işlemi YAPILMAMALIDIR. Tüm görsel manipülasyonları RAM üzerinde io.BytesIO ve OpenCV matrisleri ile dönmelidir.

Hata Yönetimi (Error Handling): BIST verileri gecikmeli gelebilir veya API limite takılabilir. Her veri çekme ve AI çağrısı try-except blokları ile korunmalı, sistem çökmeden log tutulmalıdır.

Ucu Açıklık: Modüller birbirine sıkı sıkıya bağlı (tightly coupled) olmamalıdır. Yarın sisteme yeni bir indikatör veya farklı bir LLM modeli eklendiğinde ai_modules/ altına yeni bir dosya eklemek yeterli olmalıdır.

Gereksinimler (requirements.txt)
Plaintext
fastapi
uvicorn
yfinance
mplfinance
opencv-python
numpy
pillow
google-generativeai
apscheduler
requests
httpx
flet
