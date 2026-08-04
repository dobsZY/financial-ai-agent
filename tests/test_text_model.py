from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_modules import text_model
from ai_modules.rag.prompts import build_prompt
from ai_modules.rag.retriever import build_market_context
from ai_modules.text_model import LLMError, LLMQuotaExceeded, summarize, summarize_safe
from config.settings import get_settings
from schemas.market import OHLCVFrame
from schemas.news import NewsItem, NewsSource, RiskLevel

VALID_JSON = (
    '{"sentiment": 0.62, "bullets": ["Ciro artti", "Marj korundu", "Borç azaldi"], '
    '"risk_level": "low"}'
)


class _FakeUsage:
    total_token_count = 421


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.usage_metadata = _FakeUsage()


class _FakeModel:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0
        self.last_prompt = ""

    async def generate_content_async(self, prompt: str) -> _FakeResponse:
        self.calls += 1
        self.last_prompt = prompt
        return _FakeResponse(self._text)


@pytest.fixture(autouse=True)
def _reset_llm_state() -> None:
    text_model.reset_usage()


@pytest.fixture
def news_item() -> NewsItem:
    return NewsItem(
        source=NewsSource.KAP,
        external_id="1611139",
        title="ASELSAN A.S. - Yeni Is Iliskisi",
        ticker="ASELS.IS",
        url="https://www.kap.org.tr/tr/Bildirim/1611139",
        published_at=datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc),
        raw_text="Sirket 250 milyon USD tutarinda savunma sanayi sozlesmesi imzaladi.",
    )


def test_extract_json_handles_code_fence() -> None:
    payload = text_model._extract_json(f"```json\n{VALID_JSON}\n```")

    assert payload["sentiment"] == 0.62
    assert len(payload["bullets"]) == 3


def test_extract_json_handles_surrounding_text() -> None:
    payload = text_model._extract_json(f"Iste sonuc:\n{VALID_JSON}\nTesekkurler")

    assert payload["risk_level"] == "low"


def test_extract_json_raises_on_garbage() -> None:
    with pytest.raises(LLMError):
        text_model._extract_json("bu bir JSON degil")


async def test_summarize_returns_validated_summary(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    model = _FakeModel(VALID_JSON)
    monkeypatch.setattr(text_model, "get_model", lambda: model)

    summary = await summarize(news_item, "RSI(14): 61.0")

    assert summary.sentiment == 0.62
    assert len(summary.bullets) == 3
    assert summary.risk_level is RiskLevel.LOW
    assert summary.tokens == 421
    assert summary.model == get_settings().gemini_model
    assert "RSI(14): 61.0" in model.last_prompt
    assert text_model.calls_today() == 1


async def test_summarize_uses_cache(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    model = _FakeModel(VALID_JSON)
    monkeypatch.setattr(text_model, "get_model", lambda: model)

    await summarize(news_item)
    await summarize(news_item)

    assert model.calls == 1
    assert text_model.calls_today() == 1


async def test_summarize_enforces_daily_quota(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    model = _FakeModel(VALID_JSON)
    monkeypatch.setattr(text_model, "get_model", lambda: model)
    monkeypatch.setattr(get_settings(), "llm_daily_call_limit", 1)

    await summarize(news_item, use_cache=False)

    with pytest.raises(LLMQuotaExceeded):
        await summarize(news_item, use_cache=False)


class _QuotaError(Exception):
    """google.api_core.exceptions.ResourceExhausted taklidi."""


class _FailingModel:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    async def generate_content_async(self, prompt: str) -> None:
        self.calls += 1
        raise self._exc


async def test_provider_quota_error_blocks_further_calls(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    model = _FailingModel(
        _QuotaError("429 Your prepayment credits are depleted. Please go to AI Studio")
    )
    monkeypatch.setattr(text_model, "get_model", lambda: model)

    with pytest.raises(LLMQuotaExceeded):
        await summarize(news_item, use_cache=False)

    assert text_model.is_quota_blocked() is True

    with pytest.raises(LLMQuotaExceeded):
        await summarize(news_item, use_cache=False)

    assert model.calls == 1, "kota kilidi sonrasi API'ye tekrar gidilmemeli"


async def test_summarize_safe_skips_when_quota_blocked(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    model = _FailingModel(_QuotaError("RESOURCE_EXHAUSTED quota exceeded"))
    monkeypatch.setattr(text_model, "is_configured", lambda: True)
    monkeypatch.setattr(text_model, "get_model", lambda: model)

    assert await summarize_safe(news_item) is None
    assert await summarize_safe(news_item) is None
    assert model.calls == 1


async def test_transient_error_does_not_block(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    monkeypatch.setattr(
        text_model, "get_model", lambda: _FailingModel(RuntimeError("gecici baglanti hatasi"))
    )

    with pytest.raises(LLMError):
        await summarize(news_item, use_cache=False)

    assert text_model.is_quota_blocked() is False


async def test_summarize_rejects_out_of_range_sentiment(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    bad = '{"sentiment": 5.0, "bullets": ["a"], "risk_level": "low"}'
    monkeypatch.setattr(text_model, "get_model", lambda: _FakeModel(bad))

    with pytest.raises(LLMError):
        await summarize(news_item)


async def test_summarize_safe_returns_none_without_api_key(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    monkeypatch.setattr(text_model, "is_configured", lambda: False)

    assert await summarize_safe(news_item) is None


async def test_summarize_safe_swallows_errors(
    monkeypatch: pytest.MonkeyPatch, news_item: NewsItem
) -> None:
    monkeypatch.setattr(text_model, "is_configured", lambda: True)
    monkeypatch.setattr(text_model, "get_model", lambda: _FakeModel("bozuk cikti"))

    assert await summarize_safe(news_item) is None


def test_build_market_context_includes_indicators(frame: OHLCVFrame) -> None:
    context = build_market_context(frame)

    assert "RSI(14)" in context
    assert frame.symbol.yf_ticker in context
    assert "Tespit edilen formasyon: yok" in context


def test_build_market_context_without_frame() -> None:
    assert build_market_context(None) == "Baglam verisi yok."


def test_build_prompt_contains_schema_fields(news_item: NewsItem) -> None:
    prompt = build_prompt(news_item, "baglam")

    assert news_item.title in prompt
    assert "ASELS.IS" in prompt
    assert "baglam" in prompt
