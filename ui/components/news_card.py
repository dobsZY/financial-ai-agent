from __future__ import annotations

from typing import Any

import flet as ft

from ui.components.common import (
    RISK_COLORS,
    RISK_LABELS,
    chip,
    format_dt,
    sentiment_color,
)


def sentiment_badge(sentiment: float | None) -> ft.Control:
    """Duyarlilik rozeti (4.5): -1..1 -> renk + isaretli deger."""
    if sentiment is None:
        return chip("Ozet yok", ft.Colors.OUTLINE, ft.Icons.HOURGLASS_EMPTY)

    if sentiment > 0.15:
        icon, label = ft.Icons.SENTIMENT_SATISFIED, "Olumlu"
    elif sentiment < -0.15:
        icon, label = ft.Icons.SENTIMENT_DISSATISFIED, "Olumsuz"
    else:
        icon, label = ft.Icons.SENTIMENT_NEUTRAL, "Notr"

    return chip(f"{label} {sentiment:+.2f}", sentiment_color(sentiment), icon)


class NewsCard(ft.Card):
    """Haber + LLM ozeti karti (4.5)."""

    def __init__(self, item: dict[str, Any]) -> None:
        self.item = item
        super().__init__(content=self._build(), elevation=1)

    def _build(self) -> ft.Control:
        item = self.item
        risk = item.get("risk_level")
        bullets = item.get("bullets") or []

        header = ft.Row(
            [
                chip(item.get("source", "?"), ft.Colors.BLUE_300, ft.Icons.ARTICLE),
                ft.Text(item.get("ticker") or "-", size=14, weight=ft.FontWeight.BOLD),
                sentiment_badge(item.get("sentiment")),
                *([chip(RISK_LABELS.get(risk, risk), RISK_COLORS.get(risk, ft.Colors.OUTLINE))]
                  if risk else []),
                ft.Container(expand=True),
                ft.Text(
                    format_dt(item.get("published_at") or item.get("created_at")),
                    size=11,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ],
            spacing=8,
            wrap=True,
        )

        body: list[ft.Control] = [
            header,
            ft.Text(item.get("title", ""), size=14, weight=ft.FontWeight.W_500),
        ]

        if bullets:
            body.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.CIRCLE, size=6, color=ft.Colors.ON_SURFACE_VARIANT),
                                ft.Text(bullet, size=12, expand=True),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        )
                        for bullet in bullets
                    ],
                    spacing=4,
                )
            )
        else:
            body.append(
                ft.Text(
                    "LLM ozeti yok (Gemini anahtari veya gunluk kota).",
                    size=11,
                    italic=True,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                )
            )

        if item.get("url"):
            body.append(
                ft.TextButton(
                    "Kaynagi ac",
                    icon=ft.Icons.OPEN_IN_NEW,
                    url=item["url"],
                )
            )

        return ft.Container(content=ft.Column(body, spacing=8), padding=14)
