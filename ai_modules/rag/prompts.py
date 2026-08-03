from __future__ import annotations

from schemas.news import NewsItem

SYSTEM_INSTRUCTION = """Sen BIST ve NASDAQ piyasalarinda uzman bir finansal analistsin.
Gorevin: verilen sirket bildirimini ve piyasa baglamini degerlendirip kisa, olculebilir bir
degerlendirme uretmek. Spekulasyon yapma, yalnizca metinde ve baglamda olan bilgiye dayan.
Yatirim tavsiyesi verme; olasi fiyat etkisini tarafsiz degerlendir.

Cikti KURALLARI:
- Yalnizca gecerli JSON dondur, baska hicbir metin ekleme.
- sentiment: -1.0 (cok olumsuz) ile 1.0 (cok olumlu) arasinda ondalik sayi.
- bullets: tam olarak 3 madde, her biri en fazla 140 karakter, Turkce.
- risk_level: "low", "medium" veya "high".

JSON semasi:
{"sentiment": number, "bullets": [string, string, string], "risk_level": string}
"""

_TEMPLATE = """### Bildirim
Kaynak: {source}
Sembol: {ticker}
Baslik: {title}
Yayin: {published_at}

Icerik:
{content}

### Piyasa Baglami
{market_context}

Yukaridaki bildirimi degerlendir ve istenen JSON'u dondur."""

MAX_CONTENT_CHARS = 6000


def build_prompt(item: NewsItem, market_context: str = "Baglam verisi yok.") -> str:
    content = (item.content or "Icerik bulunamadi.")[:MAX_CONTENT_CHARS]
    return _TEMPLATE.format(
        source=item.source.value,
        ticker=item.ticker or "belirtilmemis",
        title=item.title,
        published_at=item.published_at.isoformat() if item.published_at else "bilinmiyor",
        content=content,
        market_context=market_context,
    )
