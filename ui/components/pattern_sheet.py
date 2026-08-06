from __future__ import annotations

from typing import Any

import flet as ft

from ui.components.common import chip, direction_color, direction_icon

FAMILY_LABELS = {"donus": "Trend donusu", "devam": "Trend devami"}

# Aciklama bolumleri: (anahtar, baslik, ikon)
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("forms", "Nasil olusur", ft.Icons.TIMELINE),
    ("implication", "Ne anlama gelir", ft.Icons.PSYCHOLOGY_ALT),
    ("confirmation", "Teyit kosulu", ft.Icons.CHECK_CIRCLE_OUTLINE),
    ("invalidation", "Nerede gecersiz olur", ft.Icons.CANCEL_OUTLINED),
    ("target", "Hedef hesabi", ft.Icons.FLAG_OUTLINED),
    ("pitfalls", "Sik yapilan hata", ft.Icons.WARNING_AMBER_ROUNDED),
)

SECTION_COLORS = {
    "confirmation": ft.Colors.GREEN_300,
    "invalidation": ft.Colors.RED_300,
    "pitfalls": ft.Colors.AMBER_300,
}


def _section(key: str, title: str, icon: str, text: str) -> ft.Control:
    color = SECTION_COLORS.get(key, ft.Colors.BLUE_200)
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Icon(icon, size=15, color=color),
                    ft.Text(title, size=11, weight=ft.FontWeight.W_700, color=color),
                ],
                spacing=7,
            ),
            ft.Text(text, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
        ],
        spacing=5,
    )


def build_header(info: dict[str, Any], ticker: str | None = None) -> ft.Control:
    direction = info.get("direction", "LONG")
    family = FAMILY_LABELS.get(info.get("family", ""), info.get("family", ""))
    title = info.get("label", info.get("pattern", "?"))

    return ft.Column(
        [
            ft.Row(
                [
                    ft.Icon(direction_icon(direction), color=direction_color(direction), size=22),
                    ft.Text(
                        f"{ticker} · {title}" if ticker else title,
                        size=19,
                        weight=ft.FontWeight.BOLD,
                    ),
                ],
                spacing=8,
            ),
            ft.Row(
                [
                    chip(
                        f"Beklenen yon: {'YUKARI' if direction == 'LONG' else 'ASAGI'}",
                        direction_color(direction),
                    ),
                    chip(family, ft.Colors.BLUE_GREY_300),
                ],
                spacing=6,
            ),
            ft.Text(info.get("summary", ""), size=14, weight=ft.FontWeight.W_500),
        ],
        spacing=9,
        tight=True,
    )


def build_body(info: dict[str, Any], notes: dict[str, str] | None = None) -> ft.Control:
    """Aciklama govdesi: bolumler + uyari notlari."""
    notes = notes or {}
    controls: list[ft.Control] = [
        _section(key, title, icon, info[key]) for key, title, icon in SECTIONS if info.get(key)
    ]

    for note_key, icon in (("detection_caveat", ft.Icons.INFO_OUTLINE),
                           ("disclaimer", ft.Icons.GAVEL)):
        text = notes.get(note_key)
        if not text:
            continue
        controls.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon, size=14, color=ft.Colors.OUTLINE),
                        ft.Text(text, size=11, color=ft.Colors.OUTLINE, expand=True),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                padding=10,
                border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
            )
        )

    return ft.Column(controls, spacing=15, scroll=ft.ScrollMode.AUTO, tight=True)


def build_dialog(
    info: dict[str, Any],
    notes: dict[str, str] | None,
    ticker: str | None,
    on_close,
) -> ft.AlertDialog:
    """Formasyon aciklama diyalogu (karta tiklandiginda acilir)."""
    dialog = ft.AlertDialog(
        title=build_header(info, ticker),
        content=ft.Container(content=build_body(info, notes), width=560, height=460),
    )
    dialog.actions = [ft.TextButton("Kapat", on_click=lambda _: on_close(dialog))]
    return dialog


def unavailable_dialog(pattern: str, on_close) -> ft.AlertDialog:
    dialog = ft.AlertDialog(
        title=ft.Text("Aciklama bulunamadi"),
        content=ft.Text(f"'{pattern}' formasyonu icin sozlukte kayit yok."),
    )
    dialog.actions = [ft.TextButton("Kapat", on_click=lambda _: on_close(dialog))]
    return dialog
