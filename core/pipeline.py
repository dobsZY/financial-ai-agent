from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ai_modules.base import available_analyzers, deduplicate, filter_by_confidence
from ai_modules.rag.retriever import build_market_context
from ai_modules.text_model import summarize_safe
from config.settings import get_settings
from core.chart_factory import render_chart, to_png_bytes
from core.data_fetcher import fetch_many, watchlist_from_settings
from core.logger import get_logger
from core.market_hours import filter_open_tickers
from core.pattern_glossary import short_meaning
from core.scoring import bucket_timestamp, compute_final_score, cooldown_cutoff, should_notify
from core.indicators import trend_confirmation
from database import db_manager
from notifications.base import Notification, Priority, notify
from schemas.market import Interval, OHLCVFrame, SymbolConfig
from schemas.news import NewsItem, NewsSource
from schemas.signal import Detection, SignalCandidate

logger = get_logger(__name__)

_DIRECTION_EMOJI = {"LONG": "\U0001f4c8", "SHORT": "\U0001f4c9"}


@dataclass
class ScanResult:
    scanned: int = 0
    detections: int = 0
    saved: int = 0
    notified: int = 0
    skipped_duplicate: int = 0
    errors: list[str] = field(default_factory=list)
    candidates: list[SignalCandidate] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "detections": self.detections,
            "saved": self.saved,
            "notified": self.notified,
            "skipped_duplicate": self.skipped_duplicate,
            "errors": len(self.errors),
        }


async def _collect_detections(frame: OHLCVFrame) -> list[Detection]:
    """Tum etkin analizcileri paralel calistirir; biri patlarsa digerleri surer (K-03)."""
    analyzers = available_analyzers()
    if not analyzers:
        logger.warning("pipeline.no_analyzer_available")
        return []

    results = await asyncio.gather(
        *(analyzer.analyze(frame) for analyzer in analyzers), return_exceptions=True
    )

    detections: list[Detection] = []
    for analyzer, result in zip(analyzers, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "pipeline.analyzer_failed",
                analyzer=analyzer.name,
                ticker=frame.symbol.yf_ticker,
                error=str(result),
            )
            continue
        detections.extend(result)

    return deduplicate(detections)


def _build_notification(
    candidate: SignalCandidate,
    context_lines: list[str],
    image_png: bytes | None,
) -> Notification:
    detection = candidate.detection
    direction = candidate.direction.value
    emoji = _DIRECTION_EMOJI.get(direction, "")
    title = f"{emoji} {candidate.ticker} - {detection.pattern.value} ({direction})"

    meaning = short_meaning(detection.pattern)
    body_lines = [
        *([meaning, ""] if meaning else []),
        f"Skor: {candidate.final_score:.2f} | Guven: {detection.confidence:.2f}",
        f"Fiyat: {candidate.price:.2f}" if candidate.price is not None else "Fiyat: yok",
        f"Indikator teyidi: {candidate.indicator_score:+.2f}",
        f"Haber duyarliligi: {candidate.sentiment:+.2f}",
        f"Kaynak: {detection.source} | Periyot: {candidate.interval}",
        *context_lines,
    ]
    return Notification(
        title=title,
        body="\n".join(body_lines),
        priority=Priority.HIGH if (candidate.final_score or 0.0) >= 0.8 else Priority.NORMAL,
        image_png=image_png,
    )


async def _process_frame(
    frame: OHLCVFrame,
    result: ScanResult,
    cutoff: datetime,
    send_notification: bool,
    attach_chart: bool,
) -> None:
    detections = filter_by_confidence(
        await _collect_detections(frame), get_settings().min_confidence
    )
    if not detections:
        return

    result.detections += len(detections)
    indicator_score = trend_confirmation(frame.df)
    sentiment = await db_manager.recent_sentiment(frame.symbol.yf_ticker)
    moment = frame.last_timestamp or datetime.now(timezone.utc)

    for detection in detections:
        candidate = SignalCandidate(
            ticker=frame.symbol.yf_ticker,
            interval=frame.interval.value,
            detection=detection,
            bucket_ts=bucket_timestamp(moment, frame.interval),
            price=frame.latest_close,
            indicator_score=indicator_score,
            sentiment=sentiment,
            final_score=compute_final_score(detection, indicator_score, sentiment),
        )
        result.candidates.append(candidate)

        async with db_manager.session_scope() as session:
            signal = await db_manager.save_signal(session, candidate, cutoff)
            signal_id = signal.id if signal is not None else None

        if signal_id is None:
            result.skipped_duplicate += 1
            continue

        result.saved += 1

        if not (send_notification and should_notify(candidate.final_score or 0.0)):
            continue

        image = None
        if attach_chart:
            try:
                image = to_png_bytes(await render_chart(frame))
            except Exception as exc:  # noqa: BLE001 - grafik hatasi bildirimi engellemez
                logger.warning("pipeline.chart_failed", ticker=candidate.ticker, error=str(exc))

        notification = _build_notification(candidate, [], image)
        delivered = await notify(notification)
        if delivered:
            result.notified += 1
            async with db_manager.session_scope() as session:
                await db_manager.mark_notified(session, signal_id)


async def run_scan(
    tickers: list[str] | None = None,
    interval: Interval | None = None,
    only_open_markets: bool = False,
    send_notification: bool = True,
    attach_chart: bool = True,
    persist_candles: bool = True,
) -> ScanResult:
    """fetch -> chart/analiz -> skorlama -> persist -> notify (3.4)."""
    settings = get_settings()
    target_interval = interval or Interval(settings.intraday_interval)

    symbol_list = tickers or [item.yf_ticker for item in watchlist_from_settings()]
    if only_open_markets:
        symbol_list = filter_open_tickers(symbol_list)

    result = ScanResult()
    if not symbol_list:
        logger.info("pipeline.no_symbols", only_open_markets=only_open_markets)
        return result

    configs = [
        SymbolConfig.from_ticker(ticker, interval=target_interval) for ticker in symbol_list
    ]
    frames = await fetch_many(configs)
    result.scanned = len(frames)
    result.errors.extend(
        f"{config.yf_ticker}: veri alinamadi"
        for config in configs
        if config.yf_ticker not in frames
    )

    if persist_candles and frames:
        try:
            await db_manager.save_frames(list(frames.values()))
        except Exception as exc:  # noqa: BLE001
            logger.warning("pipeline.persist_failed", error=str(exc))
            result.errors.append(f"mum yazimi: {exc}")

    cutoff = cooldown_cutoff()
    for frame in frames.values():
        try:
            await _process_frame(frame, result, cutoff, send_notification, attach_chart)
        except Exception as exc:  # noqa: BLE001 - tek sembol hatasi taramayi durdurmaz
            logger.warning(
                "pipeline.symbol_failed", ticker=frame.symbol.yf_ticker, error=str(exc)
            )
            result.errors.append(f"{frame.symbol.yf_ticker}: {exc}")

    logger.info("pipeline.scan_completed", **result.summary)
    return result


async def _news_context(item: NewsItem) -> str:
    if not item.ticker:
        return "Baglam verisi yok."
    try:
        frames = await fetch_many([SymbolConfig.from_ticker(item.ticker, interval=Interval.D1)])
    except Exception as exc:  # noqa: BLE001
        logger.warning("news.context_failed", ticker=item.ticker, error=str(exc))
        return "Baglam verisi yok."
    frame = frames.get(item.ticker.strip().upper())
    return build_market_context(frame)


async def run_news_poll(
    tickers: list[str] | None = None,
    days: int | None = None,
    limit: int = 20,
    summarize: bool = True,
) -> dict[str, int]:
    """KAP + SEC bildirimlerini ceker, yenileri LLM ile ozetleyip kaydeder (3.4)."""
    from scrapers import kap_scraper, sec_scraper

    settings = get_settings()
    watchlist = tickers or [item.yf_ticker for item in watchlist_from_settings()]
    bist = [ticker for ticker in watchlist if ticker.endswith(".IS")]
    nasdaq = [ticker for ticker in watchlist if not ticker.endswith(".IS")]

    stats = {"fetched": 0, "new": 0, "summarized": 0, "errors": 0}
    items: list[NewsItem] = []

    try:
        items.extend(
            await kap_scraper.fetch_disclosures(
                tickers=bist or None, days=days or settings.news_poll_days, limit=limit
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("news.kap_failed", error=str(exc))
        stats["errors"] += 1

    if nasdaq:
        try:
            items.extend(await sec_scraper.fetch_many(nasdaq, limit=3))
        except Exception as exc:  # noqa: BLE001
            logger.warning("news.sec_failed", error=str(exc))
            stats["errors"] += 1

    stats["fetched"] = len(items)

    for item in items:
        async with db_manager.session_scope() as session:
            saved = await db_manager.save_news_item(session, item)
        if saved is None:
            continue

        stats["new"] += 1
        if not summarize:
            continue

        summary = await summarize_safe(item, await _news_context(item))
        if summary is None:
            continue

        async with db_manager.session_scope() as session:
            await db_manager.attach_summary(session, saved.id, summary)
        stats["summarized"] += 1

    logger.info("pipeline.news_poll_completed", **stats)
    return stats


async def backfill_summaries(limit: int = 20) -> dict[str, int]:
    """Ozetsiz kalan haberleri sonradan ozetler.

    LLM kotasi doldugunda devre kesici devreye girer ve o sirada kaydedilen
    haberler ozetsiz kalir; `run_news_poll` yalnizca **yeni** haberleri isledigi
    icin bunlar bir daha ele alinmaz. Kota geri geldiginde bu is onlari tamamlar.
    """
    rows = await db_manager.news_without_summary(limit=limit)
    stats = {"pending": len(rows), "summarized": 0, "failed": 0}

    for news, ticker in rows:
        item = NewsItem(
            source=NewsSource(news.source),
            external_id=news.external_id,
            title=news.title,
            ticker=ticker,
            url=news.url,
            published_at=news.published_at,
            raw_text=news.raw_text,
        )
        summary = await summarize_safe(item, await _news_context(item))
        if summary is None:
            stats["failed"] += 1
            continue

        async with db_manager.session_scope() as session:
            await db_manager.attach_summary(session, news.id, summary)
        stats["summarized"] += 1

    logger.info("pipeline.backfill_completed", **stats)
    return stats


async def _alert_job_failure(job_name: str, error: str) -> None:
    """Job cokerse tum kanallara uyari gonderir (3.8); bildirim hatasi yutulur."""
    try:
        await notify(
            Notification(
                title=f"⚠️ Job hatasi: {job_name}",
                body=f"{error}\n\nZaman: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
                priority=Priority.HIGH,
            ),
            fan_out=True,
        )
    except Exception as exc:  # noqa: BLE001 - uyari gonderilemese de akis surer
        logger.warning("pipeline.alert_failed", job=job_name, error=str(exc))


async def run_tracked_scan(job_name: str = "intraday_scan", **kwargs: object) -> ScanResult:
    """`run_scan`'i `job_runs` kaydiyla sarmalar (3.8)."""
    job_id = await db_manager.start_job_run(job_name)
    try:
        result = await run_scan(**kwargs)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - job zamanlayiciyi dusurmez
        logger.error("pipeline.job_failed", job=job_name, error=str(exc))
        await db_manager.finish_job_run(job_id, status="error", error_text=str(exc)[:1000])
        await _alert_job_failure(job_name, str(exc))
        return ScanResult(errors=[str(exc)])

    await db_manager.finish_job_run(
        job_id,
        status="partial" if result.errors else "success",
        items_processed=result.scanned,
        error_text="; ".join(result.errors)[:1000] or None,
    )
    return result


async def run_tracked_news_poll(job_name: str = "news_poll", **kwargs: object) -> dict[str, int]:
    """`run_news_poll`'u `job_runs` kaydiyla sarmalar (3.8)."""
    job_id = await db_manager.start_job_run(job_name)
    try:
        stats = await run_news_poll(**kwargs)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        logger.error("pipeline.job_failed", job=job_name, error=str(exc))
        await db_manager.finish_job_run(job_id, status="error", error_text=str(exc)[:1000])
        await _alert_job_failure(job_name, str(exc))
        return {"fetched": 0, "new": 0, "summarized": 0, "errors": 1}

    await db_manager.finish_job_run(
        job_id,
        status="partial" if stats["errors"] else "success",
        items_processed=stats["fetched"],
    )
    return stats
