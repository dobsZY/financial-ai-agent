from __future__ import annotations

import httpx
import pytest
import respx

from schemas.news import NewsSource
from scrapers import kap_scraper, sec_scraper

KAP_PRIMARY = f"{kap_scraper.BASE_URL}{kap_scraper.PRIMARY_ENDPOINT}"
KAP_LEGACY = f"{kap_scraper.BASE_URL}{kap_scraper.LEGACY_ENDPOINT}"

KAP_RECORDS = [
    {
        "publishDate": "03.08.2026 09:10:35",
        "kapTitle": "ASELSAN ELEKTRONIK SANAYI VE TICARET A.S.",
        "subject": "Yeni Is Iliskisi",
        "summary": "250 milyon USD tutarinda sozlesme imzalandi",
        "stockCodes": "ASELS",
        "disclosureIndex": 1611139,
        "disclosureCategory": "ODA",
    },
    {
        "publishDate": "03.08.2026 08:00:00",
        "kapTitle": "TURK HAVA YOLLARI A.O.",
        "subject": "Finansal Rapor",
        "summary": "2026 2. donem finansal raporlar",
        "stockCodes": "THYAO",
        "disclosureIndex": 1611140,
        "disclosureCategory": "FR",
    },
    {
        "publishDate": "03.08.2026 07:00:00",
        "kapTitle": "BASKA SIRKET A.S.",
        "subject": "Kayitli Sermaye Sistemi",
        "summary": "Alakasiz duyuru",
        "stockCodes": "XXXXX",
        "disclosureIndex": 1611141,
        "disclosureCategory": "DG",
    },
]


@pytest.fixture(autouse=True)
def _reset_cik_cache() -> None:
    sec_scraper._cik_cache.clear()


@respx.mock
async def test_kap_parses_and_filters_by_ticker() -> None:
    respx.post(KAP_PRIMARY).mock(return_value=httpx.Response(200, json=KAP_RECORDS))

    items = await kap_scraper.fetch_disclosures(tickers=["ASELS.IS"])

    assert len(items) == 1
    item = items[0]
    assert item.source is NewsSource.KAP
    assert item.external_id == "1611139"
    assert item.ticker == "ASELS.IS"
    assert item.published_at is not None
    assert item.published_at.year == 2026
    assert "1611139" in (item.url or "")


@respx.mock
async def test_kap_relevance_filter_drops_unrelated() -> None:
    respx.post(KAP_PRIMARY).mock(return_value=httpx.Response(200, json=KAP_RECORDS))

    items = await kap_scraper.fetch_disclosures()

    assert {item.external_id for item in items} == {"1611139", "1611140"}


@respx.mock
async def test_kap_falls_back_to_legacy_endpoint() -> None:
    respx.post(KAP_PRIMARY).mock(return_value=httpx.Response(500))
    respx.post(KAP_LEGACY).mock(return_value=httpx.Response(200, json=KAP_RECORDS[:1]))

    items = await kap_scraper.fetch_disclosures(tickers=["ASELS"])

    assert len(items) == 1
    assert items[0].external_id == "1611139"


@respx.mock
async def test_kap_returns_empty_when_all_endpoints_fail() -> None:
    respx.post(KAP_PRIMARY).mock(return_value=httpx.Response(503))
    respx.post(KAP_LEGACY).mock(return_value=httpx.Response(503))

    assert await kap_scraper.fetch_disclosures() == []


@respx.mock
async def test_kap_detail_text_extraction() -> None:
    payload = [{"disclosure": ["<table><tr><td>Sozlesme bedeli 250 milyon USD</td></tr></table>"]}]
    respx.get(f"{kap_scraper.BASE_URL}/tr/api/notification/attachment-detail/1611139").mock(
        return_value=httpx.Response(200, json=payload)
    )

    text = await kap_scraper.fetch_disclosure_text("1611139")

    assert text is not None
    assert "250 milyon USD" in text


@respx.mock
async def test_sec_fetch_filings() -> None:
    respx.get(sec_scraper.TICKER_MAP_URL).mock(
        return_value=httpx.Response(
            200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        )
    )
    respx.get(sec_scraper.SUBMISSIONS_URL.format(cik="0000320193")).mock(
        return_value=httpx.Response(
            200,
            json={
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000320193-26-000070", "0000320193-26-000069"],
                        "form": ["8-K", "S-8"],
                        "filingDate": ["2026-07-31", "2026-07-20"],
                        "primaryDocument": ["aapl-8k.htm", "aapl-s8.htm"],
                        "reportDate": ["2026-07-31", "2026-07-20"],
                        "items": ["2.02,9.01", ""],
                    }
                }
            },
        )
    )

    items = await sec_scraper.fetch_filings("aapl")

    assert len(items) == 1
    item = items[0]
    assert item.source is NewsSource.SEC
    assert item.external_id == "0000320193-26-000070"
    assert item.ticker == "AAPL"
    assert "000032019326000070" in (item.url or "")
    assert item.raw_text == "2.02,9.01"


@respx.mock
async def test_sec_unknown_ticker_returns_empty() -> None:
    respx.get(sec_scraper.TICKER_MAP_URL).mock(
        return_value=httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL"}})
    )

    assert await sec_scraper.fetch_filings("YOKBOYLE") == []


@respx.mock
async def test_sec_sends_user_agent() -> None:
    route = respx.get(sec_scraper.TICKER_MAP_URL).mock(
        return_value=httpx.Response(200, json={})
    )

    await sec_scraper.load_cik_map(force=True)

    assert route.called
    assert route.calls[0].request.headers["user-agent"]
