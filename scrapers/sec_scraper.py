from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import get_settings
from core.logger import get_logger
from schemas.news import NewsItem, NewsSource

logger = get_logger(__name__)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"

RELEVANT_FORMS: tuple[str, ...] = ("8-K", "10-Q", "10-K", "6-K")
TIMEOUT = httpx.Timeout(20.0)

_cik_cache: dict[str, str] = {}


def _headers() -> dict[str, str]:
    """SEC, tanimlayici User-Agent zorunlu tutar; aksi halde 403 doner."""
    return {
        "User-Agent": get_settings().sec_user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    reraise=True,
)
async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    response = await client.get(url, headers=_headers())
    response.raise_for_status()
    return response.json()


async def load_cik_map(client: httpx.AsyncClient | None = None, force: bool = False) -> dict[str, str]:
    """Ticker -> 10 haneli CIK eslemesi (surec icinde onbelleklenir)."""
    if _cik_cache and not force:
        return _cik_cache

    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        payload = await _get_json(active, TICKER_MAP_URL)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("sec.cik_map_failed", error=str(exc))
        return dict(_cik_cache)
    finally:
        if owns_client:
            await active.aclose()

    entries = payload.values() if isinstance(payload, dict) else payload
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip().upper()
        cik = entry.get("cik_str") or entry.get("cik")
        if ticker and cik is not None:
            _cik_cache[ticker] = str(int(cik)).zfill(10)

    logger.info("sec.cik_map_loaded", size=len(_cik_cache))
    return _cik_cache


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _recent_filings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recent = ((payload.get("filings") or {}).get("recent")) or {}
    accessions = recent.get("accessionNumber") or []
    columns = ("form", "filingDate", "primaryDocument", "reportDate", "items")
    rows: list[dict[str, Any]] = []
    for position, accession in enumerate(accessions):
        row: dict[str, Any] = {"accessionNumber": accession}
        for column in columns:
            values = recent.get(column) or []
            row[column] = values[position] if position < len(values) else None
        rows.append(row)
    return rows


async def fetch_filings(
    ticker: str,
    forms: Iterable[str] = RELEVANT_FORMS,
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[NewsItem]:
    """Tek sembol icin son SEC dosyalamalarini NewsItem olarak dondurur."""
    normalized = ticker.strip().upper()
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=TIMEOUT)

    try:
        cik_map = await load_cik_map(active)
        cik = cik_map.get(normalized)
        if cik is None:
            logger.warning("sec.cik_not_found", ticker=normalized)
            return []

        try:
            payload = await _get_json(active, SUBMISSIONS_URL.format(cik=cik))
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("sec.submissions_failed", ticker=normalized, error=str(exc))
            return []
    finally:
        if owns_client:
            await active.aclose()

    wanted = {form.upper() for form in forms}
    items: list[NewsItem] = []
    for row in _recent_filings(payload):
        form = str(row.get("form") or "").upper()
        if form not in wanted:
            continue

        accession = str(row.get("accessionNumber") or "")
        if not accession:
            continue

        document = row.get("primaryDocument") or ""
        url = ARCHIVE_URL.format(
            cik_int=int(cik),
            accession=accession.replace("-", ""),
            document=document,
        )
        items.append(
            NewsItem(
                source=NewsSource.SEC,
                external_id=accession,
                title=f"{normalized} {form} dosyalamasi",
                ticker=normalized,
                url=url,
                published_at=_parse_date(row.get("filingDate")),
                raw_text=str(row.get("items") or "").strip() or None,
            )
        )
        if len(items) >= limit:
            break

    logger.info("sec.fetched", ticker=normalized, count=len(items))
    return items


async def fetch_many(
    tickers: Iterable[str],
    forms: Iterable[str] = RELEVANT_FORMS,
    limit: int = 5,
) -> list[NewsItem]:
    """Coklu sembol; bir sembolun hatasi digerlerini dusurmez (K-03)."""
    results: list[NewsItem] = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for ticker in tickers:
            try:
                results.extend(await fetch_filings(ticker, forms, limit, client))
            except Exception as exc:  # noqa: BLE001
                logger.warning("sec.ticker_failed", ticker=ticker, error=str(exc))
    return results
