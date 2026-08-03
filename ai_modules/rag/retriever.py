from __future__ import annotations

from core.indicators import indicator_snapshot, trend_confirmation
from schemas.market import OHLCVFrame
from schemas.signal import Detection


def _format_number(value: float | None, digits: int = 2) -> str:
    return "yok" if value is None else f"{value:.{digits}f}"


def build_market_context(
    frame: OHLCVFrame | None = None,
    detections: list[Detection] | None = None,
) -> str:
    """Haber ozetlemesine fiyat/indikator/formasyon baglamini enjekte eder (2.9)."""
    if frame is None or frame.is_empty:
        return "Baglam verisi yok."

    snapshot = indicator_snapshot(frame.df)
    change_pct = _recent_change(frame)

    lines = [
        f"Sembol: {frame.symbol.yf_ticker} ({frame.symbol.market.value}, {frame.interval.value})",
        f"Son kapanis: {_format_number(snapshot['close'])}",
        f"Son 5 mum degisimi: {_format_number(change_pct)}%",
        f"RSI(14): {_format_number(snapshot['rsi'], 1)}",
        f"EMA50: {_format_number(snapshot.get('ema_50'))} | "
        f"EMA200: {_format_number(snapshot.get('ema_200'))}",
        f"MACD histogram: {_format_number(snapshot['macd_hist'], 4)}",
        f"Hacim / 20 mum ortalamasi: {_format_number(snapshot['volume_ratio'])}",
        f"Indikator trend skoru (-1..1): {trend_confirmation(frame.df):.2f}",
    ]

    if detections:
        formations = ", ".join(
            f"{item.pattern.value} ({item.resolved_direction.value}, "
            f"guven {item.confidence:.2f})"
            for item in detections
        )
        lines.append(f"Tespit edilen formasyonlar: {formations}")
    else:
        lines.append("Tespit edilen formasyon: yok")

    return "\n".join(lines)


def _recent_change(frame: OHLCVFrame, bars: int = 5) -> float | None:
    closes = frame.df["close"]
    if len(closes) < bars + 1:
        return None
    previous = float(closes.iloc[-(bars + 1)])
    if previous == 0.0:
        return None
    return (float(closes.iloc[-1]) - previous) / previous * 100.0
