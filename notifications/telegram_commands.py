"""Telegram komut dinleyicisi (Faz 6.4).

Bot su ana kadar tek yonluydu (yalnizca bildirim gonderiyordu). Bu modul
`getUpdates` uzun yoklamasiyla gelen komutlari isler; webhook gerekmez, bu yuzden
yerel makinede public URL olmadan calisir.

Guvenlik: yalnizca `.env`'deki `TELEGRAM_CHAT_ID` ile eslesen sohbetten gelen
mesajlara yanit verilir; baska hicbir gonderen islenmez.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from config.settings import get_settings
from core.logger import get_logger
from notifications.telegram_service import _api_url

logger = get_logger(__name__)

HELP_TEXT = (
    "Kullanılabilir komutlar:\n"
    "/durum — sistem sağlığı ve son iş\n"
    "/sinyaller — son 5 sinyal\n"
    "/tara — hemen tarama başlat\n"
    "/canli SEMBOL — anlık fiyat ve indikatörler\n"
    "/alarm SEMBOL FIYAT — fiyat alarmı kur\n"
    "/alarmlar — açık alarmlar\n"
    "/istatistik — isabet oranı özeti\n"
    "/yardim — bu liste"
)


async def _send(client: httpx.AsyncClient, chat_id: str, text: str) -> None:
    settings = get_settings()
    try:
        await client.post(
            _api_url(settings.telegram_bot_token, "sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )
    except httpx.HTTPError as exc:
        logger.warning("telegram.command_reply_failed", error=str(exc))


async def handle_command(text: str) -> str:
    """Komut metnini yanita cevirir. Ag katmanindan bagimsiz, test edilebilir."""
    from core import pipeline
    from core.stats import build_stats
    from database import db_manager

    parts = text.strip().split()
    if not parts:
        return HELP_TEXT
    command = parts[0].lower().lstrip("/").split("@")[0]
    args = parts[1:]

    if command in {"start", "yardim", "help"}:
        return HELP_TEXT

    if command == "durum":
        jobs = await db_manager.list_job_runs(limit=1)
        signals = await db_manager.list_signals(limit=100)
        alerts = await db_manager.list_alerts(active_only=True)
        last = f"{jobs[0].job_name} · {jobs[0].status}" if jobs else "kayıt yok"
        return (
            f"<b>Sistem durumu</b>\n"
            f"Sinyal: {len(signals)}\n"
            f"Açık alarm: {len(alerts)}\n"
            f"Son iş: {last}"
        )

    if command == "sinyaller":
        rows = await db_manager.list_signals(limit=5)
        if not rows:
            return "Kayıtlı sinyal yok."
        lines = ["<b>Son sinyaller</b>"]
        for signal, ticker in rows:
            mark = "✅" if signal.confirmed_at else "⏳"
            lines.append(
                f"{mark} {ticker} · {pipeline.pattern_label(signal.pattern)} · "
                f"{signal.direction} · {signal.final_score:.2f}"
            )
        return "\n".join(lines)

    if command == "tara":
        result = await pipeline.run_tracked_scan("telegram_scan")
        return (
            f"<b>Tarama bitti</b>\n"
            f"Taranan: {result.scanned}\nYeni sinyal: {result.saved}\n"
            f"Bildirim: {result.notified}\nKırılım: {result.confirmed}"
        )

    if command in {"canli", "canlı"}:
        if not args:
            return "Kullanım: /canli GARAN.IS"
        from api.routes.quotes import get_quote

        try:
            quote = await get_quote(args[0])
        except Exception as exc:  # noqa: BLE001 - kullaniciya sade mesaj
            return f"Fiyat alınamadı: {exc}"
        arrow = "▲" if quote.change >= 0 else "▼"
        rsi = quote.indicators.get("rsi")
        return (
            f"<b>{quote.ticker}</b> {quote.price:.2f} {arrow} "
            f"{quote.change:+.2f} ({quote.change_pct:+.2f}%)\n"
            f"Yüksek {quote.high:.2f} · Düşük {quote.low:.2f}\n"
            f"RSI: {rsi:.1f}" if rsi is not None else ""
        ).strip()

    if command == "alarm":
        if len(args) < 2:
            return "Kullanım: /alarm GARAN.IS 130"
        try:
            price = float(args[1].replace(",", "."))
        except ValueError:
            return "Fiyat sayısal olmalı: /alarm GARAN.IS 130"

        from api.routes.quotes import get_quote

        try:
            quote = await get_quote(args[0])
            direction = "above" if price > quote.price else "below"
            current = f" (şu an {quote.price:.2f})"
        except Exception:  # noqa: BLE001 - fiyat alinamazsa yon varsayilir
            direction, current = "above", ""

        alert = await db_manager.create_alert(args[0], direction, price)
        yon = "üstüne çıkarsa" if direction == "above" else "altına inerse"
        return f"🔔 {alert.ticker} {alert.price:.2f} {yon} haber verilecek{current}"

    if command == "alarmlar":
        alerts = await db_manager.list_alerts(active_only=True)
        if not alerts:
            return "Açık alarm yok."
        lines = ["<b>Açık alarmlar</b>"]
        for alert in alerts:
            arrow = "▲" if alert.direction == "above" else "▼"
            lines.append(f"{arrow} {alert.ticker} {alert.price:.2f}")
        return "\n".join(lines)

    if command in {"istatistik", "istatistikler"}:
        report = build_stats(await db_manager.outcome_rows())
        if not report.evaluated:
            return "Henüz değerlendirilmiş sinyal yok."
        lines = [
            "<b>İsabet istatistiği</b>",
            f"Değerlendirilen: {report.evaluated}",
            f"İsabet: %{report.hit_rate * 100:.1f}",
            f"Ortalama getiri: %{report.avg_return_pct:+.2f}",
        ]
        for group in report.by_pattern[:5]:
            lines.append(
                f"· {group.label}: %{group.hit_rate * 100:.0f} ({group.count})"
            )
        return "\n".join(lines)

    return f"Bilinmeyen komut: {command}\n\n{HELP_TEXT}"


async def poll_commands(stop_event: asyncio.Event) -> None:
    """getUpdates uzun yoklamasi; uygulama kapanana kadar surer."""
    settings = get_settings()
    if not settings.telegram_enabled or not settings.telegram_commands_enabled:
        logger.info("telegram.commands_disabled")
        return

    token, chat_id = settings.telegram_bot_token, str(settings.telegram_chat_id)
    offset: int | None = None
    timeout = settings.telegram_poll_timeout
    logger.info("telegram.commands_started", timeout=timeout)

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 10)) as client:
        while not stop_event.is_set():
            try:
                params: dict[str, Any] = {"timeout": timeout}
                if offset is not None:
                    params["offset"] = offset
                response = await client.get(_api_url(token, "getUpdates"), params=params)
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("telegram.poll_failed", error=str(exc))
                await asyncio.sleep(5)
                continue

            for update in payload.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message") or {}
                text = (message.get("text") or "").strip()
                sender = str((message.get("chat") or {}).get("id", ""))

                if not text or sender != chat_id:
                    if sender and sender != chat_id:
                        logger.warning("telegram.unauthorized_chat", chat=sender)
                    continue

                logger.info("telegram.command_received", command=text.split()[0])
                try:
                    reply = await handle_command(text)
                except Exception as exc:  # noqa: BLE001 - komut hatasi botu dusurmez
                    logger.warning("telegram.command_failed", error=str(exc))
                    reply = f"Komut çalıştırılamadı: {exc}"
                await _send(client, chat_id, reply)

    logger.info("telegram.commands_stopped")
