from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import httpx
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from core.logger import get_logger
from schemas.news import NewsItem, NewsSource

logger = get_logger(__name__)

BASE_URL = "https://www.kap.org.tr"
PRIMARY_ENDPOINT = "/tr/api/disclosure/members/byCriteria"
LEGACY_ENDPOINT = "/tr/api/memberDisclosureQuery"
DETAIL_ENDPOINT = "/tr/api/notification/attachment-detail/{index}"

TIMEOUT = httpx.Timeout(20.0)
DATE_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%y %H:%M")

# Turkce karakter katlama: kaynak metin "Yeni Is Iliskisi" veya "Yeni İş İlişkisi" gelebilir
_TR_FOLD = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
        "â": "a",
        "î": "i",
        "û": "u",
    }
)


def _fold(text: str) -> str:
    return text.translate(_TR_FOLD).lower()


# Fiyat/hacim etkisi yuksek bildirim konulari (katlanmis biciminde saklanir)
RELEVANT_KEYWORDS = tuple(
    _fold(keyword)
    for keyword in (
        "pay alım satım",
        "finansal rapor",
        "kar payı",
        "sermaye artırım",
        "birleşme",
        "devralma",
        "yeni iş ilişkisi",
        "ihale",
        "yatırım",
        "geri alım",
        "özel durum",
    )
)


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": f"{BASE_URL}/tr/bildirim-sorgu",
        "User-Agent": "financial-ai-agent/0.1 (research)",
    }


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("kap.date_parse_failed", raw=raw)
    return None


def _extract_tickers(payload: dict[str, Any]) -> list[str]:
    tickers: list[str] = []
    for key in ("stockCodes", "relatedStocks"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            tickers.extend(part.strip().upper() for part in value.split(",") if part.strip())
    return list(dict.fromkeys(tickers))


def _matches(payload: dict[str, Any], tickers: set[str] | None) -> bool:
    if not tickers:
        return True
    return bool(tickers.intersection(_extract_tickers(payload)))


def _is_relevant(payload: dict[str, Any]) -> bool:
    haystack = _fold(
        " ".join(
            str(payload.get(key) or "")
            for key in ("subject", "summary", "disclosureCategory")
        )
    )
    return any(keyword in haystack for keyword in RELEVANT_KEYWORDS)


def _to_news_item(payload: dict[str, Any]) -> NewsItem | None:
    index = payload.get("disclosureIndex")
    if index is None:
        return None

    tickers = _extract_tickers(payload)
    title_parts = [
        str(payload.get("kapTitle") or "").strip(),
        str(payload.get("subject") or payload.get("summary") or "").strip(),
    ]
    title = " - ".join(part for part in title_parts if part) or f"KAP bildirimi {index}"

    return NewsItem(
        source=NewsSource.KAP,
        external_id=str(index),
        title=title[:512],
        ticker=f"{tickers[0]}.IS" if tickers else None,
        url=f"{BASE_URL}/tr/Bildirim/{index}",
        published_at=_parse_datetime(payload.get("publishDate")),
        raw_text=str(payload.get("summary") or "").strip() or None,
    )


def _normalize_ticker_filter(tickers: Iterable[str] | None) -> set[str] | None:
    if not tickers:
        return None
    return {ticker.strip().upper().removesuffix(".IS") for ticker in tickers if ticker.strip()}


@retry(
    retry=lambda state: isinstance(
        state.outcome.exception() if state.outcome else None, (httpx.HTTPError,)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    reraise=True,
)
async def _post_json(client: httpx.AsyncClient, endpoint: str, payload: dict[str, Any]) -> Any:
    response = await client.post(endpoint, json=payload, headers=_headers())
    response.raise_for_status()
    return response.json()


def _primary_payload(from_date: date, to_date: date) -> dict[str, Any]:
    return {
        "fromDate": from_date.isoformat(),
        "toDate": to_date.isoformat(),
        "mkkMemberOidList": [],
        "subjectList": [],
    }


def _legacy_payload(from_date: date, to_date: date) -> dict[str, Any]:
    return {
        "fromDate": from_date.isoformat(),
        "toDate": to_date.isoformat(),
        "year": "",
        "prd": "",
        "term": "",
        "ruleType": "",
        "bdkReview": "",
        "disclosureClass": "",
        "index": "",
        "market": "",
        "isLate": "",
        "subjectList": [],
        "mkkMemberOidList": [],
        "inactiveMkkMemberOidList": [],
        "bdkMemberOidList": [],
        "mainSector": "",
        "sector": "",
        "subSector": "",
        "memberType": None,
        "fromSrc": "N",
        "srcCategory": "",
        "discIndex": [],
    }


async def fetch_disclosures(
    tickers: Iterable[str] | None = None,
    days: int = 1,
    limit: int = 50,
    only_relevant: bool = True,
    client: httpx.AsyncClient | None = None,
) -> list[NewsItem]:
    """KAP bildirimlerini ceker. Endpoint degisirse eski API'ye duser (risk kaydi)."""
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=max(days, 1))
    ticker_filter = _normalize_ticker_filter(tickers)

    owns_client = client is None
    active = client or httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)

    try:
        raw: Any = None
        for endpoint, payload in (
            (PRIMARY_ENDPOINT, _primary_payload(from_date, to_date)),
            (LEGACY_ENDPOINT, _legacy_payload(from_date, to_date)),
        ):
            try:
                raw = await _post_json(active, endpoint, payload)
                break
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("kap.endpoint_failed", endpoint=endpoint, error=str(exc))
        if raw is None:
            logger.warning("kap.all_endpoints_failed")
            return []
    finally:
        if owns_client:
            await active.aclose()

    records = raw if isinstance(raw, list) else raw.get("disclosures", []) if isinstance(raw, dict) else []

    items: list[NewsItem] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if not _matches(record, ticker_filter):
            continue
        if only_relevant and not _is_relevant(record):
            continue
        item = _to_news_item(record)
        if item is not None:
            items.append(item)
        if len(items) >= limit:
            break

    logger.info("kap.fetched", total=len(records), matched=len(items), days=days)
    return items


async def fetch_disclosure_text(
    disclosure_index: str,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Bildirim detayindaki HTML govdeyi duz metne cevirir."""
    owns_client = client is None
    active = client or httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)
    try:
        response = await active.get(
            DETAIL_ENDPOINT.format(index=disclosure_index), headers=_headers()
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("kap.detail_failed", index=disclosure_index, error=str(exc))
        return None
    finally:
        if owns_client:
            await active.aclose()

    blocks = _collect_html_blocks(payload)
    if not blocks:
        return None

    texts = [HTMLParser(block).text(separator=" ", strip=True) for block in blocks]
    combined = " ".join(text for text in texts if text)
    return combined.strip() or None


def _collect_html_blocks(payload: Any) -> list[str]:
    """Detay yanitinin sekli degisebilir; tum string listelerini toplar."""
    blocks: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            if "<" in node and ">" in node:
                blocks.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(payload)
    return blocks
