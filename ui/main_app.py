"""Flet dashboard (Faz 4).

Calistirma:  flet run ui/main_app.py     (API ayri terminalde: python main.py)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Awaitable, Callable

import flet as ft

from config.settings import get_settings
from core.logger import get_logger, setup_logging
from ui.api_client import ApiClient, ApiError
from ui.components.common import (
    STATUS_COLORS,
    chip,
    empty_state,
    parse_dt,
    pattern_label,
    relative_time,
    section_title,
    to_base64,
)
from ui.components.news_card import NewsCard
from ui.components.signal_card import SignalCard

logger = get_logger(__name__)

SIGNAL_LIMIT = 30
NEWS_LIMIT = 30
JOB_LIMIT = 15


class Dashboard:
    """Sol navigasyon + icerik alani; her gorunum kendi verisini API'den ceker."""

    def __init__(self, page: ft.Page, client: ApiClient) -> None:
        self.page = page
        self.client = client
        self.selected_index = 0
        self.auto_refresh = True

        self.body = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
        self.status_text = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
        self.progress = ft.ProgressBar(visible=False, bar_height=2)
        self.min_score_field = ft.TextField(
            label="Min skor",
            value="",
            width=110,
            dense=True,
            hint_text="0.60",
            on_submit=lambda _: self.page.run_task(self.refresh),
        )

    # ------------------------------------------------------------------ duzen

    def build(self) -> ft.Control:
        rail = ft.NavigationRail(
            selected_index=self.selected_index,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=76,
            min_extended_width=190,
            group_alignment=-0.9,
            destinations=[
                ft.NavigationRailDestination(icon=ft.Icons.SHOW_CHART, label="Sinyaller"),
                ft.NavigationRailDestination(icon=ft.Icons.LIST_ALT, label="Izleme"),
                ft.NavigationRailDestination(icon=ft.Icons.ARTICLE, label="Haberler"),
                ft.NavigationRailDestination(icon=ft.Icons.MONITOR_HEART, label="Sistem"),
            ],
            on_change=self._on_nav_change,
        )

        header = ft.Row(
            [
                ft.Icon(ft.Icons.CANDLESTICK_CHART, color=ft.Colors.BLUE_300),
                ft.Text("Financial Command Center", size=16, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                self.status_text,
                ft.Switch(
                    label="Oto yenile",
                    value=True,
                    on_change=self._on_auto_toggle,
                    scale=0.85,
                ),
                ft.IconButton(
                    ft.Icons.REFRESH,
                    tooltip="Simdi yenile",
                    on_click=lambda _: self.page.run_task(self.refresh),
                ),
            ],
            spacing=10,
        )

        return ft.Row(
            [
                rail,
                ft.VerticalDivider(width=1),
                ft.Column(
                    [header, self.progress, ft.Divider(height=1), self.body],
                    expand=True,
                    spacing=8,
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _on_nav_change(self, event: ft.ControlEvent) -> None:
        self.selected_index = event.control.selected_index
        self.page.run_task(self.refresh)

    def _on_auto_toggle(self, event: ft.ControlEvent) -> None:
        self.auto_refresh = bool(event.control.value)

    def _set_body(self, controls: list[ft.Control]) -> None:
        self.body.controls = controls
        self.body.update()

    def _notify(self, message: str) -> None:
        self.page.open(ft.SnackBar(ft.Text(message)))

    # ------------------------------------------------------------- yenileme

    async def refresh(self) -> None:
        loaders: list[Callable[[], Awaitable[None]]] = [
            self._load_signals,
            self._load_watchlist,
            self._load_news,
            self._load_system,
        ]
        self.progress.visible = True
        self.progress.update()
        try:
            await loaders[self.selected_index]()
            self.status_text.value = f"Guncellendi {datetime.now().strftime('%H:%M:%S')}"
        except ApiError as exc:
            logger.warning("ui.api_error", error=str(exc))
            self._set_body([self._api_error(str(exc))])
            self.status_text.value = "API'ye ulasilamiyor"
        finally:
            self.progress.visible = False
            self.progress.update()
            self.status_text.update()

    async def auto_refresh_loop(self, seconds: int) -> None:
        """4.7: periyodik polling; kullanici kapatirsa dongu bos doner."""
        while True:
            await asyncio.sleep(seconds)
            if self.auto_refresh:
                await self.refresh()

    def _api_error(self, detail: str) -> ft.Control:
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.CLOUD_OFF, color=ft.Colors.RED_300),
                                ft.Text("API'ye baglanilamadi", weight=ft.FontWeight.BOLD),
                            ],
                            spacing=8,
                        ),
                        ft.Text(
                            "Ayri bir terminalde `python main.py` calistigindan emin ol.",
                            size=12,
                        ),
                        ft.Text(detail, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.FilledButton(
                            "Tekrar dene",
                            icon=ft.Icons.REFRESH,
                            on_click=lambda _: self.page.run_task(self.refresh),
                        ),
                    ],
                    spacing=10,
                ),
                padding=18,
            )
        )

    # -------------------------------------------------------------- sinyaller

    async def _load_signals(self) -> None:
        min_score = None
        raw = (self.min_score_field.value or "").strip().replace(",", ".")
        if raw:
            try:
                min_score = max(0.0, min(1.0, float(raw)))
            except ValueError:
                self._notify("Min skor sayisal olmali (orn. 0.6)")

        signals = await self.client.signals(limit=SIGNAL_LIMIT, min_score=min_score)

        toolbar = ft.Row(
            [
                section_title("Sinyaller", f"Son {len(signals)} kayit"),
                ft.Container(expand=True),
                self.min_score_field,
                ft.FilledTonalButton(
                    "Tarama baslat",
                    icon=ft.Icons.PLAY_ARROW,
                    on_click=lambda _: self.page.run_task(self._trigger_scan),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        if not signals:
            self._set_body([toolbar, empty_state("Henuz sinyal yok. Bir tarama baslat.")])
            return

        cards = [SignalCard(signal, self.client, self._open_chart) for signal in signals]
        grid = ft.ResponsiveRow(
            [ft.Container(card, col={"sm": 12, "lg": 6}) for card in cards],
            run_spacing=10,
        )
        self._set_body([toolbar, grid])

        for card in cards:
            self.page.run_task(card.load_thumbnail)

    async def _open_chart(self, signal: dict[str, Any]) -> None:
        """4.3: PNG -> base64, yalnizca UI katmaninda; diske yazilmaz."""
        ticker = signal.get("ticker", "")
        image_area = ft.Container(
            content=ft.ProgressRing(),
            width=760,
            height=480,
            alignment=ft.alignment.center,
        )
        dialog = ft.AlertDialog(
            title=ft.Text(f"{ticker} - {pattern_label(signal.get('pattern', ''))}"),
            content=image_area,
        )
        dialog.actions = [ft.TextButton("Kapat", on_click=lambda _: self.page.close(dialog))]
        self.page.open(dialog)

        payload = await self.client.chart_png(ticker, width=1520, height=960, candles=150)
        image_area.content = (
            ft.Image(src_base64=to_base64(payload), fit=ft.ImageFit.CONTAIN)
            if payload
            else ft.Text("Grafik uretilemedi (veri yok).")
        )
        image_area.update()

    async def _trigger_scan(self, tickers: list[str] | None = None) -> None:
        try:
            await self.client.trigger_scan(tickers=tickers, background=True)
        except ApiError as exc:
            self._notify(f"Tarama baslatilamadi: {exc}")
            return
        self._notify("Tarama arka planda basladi; birkac saniye sonra yenile.")

    # ---------------------------------------------------------- izleme listesi

    async def _load_watchlist(self) -> None:
        symbols = await self.client.symbols()
        ticker_field = ft.TextField(
            label="Sembol ekle",
            hint_text="THYAO.IS veya AAPL",
            width=220,
            dense=True,
        )
        interval_dropdown = ft.Dropdown(
            label="Periyot",
            value="1h",
            width=110,
            dense=True,
            options=[ft.dropdown.Option(value) for value in ("5m", "15m", "30m", "1h", "1d")],
        )

        async def add(_: ft.ControlEvent | None = None) -> None:
            ticker = (ticker_field.value or "").strip()
            if not ticker:
                self._notify("Once sembol kodu gir.")
                return
            try:
                await self.client.add_symbol(ticker, interval_dropdown.value or "1h")
            except ApiError as exc:
                self._notify(f"Eklenemedi: {exc}")
                return
            ticker_field.value = ""
            self._notify(f"{ticker.upper()} eklendi.")
            await self.refresh()

        toolbar = ft.Row(
            [
                section_title("Izleme Listesi", f"{len(symbols)} sembol"),
                ft.Container(expand=True),
                ticker_field,
                interval_dropdown,
                ft.FilledButton("Ekle", icon=ft.Icons.ADD, on_click=lambda e: self.page.run_task(add)),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        if not symbols:
            self._set_body([toolbar, empty_state("Izleme listesi bos.", ft.Icons.LIST_ALT)])
            return

        rows = [self._symbol_row(symbol) for symbol in symbols]
        self._set_body([toolbar, ft.Column(rows, spacing=8)])

    def _symbol_row(self, symbol: dict[str, Any]) -> ft.Control:
        ticker = symbol["ticker"]

        async def toggle(value: bool) -> None:
            try:
                await self.client.set_symbol_active(ticker, value)
            except ApiError as exc:
                self._notify(f"Guncellenemedi: {exc}")
                return
            self._notify(f"{ticker} {'aktif' if value else 'pasif'}.")

        async def remove() -> None:
            try:
                await self.client.delete_symbol(ticker)
            except ApiError as exc:
                self._notify(f"Silinemedi: {exc}")
                return
            self._notify(f"{ticker} silindi.")
            await self.refresh()

        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CANDLESTICK_CHART, size=18, color=ft.Colors.BLUE_200),
                        ft.Text(ticker, weight=ft.FontWeight.BOLD, width=110),
                        chip(symbol.get("market", "?"), ft.Colors.BLUE_GREY_300),
                        chip(symbol.get("interval", "1h"), ft.Colors.PURPLE_200),
                        ft.Container(expand=True),
                        ft.Switch(
                            value=symbol.get("is_active", True),
                            tooltip="Taramaya dahil",
                            on_change=lambda e: self.page.run_task(toggle, bool(e.control.value)),
                        ),
                        ft.IconButton(
                            ft.Icons.PLAY_ARROW,
                            tooltip="Sadece bunu tara",
                            on_click=lambda _: self.page.run_task(self._trigger_scan, [ticker]),
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE_OUTLINE,
                            icon_color=ft.Colors.RED_300,
                            tooltip="Listeden cikar",
                            on_click=lambda _: self.page.run_task(remove),
                        ),
                    ],
                    spacing=10,
                ),
                padding=ft.padding.symmetric(horizontal=14, vertical=8),
            )
        )

    # ---------------------------------------------------------------- haberler

    async def _load_news(self) -> None:
        items = await self.client.news(limit=NEWS_LIMIT)
        toolbar = ft.Row(
            [
                section_title("Haberler", f"{len(items)} bildirim"),
                ft.Container(expand=True),
                ft.FilledTonalButton(
                    "Yoklama baslat",
                    icon=ft.Icons.CLOUD_DOWNLOAD,
                    on_click=lambda _: self.page.run_task(self._trigger_news_poll),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        if not items:
            self._set_body(
                [toolbar, empty_state("Kayitli haber yok. KAP/SEC yoklamasi baslat.", ft.Icons.ARTICLE)]
            )
            return

        cards = ft.ResponsiveRow(
            [ft.Container(NewsCard(item), col={"sm": 12, "lg": 6}) for item in items],
            run_spacing=10,
        )
        self._set_body([toolbar, cards])

    async def _trigger_news_poll(self) -> None:
        try:
            await self.client.trigger_news_poll()
        except ApiError as exc:
            self._notify(f"Yoklama baslatilamadi: {exc}")
            return
        self._notify("KAP/SEC yoklamasi arka planda basladi.")

    # ----------------------------------------------------------------- sistem

    async def _load_system(self) -> None:
        health = await self.client.health()
        jobs = await self.client.jobs(limit=JOB_LIMIT)
        integrations = health.get("integrations", {})

        status_cards = ft.ResponsiveRow(
            [
                ft.Container(
                    self._stat_card(
                        "Scheduler",
                        "Calisiyor" if health.get("scheduler_running") else "Durdu",
                        ft.Icons.SCHEDULE,
                        ft.Colors.GREEN_400 if health.get("scheduler_running") else ft.Colors.RED_400,
                        f"{health.get('jobs', 0)} is kayitli",
                    ),
                    col={"sm": 6, "md": 3},
                ),
                ft.Container(
                    self._stat_card(
                        "Izleme listesi",
                        str(health.get("watchlist_size", 0)),
                        ft.Icons.LIST_ALT,
                        ft.Colors.BLUE_300,
                        "sembol",
                    ),
                    col={"sm": 6, "md": 3},
                ),
                ft.Container(
                    self._stat_card(
                        "Bildirim",
                        "Telegram" if integrations.get("telegram") else "Kapali",
                        ft.Icons.SEND,
                        ft.Colors.GREEN_400 if integrations.get("telegram") else ft.Colors.ORANGE_300,
                        "Pushover acik" if integrations.get("pushover") else "Pushover kapali",
                    ),
                    col={"sm": 6, "md": 3},
                ),
                ft.Container(
                    self._stat_card(
                        "Gemini",
                        "Bagli" if integrations.get("gemini") else "Anahtar yok",
                        ft.Icons.AUTO_AWESOME,
                        ft.Colors.GREEN_400 if integrations.get("gemini") else ft.Colors.ORANGE_300,
                        health.get("env", ""),
                    ),
                    col={"sm": 6, "md": 3},
                ),
            ],
            run_spacing=10,
        )

        controls: list[ft.Control] = [
            section_title("Sistem Sagligi", "Son is calistirmalari (job_runs)"),
            status_cards,
        ]
        controls.append(self._job_table(jobs) if jobs else empty_state("Henuz is kaydi yok.", ft.Icons.HISTORY))
        self._set_body(controls)

    def _stat_card(
        self, title: str, value: str, icon: str, color: str, subtitle: str
    ) -> ft.Control:
        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(icon, color=color, size=18),
                                ft.Text(title, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ],
                            spacing=6,
                        ),
                        ft.Text(value, size=18, weight=ft.FontWeight.BOLD, color=color),
                        ft.Text(subtitle, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=4,
                ),
                padding=14,
            )
        )

    def _job_table(self, jobs: list[dict[str, Any]]) -> ft.Control:
        rows = []
        for job in jobs:
            status = job.get("status", "?")
            duration = "-"
            started, finished = job.get("started_at"), job.get("finished_at")
            if started and finished:
                start_dt, end_dt = parse_dt(started), parse_dt(finished)
                if start_dt and end_dt:
                    duration = f"{(end_dt - start_dt).total_seconds():.1f} sn"

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(job.get("job_name", "?"), size=12)),
                        ft.DataCell(chip(status, STATUS_COLORS.get(status, ft.Colors.OUTLINE))),
                        ft.DataCell(ft.Text(relative_time(started), size=12)),
                        ft.DataCell(ft.Text(duration, size=12)),
                        ft.DataCell(ft.Text(str(job.get("items_processed", 0)), size=12)),
                        ft.DataCell(
                            ft.Text(
                                (job.get("error_text") or "-")[:60],
                                size=11,
                                color=ft.Colors.RED_200 if job.get("error_text") else None,
                            )
                        ),
                    ]
                )
            )

        return ft.Column(
            [
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Is", size=12)),
                        ft.DataColumn(ft.Text("Durum", size=12)),
                        ft.DataColumn(ft.Text("Baslangic", size=12)),
                        ft.DataColumn(ft.Text("Sure", size=12)),
                        ft.DataColumn(ft.Text("Islenen", size=12)),
                        ft.DataColumn(ft.Text("Hata", size=12)),
                    ],
                    rows=rows,
                    heading_row_height=36,
                    data_row_max_height=44,
                )
            ],
            scroll=ft.ScrollMode.AUTO,
        )


async def main(page: ft.Page) -> None:
    settings = get_settings()

    page.title = "AI Financial Command Center"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)
    page.padding = 10
    page.window.width = 1360
    page.window.height = 880

    client = ApiClient()
    dashboard = Dashboard(page, client)

    async def on_disconnect(_: Any = None) -> None:
        await client.close()

    page.on_disconnect = on_disconnect
    page.add(dashboard.build())

    await dashboard.refresh()
    page.run_task(dashboard.auto_refresh_loop, settings.ui_refresh_seconds)


if __name__ == "__main__":
    setup_logging()
    ft.app(target=main)
