# Arayüz Taslakları

Konsept aşaması — mevcut Flet paneline dokunulmadı. Amaç bir yön seçmek, kod yazmak değil.

Dosyalar tarayıcıda doğrudan açılır, dış bağımlılık yoktur (font/CDN/JS kütüphanesi yok).
Scroll animasyonlarını görmek için **gerçek tarayıcıda** açın — statik önizlemede hareket olmaz.

```powershell
start design\01-terminal.html
```

| Dosya | Ne |
|---|---|
| `04-panel.html` | **Yön A2 — seçilen yön.** Gerçek uygulama kabuğu: üç bölme, komut paleti, açık/koyu tema |
| `00-foundations.html` | Ortak tasarım dili: renk, tipografi, derinlik, hareket, erişilebilirlik bütçesi |
| `01-terminal.html` | Yön A (ilk deneme) — yoğun terminal ama sayfa gibi kayıyor; A2 bunun yerini aldı |
| `02-signal-story.html` | Yön B — scroll ile ilerleyen sinyal hikayesi; tanıtım/ilk kullanım için |
| `03-depth-deck.html` | Yön C — z ekseninde kart destesi; seçili görünümler için |

## Yön A2 — panel (güncel yön)

İlk denemede (A) sayfa aşağı kayıyordu; bu onu uygulamadan çok web sitesine benzetiyordu.
A2 bunu düzeltir:

- **Ekran yüksekliğine oturur** (`body{overflow:hidden}`), sayfa kaymaz — yalnız liste ve
  detay bölmesi kendi içinde kayar. Uygulama hissinin asıl kaynağı bu.
- **Üç bölme:** sol gezinme + hızlı filtreler · orta liste · sağ detay. Master-detail düzeni,
  "aradığımı hemen bulayım" isteğinin karşılığı: seçtiğin satırın her şeyi sağda, tıklamadan.
- **Komut paleti (Ctrl+K):** sembol, formasyon, sayfa ve komutlar tek kutudan. Klavyeyle
  `j`/`k` ile satır gezinme.
- **Açık + koyu tema:** `data-theme` ile tüm bileşenler, grafik dahil yeniden renklenir.
  Açık temada yeşil/kırmızı koyulaştırıldı — beyaz zeminde pastel yeşil okunmuyor.
- **Ferahlık:** satırlar 15px iç boşlukla, tek satırda 6 bilgi (sembol, formasyon, sparkline,
  yön, skor, bildirim durumu). Tablo çizgisi yok; ayrım boşluk ve hover ile.
- **Alt durum çubuğu:** scheduler, sonraki tarama, entegrasyon durumu — sürekli görünür.

Dar pencerede sparkline ve bildirim rozeti düşer, karar bilgisi (sembol · formasyon · yön · skor)
kalır; 980px altında detay bölmesi gizlenir.

## Araştırma özeti

Dört kategori incelendi; taslaklara giren kararlar:

**Trading terminalleri (TradingView, Bloomberg)** — koyu ve veri-yoğun düzen standart. Katmanlar
parlaklıkla değil kenar çizgisiyle ayrılıyor; aksan rengi yalnızca kâr/zarar için ayrılmış.
→ Yön A'nın tamamı ve ortak renk kuralı buradan.

**Retail (Robinhood, Revolut)** — az bilgiyi güzel gösterme; mikro-etkileşimler ve anlık geri
bildirim güven kuruyor. Revolut ana ekranı kullanım sıklığına göre yeniden diziyor.
→ Sinyal kartındaki skor çubuğu ve "bildirildi" geri bildirimi; ileride izleme listesini
kullanım sıklığına göre sıralama fikri.

**Kripto/Web3 (Coinbase, Uniswap, Rainbow)** — 3D ve motion'ı en agresif kullanan kategori,
ama okunabilirliği bozmadan: derinlik dekor değil, hiyerarşi taşıyor.
→ Yön C'nin z-ekseni yaklaşımı; "3D yalnız bilgi hiyerarşisi için" kuralı.

**Scroll-driven 3D (Stripe, Apple, Linear)** — teknik taraf: CSS `animation-timeline: scroll()/view()`
artık ana akım (Chrome/Edge 115+, Firefox 132+, Safari 18+; ~%84 küresel destek).
`animation-range` ile sahnelerin tam olarak nerede başlayıp biteceği belirleniyor.
→ Taslakların tamamı JS animasyon kütüphanesi olmadan, yalnız CSS ile çalışıyor.

## Teknik kararlar

- **Kütüphane yok.** Three.js yerine CSS 3D dönüşümleri + Canvas 2D. Gerçek WebGL derinliği
  (ışık, gölge, gaussian splat) gerekirse Three.js'e geçilir; şu anki etki için gerekmiyor.
- **Yalnız `transform` ve `opacity` animasyonu.** İkisi de compositor thread'inde çalışır;
  scroll sırasında layout tetikleyen özellik (width/height/margin) kullanılmadı.
- **Scroll'a bağlı animasyonlar `linear`.** Hız kullanıcının parmağından gelir; easing eklemek
  gecikme hissi yaratır.
- **`prefers-reduced-motion`** her üç yönde de destekli: 3D ve scroll efektleri kapanır,
  içerik statik ve okunur kalır.
- Veriler gerçek tarama çıktısından (GARAN.IS 0.74, KCHOL.IS 0.71, GOOGL 0.70, ASELS.IS 0.64…).

## Öneri

- **A2 = ürün.** Günlük kullanımın tamamı burada geçer.
- **Yön B = tanıtım / ilk kullanım.** Sistemi bir kez anlatır, sonra kenara çekilir.
- **Yön C = seçili görünüm.** "Günün en iyi 5 sinyali" gibi az sayıda kartla sınırlı bir
  ekranda değerli; ana liste olarak yorucu.

3D'nin A2'deki yeri kasıtlı olarak küçük: panelde derinlik, gölge ve katman sırasıyla kurulur.
Scroll'a bağlı 3D sahne geçişleri B ve C'de kalır — bir üretim panelinde her gün karşılaşılan
animasyon, üçüncü günden sonra yavaşlık gibi hissedilir.

## Sonraki adım kararı

Bu taslaklar **web** teknolojisi. Üretime taşınırsa mevcut Flet paneli yerini
Next.js/Tailwind'e bırakır (ADR-10'daki v2 yolu). Backend değişmez — `/signals`, `/charts`,
`/news`, `/jobs` uçları zaten hazır ve UI'dan bağımsız.

Flet'te kalınırsa: renk paleti, tipografi hiyerarşisi ve kart düzeni uygulanabilir;
scroll'a bağlı 3D sahne geçişleri uygulanamaz.
