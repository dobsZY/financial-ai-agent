from __future__ import annotations

from typing import Any, Callable, Coroutine

import flet as ft

from ui.api_client import ApiClient
from ui.components.common import (
    chip,
    direction_color,
    direction_icon,
    format_dt,
    pattern_label,
    relative_time,
    score_color,
    to_base64,
)

THUMB_WIDTH = 260
THUMB_HEIGHT = 150


class SignalCard(ft.Card):
    """Sinyal karti (4.2): sembol, formasyon, guven, yon, zaman, mini grafik."""

    def __init__(
        self,
        signal: dict[str, Any],
        client: ApiClient,
        on_open_chart: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
        on_explain: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self.signal = signal
        self._client = client
        self._on_open_chart = on_open_chart
        self._on_explain = on_explain
        self._thumb = ft.Container(
            content=ft.ProgressRing(width=18, height=18, stroke_width=2),
            width=THUMB_WIDTH,
            height=THUMB_HEIGHT,
            alignment=ft.alignment.center,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
        )
        super().__init__(content=self._build(), elevation=1)

    # --- gorunum ---

    def _build(self) -> ft.Control:
        signal = self.signal
        direction = signal.get("direction", "LONG")
        score = signal.get("final_score")
        confidence = signal.get("confidence", 0.0)
        price = signal.get("price_at_signal")

        header = ft.Row(
            [
                ft.Icon(direction_icon(direction), color=direction_color(direction), size=22),
                ft.Text(signal.get("ticker", "?"), size=17, weight=ft.FontWeight.BOLD),
                chip(direction, direction_color(direction)),
                ft.Container(expand=True),
                ft.Text(
                    relative_time(signal.get("created_at")),
                    size=11,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ],
            spacing=8,
        )

        details = ft.Column(
            [
                self._pattern_row(),
                ft.Row(
                    [
                        chip(f"Skor {score:.2f}" if score is not None else "Skor -", score_color(score)),
                        chip(f"Guven %{confidence * 100:.0f}", ft.Colors.BLUE_300),
                    ],
                    spacing=6,
                ),
                ft.Text(
                    f"Fiyat: {price:.2f}" if price is not None else "Fiyat: -",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Text(
                    f"Mum: {format_dt(signal.get('bucket_ts'))}",
                    size=11,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                self._notified_badge(),
                ft.ProgressBar(
                    value=score or 0.0,
                    bar_height=5,
                    color=score_color(score),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE),
                ),
            ],
            spacing=6,
            expand=True,
        )

        chart_button = ft.TextButton(
            "Buyuk grafik",
            icon=ft.Icons.ZOOM_IN,
            on_click=lambda _: self.page.run_task(self._on_open_chart, self.signal),
        )

        return ft.Container(
            content=ft.Column(
                [
                    header,
                    ft.Row(
                        [details, ft.Column([self._thumb, chart_button], spacing=2)],
                        spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
                spacing=10,
            ),
            padding=14,
        )

    def _pattern_row(self) -> ft.Control:
        """Formasyon adi + 'bu ne demek?' dugmesi (aciklama diyalogunu acar)."""
        label = ft.Text(pattern_label(self.signal.get("pattern", "")), size=14)
        if self._on_explain is None:
            return label

        return ft.Row(
            [
                label,
                ft.IconButton(
                    ft.Icons.HELP_OUTLINE,
                    icon_size=16,
                    tooltip="Bu formasyon ne anlama geliyor?",
                    style=ft.ButtonStyle(padding=2),
                    on_click=lambda _: self.page.run_task(self._on_explain, self.signal),
                ),
            ],
            spacing=2,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _notified_badge(self) -> ft.Control:
        if self.signal.get("notified_at"):
            return chip("Bildirildi", ft.Colors.GREEN_300, ft.Icons.NOTIFICATIONS_ACTIVE)
        return chip("Bildirim yok", ft.Colors.BLUE_GREY_300, ft.Icons.NOTIFICATIONS_OFF)

    # --- veri ---

    async def load_thumbnail(self) -> None:
        """Mini grafigi arka planda yukler; basarisiz olursa ikon gosterir."""
        payload = await self._client.chart_png(
            self.signal.get("ticker", ""),
            width=THUMB_WIDTH * 2,
            height=THUMB_HEIGHT * 2,
            candles=60,
        )
        if payload is None:
            self._thumb.content = ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED, color=ft.Colors.OUTLINE)
        else:
            self._thumb.content = ft.Image(
                src_base64=to_base64(payload),
                width=THUMB_WIDTH,
                height=THUMB_HEIGHT,
                fit=ft.ImageFit.CONTAIN,
                border_radius=8,
            )
        if self.page is not None:
            self._thumb.update()
