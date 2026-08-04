from __future__ import annotations

from datetime import datetime, timezone

from config.settings import get_settings
from core import scoring
from schemas.market import Interval
from schemas.signal import Detection, Direction, Pattern


def _detection(pattern: Pattern, confidence: float = 0.8) -> Detection:
    return Detection(pattern=pattern, confidence=confidence, source="test")


def test_directional_sentiment_flips_for_short() -> None:
    assert scoring.directional_sentiment(0.6, Direction.LONG) == 0.6
    assert scoring.directional_sentiment(0.6, Direction.SHORT) == -0.6


def test_positive_news_lifts_long_signal() -> None:
    detection = _detection(Pattern.BULL_FLAG)
    neutral = scoring.compute_final_score(detection, indicator_score=0.0, sentiment=0.0)
    bullish = scoring.compute_final_score(detection, indicator_score=0.5, sentiment=0.8)
    bearish = scoring.compute_final_score(detection, indicator_score=-0.5, sentiment=-0.8)

    assert bearish < neutral < bullish
    assert 0.0 <= bearish and bullish <= 1.0


def test_short_pattern_rewards_negative_news() -> None:
    detection = _detection(Pattern.DOUBLE_TOP)
    with_bad_news = scoring.compute_final_score(detection, sentiment=-0.9)
    with_good_news = scoring.compute_final_score(detection, sentiment=0.9)
    assert with_bad_news > with_good_news


def test_bucket_timestamp_floors_to_interval() -> None:
    moment = datetime(2026, 8, 4, 14, 47, 31, tzinfo=timezone.utc)
    assert scoring.bucket_timestamp(moment, Interval.H1) == datetime(
        2026, 8, 4, 14, 0, tzinfo=timezone.utc
    )
    assert scoring.bucket_timestamp(moment, Interval.M15) == datetime(
        2026, 8, 4, 14, 45, tzinfo=timezone.utc
    )
    assert scoring.bucket_timestamp(moment, Interval.D1) == datetime(
        2026, 8, 4, 0, 0, tzinfo=timezone.utc
    )


def test_bucket_timestamp_assumes_utc_for_naive() -> None:
    naive = datetime(2026, 8, 4, 14, 47)
    assert scoring.bucket_timestamp(naive, Interval.H1).tzinfo is timezone.utc


def test_cooldown_cutoff_uses_settings() -> None:
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    delta = now - scoring.cooldown_cutoff(now)
    assert delta.total_seconds() / 60 == get_settings().signal_cooldown_minutes


def test_should_notify_threshold() -> None:
    threshold = get_settings().min_notify_score
    assert scoring.should_notify(threshold)
    assert not scoring.should_notify(threshold - 0.01)
