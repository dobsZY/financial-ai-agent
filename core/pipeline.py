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
from core.pattern_glossary import get_info_safe, short_meaning
from core.scoring import bucket_timestamp, compute_final_score, cooldown_cutoff, should_notify
from core.indicators import compute_all, trend_confirmation
from database import db_manager
from notifications.base import Notification, Priority, notify
from schemas.market import Interval, OHLCVFrame, SymbolConfig
from schemas.news import NewsItem, NewsSource
from schemas.signal import Detection, Direction, SignalCandidate

logger = get_logger(__name__)


def pattern_label(pattern: str) -> str:
    """Formasyonun Turkce adi; sozlukte yoksa ham deger."""
    info = get_info_safe(pattern)
    return info.label if info else pattern.replace("_", " ")

_DIRECTION_EMOJI = {"LONG": "\U0001f4c8", "SHORT": "\U0001f4c9"}


@dataclass
class ScanResult:
    scanned: int = 0
    detections: int = 0
    saved: int = 0
    notified: int = 0
    skipped_duplicate: int = 0
    confirmed: int = 0
    alerts_fired: int = 0
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
            "confirmed": self.confirmed,
            "alerts_fired": self.alerts_fired,
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
        f"Skor: {candidate.final_score:.2f} | Güven: {detection.confidence:.2f}",
        f"Fiyat: {candidate.price:.2f}" if candidate.price is not None else "Fiyat: yok",
        f"İndikatör teyidi: {candidate.indicator_score:+.2f}",
        f"Haber duyarlılığı: {candidate.sentiment:+.2f}",
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
    mtf_score: float | None = None,
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
            mtf_score=mtf_score,
            final_score=compute_final_score(detection, indicator_score, sentiment, mtf_score),
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

    mtf_scores = await _mtf_scores(list(frames), target_interval)

    cutoff = cooldown_cutoff()
    for frame in frames.values():
        try:
            await _process_frame(
                frame,
                result,
                cutoff,
                send_notification,
                attach_chart,
                mtf_scores.get(frame.symbol.yf_ticker),
            )
        except Exception as exc:  # noqa: BLE001 - tek sembol hatasi taramayi durdurmaz
            logger.warning(
                "pipeline.symbol_failed", ticker=frame.symbol.yf_ticker, error=str(exc)
            )
            result.errors.append(f"{frame.symbol.yf_ticker}: {exc}")

    # Formasyon sekli bulundu; asil islem noktasi kirilimdir (Faz 6.1)
    try:
        result.confirmed = await check_breakouts(frames, send_notification=send_notification)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pipeline.breakout_check_failed", error=str(exc))
        result.errors.append(f"kirilim kontrolu: {exc}")

    try:
        result.alerts_fired = await check_alerts(frames, send_notification=send_notification)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pipeline.alert_check_failed", error=str(exc))
        result.errors.append(f"alarm kontrolu: {exc}")

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




async def _mtf_scores(tickers: list[str], interval: Interval) -> dict[str, float]:
    """Ust zaman diliminde trend teyidi (Faz 6.5).

    1h'te cikan LONG sinyali gunluk grafikte dusus trendindeyse skoru dusurulur.
    Veri alinamazsa bos doner; skorlama bu durumda MTF agirligini toplamdan duser.
    """
    settings = get_settings()
    higher = Interval(settings.mtf_interval)
    if not settings.mtf_enabled or not tickers or higher == interval:
        return {}

    try:
        frames = await fetch_many(
            [SymbolConfig.from_ticker(ticker, interval=higher) for ticker in tickers]
        )
    except Exception as exc:  # noqa: BLE001 - teyit yoksa akis surer
        logger.warning("pipeline.mtf_fetch_failed", error=str(exc))
        return {}

    scores = {
        ticker: trend_confirmation(frame.df)
        for ticker, frame in frames.items()
        if not frame.is_empty
    }
    logger.info("pipeline.mtf_ready", interval=higher.value, symbols=len(scores))
    return scores


def _breakout_hit(
    frame: OHLCVFrame, bucket_ts: datetime, level: float, direction: str, window: int
) -> tuple[float, float | None] | None:
    """Sinyalden sonraki mumlarda seviye asildi mi? (fiyat, hacim orani) doner."""
    reference = bucket_ts if bucket_ts.tzinfo else bucket_ts.replace(tzinfo=timezone.utc)
    future = frame.df[frame.df.index > reference].head(window)
    if future.empty:
        return None

    closes = future["close"]
    crossed = closes[closes > level] if direction == Direction.LONG.value else closes[closes < level]
    if crossed.empty:
        return None

    moment = crossed.index[0]
    volume_ratio: float | None = None
    try:
        enriched = compute_all(frame.df)
        if "volume_ratio" in enriched.columns and moment in enriched.index:
            value = enriched.loc[moment, "volume_ratio"]
            volume_ratio = None if value != value else round(float(value), 3)  # NaN kontrolu
    except Exception as exc:  # noqa: BLE001 - hacim orani opsiyonel
        logger.warning("pipeline.volume_ratio_failed", error=str(exc))

    return float(crossed.iloc[0]), volume_ratio


async def check_breakouts(
    frames: dict[str, OHLCVFrame], send_notification: bool = True
) -> int:
    """Bekleyen sinyallerde kirilim gerceklesti mi (Faz 6.1)."""
    settings = get_settings()
    rows = await db_manager.pending_breakouts(tickers=list(frames))
    confirmed = 0

    for signal, ticker in rows:
        frame = frames.get(ticker)
        if frame is None or frame.is_empty or signal.breakout_level is None:
            continue

        hit = _breakout_hit(
            frame,
            signal.bucket_ts,
            float(signal.breakout_level),
            signal.direction,
            settings.breakout_window_bars,
        )
        if hit is None:
            continue

        price, volume_ratio = hit
        if (
            settings.breakout_min_volume_ratio > 0
            and volume_ratio is not None
            and volume_ratio < settings.breakout_min_volume_ratio
        ):
            logger.info("pipeline.breakout_low_volume", ticker=ticker, ratio=volume_ratio)
            continue

        if await db_manager.mark_confirmed(signal.id, price, volume_ratio) is None:
            continue
        confirmed += 1

        if send_notification:
            await notify(_breakout_notification(signal, ticker, price, volume_ratio))

    if confirmed:
        logger.info("pipeline.breakouts_confirmed", count=confirmed)
    return confirmed


def _breakout_notification(signal, ticker: str, price: float, volume_ratio: float | None):
    up = signal.direction == Direction.LONG.value
    label = pattern_label(signal.pattern)
    emoji = "\U0001f680" if up else "\U0001f53b"
    lines = [
        f"{label} {'yukari' if up else 'asagi'} kirildi.",
        "",
        f"Kirilim fiyati: {price:.2f} (seviye {signal.breakout_level:.2f})",
    ]
    if volume_ratio is not None:
        lines.append(f"Hacim: ortalamanin {volume_ratio:.2f} kati")
    lines.append(f"Sinyal skoru: {signal.final_score:.2f}" if signal.final_score else "")
    return Notification(
        title=f"{emoji} {ticker} - KIRILIM ({signal.direction})",
        body="\n".join(line for line in lines if line != ""),
        priority=Priority.HIGH,
    )


async def check_alerts(frames: dict[str, OHLCVFrame], send_notification: bool = True) -> int:
    """Kullanici tanimli fiyat alarmlari (Faz 6.3). Tetiklenen alarm kapanir."""
    alerts = await db_manager.list_alerts(active_only=True)
    fired = 0

    for alert in alerts:
        frame = frames.get(alert.ticker)
        if frame is None or frame.is_empty:
            continue
        price = frame.latest_close
        if price is None:
            continue

        hit = price >= alert.price if alert.direction == "above" else price <= alert.price
        if not hit:
            continue

        if await db_manager.trigger_alert(alert.id, price) is None:
            continue
        fired += 1

        if send_notification:
            arrow = "\u25b2" if alert.direction == "above" else "\u25bc"
            body = [f"Fiyat {price:.2f} — alarm seviyesi {alert.price:.2f}"]
            if alert.note:
                body.append(f"Not: {alert.note}")
            await notify(
                Notification(
                    title=f"\U0001f514 {alert.ticker} {arrow} {alert.price:.2f}",
                    body="\n".join(body),
                    priority=Priority.HIGH,
                )
            )

    if fired:
        logger.info("pipeline.alerts_fired", count=fired)
    return fired


async def evaluate_outcomes(horizon: int | None = None, limit: int = 200) -> dict[str, int]:
    """Sinyalleri N mum sonrasina tasiyip sonucunu kaydeder (Faz 6.2)."""
    from core.backtest import evaluate_outcome

    settings = get_settings()
    bars = horizon or settings.outcome_horizon_bars
    rows = await db_manager.signals_awaiting_outcome(limit=limit)
    stats = {"pending": len(rows), "evaluated": 0, "not_ready": 0}

    cache: dict[tuple[str, str], OHLCVFrame | None] = {}
    for signal, ticker, interval in rows:
        key = (ticker, interval)
        if key not in cache:
            cache[key] = await db_manager.load_frame(ticker, interval=Interval(interval), limit=5000)
        frame = cache[key]
        if frame is None or frame.is_empty:
            stats["not_ready"] += 1
            continue

        outcome = evaluate_outcome(
            signal_id=signal.id,
            ticker=ticker,
            pattern=signal.pattern,
            direction=signal.direction,
            final_score=signal.final_score,
            bucket_ts=signal.bucket_ts,
            entry_price=signal.price_at_signal,
            frame=frame,
            horizon=bars,
        )
        if outcome is None:
            stats["not_ready"] += 1
            continue

        saved = await db_manager.save_outcome(
            signal_id=signal.id,
            horizon=bars,
            entry_price=outcome.entry_price,
            exit_price=outcome.exit_price,
            return_pct=outcome.return_pct,
        )
        if saved is not None:
            stats["evaluated"] += 1

    logger.info("pipeline.outcomes_evaluated", **stats)
    return stats


async def _alert_job_failure(job_name: str, error: str) -> None:
    """Job cokerse tum kanallara uyari gonderir (3.8); bildirim hatasi yutulur."""
    try:
        await notify(
            Notification(
                title=f"⚠️ İş hatası: {job_name}",
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
