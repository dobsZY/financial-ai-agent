from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.data_fetcher import fetch_many
from core.indicators import indicator_snapshot
from core.logger import get_logger
from database import db_manager
from schemas.market import Interval, QuoteRead, SymbolConfig

logger = get_logger(__name__)

router = APIRouter(tags=["quotes"])


@router.get("/quote/{ticker}", response_model=QuoteRead)
async def get_quote(
    ticker: str,
    interval: Interval = Interval.H1,
    persist: bool = True,
) -> QuoteRead:
    """Sembolün canlı fiyat anlık görüntüsü.

    Veriyi her çağrıda kaynaktan çeker (önbellek yok) — canlı takip görünümü
    bunu periyodik olarak yeniler. `persist=True` iken çekilen mumlar DB'ye de
    yazılır, böylece grafik ucu da tazelenmiş olur.
    """
    config = SymbolConfig.from_ticker(ticker, interval=interval)

    try:
        frames = await fetch_many([config])
    except Exception as exc:  # noqa: BLE001 - saglayici hatasi 502'ye cevrilir
        logger.warning("quote.fetch_failed", ticker=ticker, error=str(exc))
        raise HTTPException(status_code=502, detail="Fiyat kaynağına ulaşılamadı") from exc

    frame = frames.get(config.yf_ticker)
    if frame is None or frame.is_empty:
        raise HTTPException(status_code=404, detail="Sembol için veri bulunamadı")

    if persist:
        try:
            await db_manager.save_frames([frame])
        except Exception as exc:  # noqa: BLE001 - yazma hatasi fiyati dondurmeyi engellemez
            logger.warning("quote.persist_failed", ticker=ticker, error=str(exc))

    df = frame.df
    last = df.iloc[-1]
    price = float(last["close"])
    previous = float(df["close"].iloc[-2]) if len(df) > 1 else price
    change = price - previous

    return QuoteRead(
        ticker=config.yf_ticker,
        market=config.market.value,
        interval=interval.value,
        price=round(price, 4),
        previous_close=round(previous, 4),
        change=round(change, 4),
        change_pct=round(change / previous * 100.0, 3) if previous else 0.0,
        high=round(float(last["high"]), 4),
        low=round(float(last["low"]), 4),
        volume=float(last["volume"]),
        last_candle_ts=frame.last_timestamp,  # type: ignore[arg-type]
        is_stale=frame.is_stale(),
        indicators=indicator_snapshot(df),
    )
