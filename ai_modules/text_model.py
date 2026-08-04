from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from pydantic import ValidationError

from ai_modules.rag.prompts import SYSTEM_INSTRUCTION, build_prompt
from config.settings import get_settings
from core.logger import get_logger
from schemas.news import LLMSummary, NewsItem

logger = get_logger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

_model: Any | None = None
_model_name: str | None = None
_call_counter: dict[date, int] = {}
_summary_cache: dict[tuple[str, str], LLMSummary] = {}
_blocked_until: date | None = None

# Saglayici tarafli kota/limit hatalarinin imzalari
_QUOTA_MARKERS = (
    "resourceexhausted",
    "resource_exhausted",
    "429",
    "quota",
    "credits are depleted",
    "rate limit",
)


class LLMError(RuntimeError):
    """Gemini cagrisi basarisiz oldugunda firlatilir."""


class LLMQuotaExceeded(LLMError):
    """Gunluk cagri limiti dolduğunda firlatilir (maliyet korumasi, 2.10)."""


def is_configured() -> bool:
    return bool(get_settings().gemini_api_key)


def calls_today() -> int:
    return _call_counter.get(date.today(), 0)


def reset_usage() -> None:
    global _blocked_until
    _call_counter.clear()
    _summary_cache.clear()
    _blocked_until = None


def is_quota_blocked() -> bool:
    """Saglayici kotasi doldugunda gun sonuna kadar cagri yapilmaz."""
    return _blocked_until == date.today()


def _is_quota_error(exc: BaseException) -> bool:
    haystack = f"{type(exc).__name__} {exc}".lower()
    return any(marker in haystack for marker in _QUOTA_MARKERS)


def _block_for_today(reason: str) -> None:
    global _blocked_until
    _blocked_until = date.today()
    logger.warning("llm.quota_blocked", reason=reason)


def _register_call() -> None:
    settings = get_settings()
    today = date.today()
    if _blocked_until == today:
        raise LLMQuotaExceeded("Saglayici kotasi tukendi; bugun yeni cagri yapilmayacak")
    used = _call_counter.get(today, 0)
    if used >= settings.llm_daily_call_limit:
        raise LLMQuotaExceeded(
            f"Gunluk LLM limiti asildi ({used}/{settings.llm_daily_call_limit})"
        )
    _call_counter[today] = used + 1


def get_model() -> Any:
    """Gemini modelini lazy olarak yukler."""
    global _model, _model_name
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY tanimli degil")

    if _model is not None and _model_name == settings.gemini_model:
        return _model

    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    _model = genai.GenerativeModel(
        model_name=settings.gemini_model,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "max_output_tokens": 512,
        },
    )
    _model_name = settings.gemini_model
    logger.info("llm.model_loaded", model=settings.gemini_model)
    return _model


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(stripped)
        if match is None:
            raise LLMError(f"JSON cikarilamadi: {text[:200]}") from None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gecersiz JSON: {text[:200]}") from exc

    if not isinstance(payload, dict):
        raise LLMError("Beklenen JSON nesnesi degil")
    return payload


def _token_count(response: Any) -> int | None:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None
    total = getattr(usage, "total_token_count", None)
    return int(total) if total is not None else None


async def summarize(
    item: NewsItem,
    market_context: str = "Baglam verisi yok.",
    use_cache: bool = True,
) -> LLMSummary:
    """Bildirimi 3 maddelik JSON ozete ve sentiment skoruna cevirir."""
    cache_key = (item.source.value, item.external_id)
    if use_cache and cache_key in _summary_cache:
        logger.info("llm.cache_hit", external_id=item.external_id)
        return _summary_cache[cache_key]

    settings = get_settings()
    model = get_model()
    _register_call()

    prompt = build_prompt(item, market_context)
    try:
        response = await model.generate_content_async(prompt)
    except Exception as exc:  # noqa: BLE001 - SDK cesitli hatalar firlatir
        if _is_quota_error(exc):
            _block_for_today(str(exc)[:200])
            raise LLMQuotaExceeded(f"Gemini kotasi/kredisi tukendi: {exc}") from exc
        raise LLMError(f"Gemini cagrisi basarisiz: {exc}") from exc

    text = getattr(response, "text", "") or ""
    payload = _extract_json(text)
    payload["model"] = settings.gemini_model
    payload["tokens"] = _token_count(response)

    try:
        summary = LLMSummary.model_validate(payload)
    except ValidationError as exc:
        raise LLMError(f"LLM cikisi semaya uymuyor: {exc}") from exc

    if use_cache:
        _summary_cache[cache_key] = summary

    logger.info(
        "llm.summarized",
        external_id=item.external_id,
        sentiment=summary.sentiment,
        risk=summary.risk_level.value,
        tokens=summary.tokens,
        calls_today=calls_today(),
    )
    return summary


async def summarize_safe(
    item: NewsItem,
    market_context: str = "Baglam verisi yok.",
) -> LLMSummary | None:
    """Hata durumunda None doner; tarama akisini dusurmez (K-03)."""
    if not is_configured():
        logger.warning("llm.not_configured", external_id=item.external_id)
        return None
    if is_quota_blocked():
        logger.info("llm.skipped_quota_blocked", external_id=item.external_id)
        return None
    try:
        return await summarize(item, market_context)
    except LLMError as exc:
        logger.warning("llm.failed", external_id=item.external_id, error=str(exc))
        return None
