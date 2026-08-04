from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy import func, select

from ai_modules.base import PatternAnalyzer
from core import pipeline
from database import db_manager
from database.models import JobRun
from database.models import LLMSummary as LLMSummaryRow
from database.models import Signal
from notifications.base import Notification
from schemas.market import Interval, OHLCVFrame
from schemas.signal import Detection, Pattern


class _FakeAnalyzer(PatternAnalyzer):
    name = "fake"

    def __init__(self, detections: list[Detection], fail: bool = False) -> None:
        self._detections = detections
        self._fail = fail

    async def analyze(self, frame: OHLCVFrame) -> list[Detection]:
        if self._fail:
            raise RuntimeError("analizci coktu")
        return list(self._detections)


@dataclass
class _NotifySpy:
    sent: list[Notification] = field(default_factory=list)
    succeed: bool = True

    async def __call__(self, notification: Notification, fan_out: bool = False) -> list[str]:
        self.sent.append(notification)
        return ["telegram"] if self.succeed else []


def _detection(confidence: float = 0.95, pattern: Pattern = Pattern.BULL_FLAG) -> Detection:
    return Detection(pattern=pattern, confidence=confidence, source="fake")


async def _async_value(value: str) -> str:
    return value


@pytest.fixture
def notify_spy(monkeypatch: pytest.MonkeyPatch) -> _NotifySpy:
    spy = _NotifySpy()
    monkeypatch.setattr(pipeline, "notify", spy)
    return spy


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch, frame: OHLCVFrame) -> None:
    """Tum dis bagimliliklari (veri cekme, indikator, grafik) sabitler."""

    async def fake_fetch_many(configs, **kwargs):
        return {config.yf_ticker: frame for config in configs}

    monkeypatch.setattr(pipeline, "fetch_many", fake_fetch_many)
    monkeypatch.setattr(pipeline, "trend_confirmation", lambda df: 0.0)


def _use_analyzers(monkeypatch: pytest.MonkeyPatch, *analyzers: PatternAnalyzer) -> None:
    monkeypatch.setattr(pipeline, "available_analyzers", lambda: list(analyzers))


async def test_scan_produces_signal_and_single_notification(
    monkeypatch: pytest.MonkeyPatch,
    stub_pipeline: None,
    notify_spy: _NotifySpy,
    clean_db: None,
) -> None:
    _use_analyzers(monkeypatch, _FakeAnalyzer([_detection()]))

    result = await pipeline.run_scan(
        tickers=["AAPL"], interval=Interval.H1, attach_chart=False
    )

    assert result.scanned == 1
    assert result.saved == 1
    assert result.notified == 1
    assert len(notify_spy.sent) == 1
    assert "AAPL" in notify_spy.sent[0].title

    async with db_manager.session_scope() as session:
        signal = (await session.execute(select(Signal))).scalar_one()
    assert signal.notified_at is not None
    assert signal.final_score is not None and signal.final_score > 0.6


async def test_second_scan_is_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
    stub_pipeline: None,
    notify_spy: _NotifySpy,
    clean_db: None,
) -> None:
    _use_analyzers(monkeypatch, _FakeAnalyzer([_detection()]))

    async def scan() -> pipeline.ScanResult:
        return await pipeline.run_scan(
            tickers=["AAPL"], interval=Interval.H1, attach_chart=False
        )

    first = await scan()
    second = await scan()

    assert first.saved == 1
    assert second.saved == 0
    assert second.skipped_duplicate == 1
    assert len(notify_spy.sent) == 1, "K-08: ayni formasyon icin tekrar bildirim gonderilmemeli"

    async with db_manager.session_scope() as session:
        count = await session.scalar(select(func.count()).select_from(Signal))
    assert count == 1


async def test_low_score_signal_is_saved_but_not_notified(
    monkeypatch: pytest.MonkeyPatch,
    stub_pipeline: None,
    notify_spy: _NotifySpy,
    clean_db: None,
) -> None:
    # 0.6 guven -> skor 0.55; min_confidence'i gecer ama min_notify_score'un altinda kalir
    _use_analyzers(monkeypatch, _FakeAnalyzer([_detection(confidence=0.6)]))

    result = await pipeline.run_scan(
        tickers=["AAPL"], interval=Interval.H1, attach_chart=False
    )

    assert result.saved == 1
    assert result.notified == 0
    assert notify_spy.sent == []


async def test_low_confidence_detection_is_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
    stub_pipeline: None,
    notify_spy: _NotifySpy,
    clean_db: None,
) -> None:
    _use_analyzers(monkeypatch, _FakeAnalyzer([_detection(confidence=0.2)]))

    result = await pipeline.run_scan(
        tickers=["AAPL"], interval=Interval.H1, attach_chart=False
    )

    assert result.detections == 0
    assert result.saved == 0


async def test_failing_analyzer_does_not_break_scan(
    monkeypatch: pytest.MonkeyPatch,
    stub_pipeline: None,
    notify_spy: _NotifySpy,
    clean_db: None,
) -> None:
    _use_analyzers(
        monkeypatch,
        _FakeAnalyzer([], fail=True),
        _FakeAnalyzer([_detection(pattern=Pattern.CUP_HANDLE)]),
    )

    result = await pipeline.run_scan(
        tickers=["AAPL"], interval=Interval.H1, attach_chart=False
    )

    assert result.saved == 1, "K-03: bir analizcinin hatasi digerlerini dusurmemeli"


async def test_missing_data_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, notify_spy: _NotifySpy, frame: OHLCVFrame, clean_db: None
) -> None:
    async def partial_fetch(configs, **kwargs):
        return {configs[0].yf_ticker: frame}

    monkeypatch.setattr(pipeline, "fetch_many", partial_fetch)
    monkeypatch.setattr(pipeline, "trend_confirmation", lambda df: 0.0)
    _use_analyzers(monkeypatch, _FakeAnalyzer([]))

    result = await pipeline.run_scan(
        tickers=["AAPL", "THYAO.IS"], interval=Interval.H1, attach_chart=False
    )

    assert result.scanned == 1
    assert any("THYAO.IS" in error for error in result.errors)


async def test_chart_failure_does_not_block_notification(
    monkeypatch: pytest.MonkeyPatch,
    stub_pipeline: None,
    notify_spy: _NotifySpy,
    clean_db: None,
) -> None:
    async def broken_chart(frame: OHLCVFrame):
        raise RuntimeError("mplfinance hatasi")

    monkeypatch.setattr(pipeline, "render_chart", broken_chart)
    _use_analyzers(monkeypatch, _FakeAnalyzer([_detection()]))

    result = await pipeline.run_scan(tickers=["AAPL"], interval=Interval.H1, attach_chart=True)

    assert result.notified == 1
    assert notify_spy.sent[0].image_png is None


async def test_notification_failure_leaves_signal_unmarked(
    monkeypatch: pytest.MonkeyPatch,
    stub_pipeline: None,
    notify_spy: _NotifySpy,
    clean_db: None,
) -> None:
    notify_spy.succeed = False
    _use_analyzers(monkeypatch, _FakeAnalyzer([_detection()]))

    result = await pipeline.run_scan(
        tickers=["AAPL"], interval=Interval.H1, attach_chart=False
    )

    assert result.saved == 1
    assert result.notified == 0
    async with db_manager.session_scope() as session:
        signal = (await session.execute(select(Signal))).scalar_one()
    assert signal.notified_at is None


async def test_only_open_markets_filters_closed_sessions(
    monkeypatch: pytest.MonkeyPatch, notify_spy: _NotifySpy, clean_db: None
) -> None:
    monkeypatch.setattr(pipeline, "filter_open_tickers", lambda tickers: [])

    result = await pipeline.run_scan(tickers=["AAPL"], only_open_markets=True)

    assert result.scanned == 0


async def test_tracked_scan_records_job_run(
    monkeypatch: pytest.MonkeyPatch,
    stub_pipeline: None,
    notify_spy: _NotifySpy,
    clean_db: None,
) -> None:
    _use_analyzers(monkeypatch, _FakeAnalyzer([_detection()]))

    await pipeline.run_tracked_scan(
        "intraday_scan_nasdaq", tickers=["AAPL"], interval=Interval.H1, attach_chart=False
    )

    async with db_manager.session_scope() as session:
        job = (await session.execute(select(JobRun))).scalar_one()
    assert job.job_name == "intraday_scan_nasdaq"
    assert job.status == "success"
    assert job.items_processed == 1
    assert job.finished_at is not None


async def test_tracked_scan_logs_error_and_alerts(
    monkeypatch: pytest.MonkeyPatch, notify_spy: _NotifySpy, clean_db: None
) -> None:
    async def boom(**kwargs):
        raise RuntimeError("veri kaynagi coktu")

    monkeypatch.setattr(pipeline, "run_scan", boom)

    result = await pipeline.run_tracked_scan("eod_scan_bist", tickers=["AAPL"])

    assert result.errors
    async with db_manager.session_scope() as session:
        job = (await session.execute(select(JobRun))).scalar_one()
    assert job.status == "error"
    assert "veri kaynagi coktu" in (job.error_text or "")
    assert len(notify_spy.sent) == 1, "3.8: job hatasi uyari bildirimi uretmeli"


async def test_news_poll_persists_summary(
    monkeypatch: pytest.MonkeyPatch, notify_spy: _NotifySpy, clean_db: None
) -> None:
    """Haber kaydedilir ve LLM ozeti ayni habere baglanir (attach_summary yolu)."""
    from schemas.news import LLMSummary, NewsItem, NewsSource, RiskLevel

    item = NewsItem(
        source=NewsSource.KAP,
        external_id="998",
        title="GARANTI temettu aciklamasi",
        ticker="GARAN.IS",
    )
    summary = LLMSummary(
        sentiment=0.5,
        bullets=["Temettu aciklandi", "Nakit akisi guclu", "Risk dusuk"],
        risk_level=RiskLevel.LOW,
        model="test-model",
        tokens=42,
    )

    async def fake_kap(**kwargs):
        return [item]

    async def fake_summarize(news_item, context):
        return summary

    monkeypatch.setattr("scrapers.kap_scraper.fetch_disclosures", fake_kap)
    monkeypatch.setattr(pipeline, "summarize_safe", fake_summarize)
    monkeypatch.setattr(pipeline, "_news_context", lambda item: _async_value("baglam"))

    stats = await pipeline.run_news_poll(tickers=["GARAN.IS"])

    assert stats == {"fetched": 1, "new": 1, "summarized": 1, "errors": 0}

    async with db_manager.session_scope() as session:
        stored = (await session.execute(select(LLMSummaryRow))).scalar_one()
    assert stored.sentiment == 0.5
    assert stored.model == "test-model"
    assert "Temettu aciklandi" in stored.bullets_json

    # Ayni haber tekrar gelirse yeniden ozetlenmez (K-08 + LLM maliyeti)
    second = await pipeline.run_news_poll(tickers=["GARAN.IS"])
    assert second["new"] == 0
    assert second["summarized"] == 0


async def test_backfill_summarizes_only_pending_news(
    monkeypatch: pytest.MonkeyPatch, notify_spy: _NotifySpy, clean_db: None
) -> None:
    """Kota kesintisinde ozetsiz kalan haberler sonradan tamamlanir."""
    from schemas.news import LLMSummary, NewsItem, NewsSource, RiskLevel

    summarized_ids: list[str] = []

    async def fake_summarize(item, context):
        summarized_ids.append(item.external_id)
        return LLMSummary(
            sentiment=-0.2,
            bullets=["Madde 1", "Madde 2", "Madde 3"],
            risk_level=RiskLevel.MEDIUM,
            model="test-model",
        )

    monkeypatch.setattr(pipeline, "summarize_safe", fake_summarize)
    monkeypatch.setattr(pipeline, "_news_context", lambda item: _async_value("baglam"))

    # Biri ozetli, ikisi ozetsiz kaydedilir
    for index in range(3):
        item = NewsItem(
            source=NewsSource.SEC,
            external_id=f"pending-{index}",
            title=f"Haber {index}",
            ticker="AAPL",
        )
        summary = (
            LLMSummary(sentiment=0.1, bullets=["var"], model="onceki") if index == 0 else None
        )
        async with db_manager.session_scope() as session:
            await db_manager.save_news_item(session, item, summary)

    stats = await pipeline.backfill_summaries(limit=10)

    assert stats == {"pending": 2, "summarized": 2, "failed": 0}
    assert sorted(summarized_ids) == ["pending-1", "pending-2"]
    assert await db_manager.news_without_summary() == []

    # Tekrar calistirilirsa yapacak is kalmaz (LLM cagrisi yok)
    assert await pipeline.backfill_summaries() == {"pending": 0, "summarized": 0, "failed": 0}
    assert len(summarized_ids) == 2


async def test_backfill_counts_llm_failures(
    monkeypatch: pytest.MonkeyPatch, notify_spy: _NotifySpy, clean_db: None
) -> None:
    from schemas.news import NewsItem, NewsSource

    async def failing_summarize(item, context):
        return None

    monkeypatch.setattr(pipeline, "summarize_safe", failing_summarize)
    monkeypatch.setattr(pipeline, "_news_context", lambda item: _async_value("baglam"))

    async with db_manager.session_scope() as session:
        await db_manager.save_news_item(
            session,
            NewsItem(source=NewsSource.KAP, external_id="x1", title="Haber", ticker="THYAO.IS"),
        )

    stats = await pipeline.backfill_summaries()

    assert stats == {"pending": 1, "summarized": 0, "failed": 1}
    assert len(await db_manager.news_without_summary()) == 1, "Basarisiz haber kuyrukta kalmali"


async def test_tracked_news_poll_records_job_run(
    monkeypatch: pytest.MonkeyPatch, notify_spy: _NotifySpy, clean_db: None
) -> None:
    async def fake_poll(**kwargs):
        return {"fetched": 4, "new": 2, "summarized": 2, "errors": 0}

    monkeypatch.setattr(pipeline, "run_news_poll", fake_poll)

    stats = await pipeline.run_tracked_news_poll()

    assert stats["new"] == 2
    async with db_manager.session_scope() as session:
        job = (await session.execute(select(JobRun))).scalar_one()
    assert job.job_name == "news_poll"
    assert job.items_processed == 4
    assert job.status == "success"
