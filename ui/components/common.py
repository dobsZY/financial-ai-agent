from __future__ import annotations

import base64
from datetime import datetime, timezone

import flet as ft

PATTERN_LABELS: dict[str, str] = {
    "double_top": "Cift Tepe",
    "double_bottom": "Cift Dip",
    "head_shoulders": "Omuz Bas Omuz",
    "inv_head_shoulders": "Ters Omuz Bas Omuz",
    "asc_triangle": "Yukselen Ucgen",
    "desc_triangle": "Alcalan Ucgen",
    "bull_flag": "Boga Bayragi",
    "bear_flag": "Ayi Bayragi",
    "cup_handle": "Fincan Kulp",
}

RISK_LABELS: dict[str, str] = {"low": "Dusuk risk", "medium": "Orta risk", "high": "Yuksek risk"}

RISK_COLORS: dict[str, str] = {
    "low": ft.Colors.GREEN_400,
    "medium": ft.Colors.AMBER_400,
    "high": ft.Colors.RED_400,
}

STATUS_COLORS: dict[str, str] = {
    "success": ft.Colors.GREEN_400,
    "partial": ft.Colors.AMBER_400,
    "error": ft.Colors.RED_400,
    "running": ft.Colors.BLUE_300,
}


def pattern_label(pattern: str) -> str:
    return PATTERN_LABELS.get(pattern, pattern.replace("_", " ").title())


def direction_color(direction: str) -> str:
    return ft.Colors.GREEN_400 if direction == "LONG" else ft.Colors.RED_400


def direction_icon(direction: str) -> str:
    return ft.Icons.TRENDING_UP if direction == "LONG" else ft.Icons.TRENDING_DOWN


def score_color(score: float | None) -> str:
    if score is None:
        return ft.Colors.OUTLINE
    if score >= 0.75:
        return ft.Colors.GREEN_400
    if score >= 0.6:
        return ft.Colors.AMBER_400
    return ft.Colors.ORANGE_300


def sentiment_color(sentiment: float | None) -> str:
    if sentiment is None:
        return ft.Colors.OUTLINE
    if sentiment > 0.15:
        return ft.Colors.GREEN_400
    if sentiment < -0.15:
        return ft.Colors.RED_400
    return ft.Colors.BLUE_GREY_300


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def format_dt(value: str | None) -> str:
    parsed = parse_dt(value)
    if parsed is None:
        return "-"
    return parsed.astimezone().strftime("%d.%m %H:%M")


def relative_time(value: str | None) -> str:
    parsed = parse_dt(value)
    if parsed is None:
        return "-"
    delta = datetime.now(timezone.utc) - parsed
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "az once"
    if minutes < 60:
        return f"{minutes} dk once"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} sa once"
    return f"{hours // 24} gun once"


def to_base64(payload: bytes) -> str:
    """PNG baytlari -> base64 (yalnizca UI katmani; diske yazilmaz — K-02)."""
    return base64.b64encode(payload).decode("ascii")


def chip(text: str, color: str, icon: str | None = None) -> ft.Container:
    content: list[ft.Control] = []
    if icon:
        content.append(ft.Icon(icon, size=13, color=color))
    content.append(ft.Text(text, size=11, color=color, weight=ft.FontWeight.W_600))
    return ft.Container(
        content=ft.Row(content, spacing=4, tight=True),
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.12, color),
    )


def section_title(text: str, subtitle: str | None = None) -> ft.Control:
    controls: list[ft.Control] = [ft.Text(text, size=22, weight=ft.FontWeight.BOLD)]
    if subtitle:
        controls.append(ft.Text(subtitle, size=12, color=ft.Colors.ON_SURFACE_VARIANT))
    return ft.Column(controls, spacing=2)


def empty_state(message: str, icon: str = ft.Icons.INBOX) -> ft.Control:
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(icon, size=44, color=ft.Colors.OUTLINE),
                ft.Text(message, color=ft.Colors.ON_SURFACE_VARIANT, size=13),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        alignment=ft.alignment.center,
        padding=40,
    )
