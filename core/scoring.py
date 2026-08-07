from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config.settings import get_settings
from schemas.market import INTERVAL_MINUTES, Interval
from schemas.signal import Detection, Direction


def directional_sentiment(sentiment: float, direction: Direction) -> float:
    """Haber duyarliligini formasyon yonuyle hizalar.

    LONG sinyalde olumlu haber destekleyicidir; SHORT sinyalde olumsuz haber
    destekleyicidir. Zit yonlu haber skoru dusurur.
    """
    aligned = sentiment if direction is Direction.LONG else -sentiment
    return max(-1.0, min(1.0, aligned))


def compute_final_score(
    detection: Detection,
    indicator_score: float = 0.0,
    sentiment: float = 0.0,
    mtf_score: float | None = None,
) -> float:
    """`w1*vision + w2*sentiment + w3*indicator` -> 0..1 araligina normalize edilir.

    `indicator_score` ve `sentiment` -1..1; formasyon guveni 0..1 oldugundan
    yonle hizalanmis skorlar [0,1] araligina tasinir.
    """
    settings = get_settings()
    direction = detection.resolved_direction

    vision_part = detection.confidence
    sentiment_part = (directional_sentiment(sentiment, direction) + 1.0) / 2.0

    aligned_indicator = indicator_score if direction is Direction.LONG else -indicator_score
    indicator_part = (max(-1.0, min(1.0, aligned_indicator)) + 1.0) / 2.0

    total_weight = settings.weight_vision + settings.weight_sentiment + settings.weight_indicator
    weighted = (
        settings.weight_vision * vision_part
        + settings.weight_sentiment * sentiment_part
        + settings.weight_indicator * indicator_part
    )

    # Ust zaman dilimi teyidi yalnizca veri varsa hesaba katilir; yoksa agirligi
    # toplama eklenmez, boylece veri eksikligi skoru cezalandirmaz.
    if mtf_score is not None and settings.weight_mtf > 0:
        aligned_mtf = mtf_score if direction is Direction.LONG else -mtf_score
        mtf_part = (max(-1.0, min(1.0, aligned_mtf)) + 1.0) / 2.0
        weighted += settings.weight_mtf * mtf_part
        total_weight += settings.weight_mtf

    if total_weight <= 0:
        return round(vision_part, 4)

    return round(max(0.0, min(1.0, weighted / total_weight)), 4)


def bucket_timestamp(moment: datetime, interval: Interval) -> datetime:
    """Zamani interval kovasina yuvarlar; ayni mumda tekrar sinyal uretilmez (K-08)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)

    minutes = INTERVAL_MINUTES.get(interval, 60)
    if minutes >= 1440:
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)

    floored_minute = (moment.hour * 60 + moment.minute) // minutes * minutes
    return moment.replace(
        hour=floored_minute // 60, minute=floored_minute % 60, second=0, microsecond=0
    )


def cooldown_cutoff(moment: datetime | None = None) -> datetime:
    reference = moment or datetime.now(timezone.utc)
    return reference - timedelta(minutes=get_settings().signal_cooldown_minutes)


def should_notify(final_score: float) -> bool:
    return final_score >= get_settings().min_notify_score
