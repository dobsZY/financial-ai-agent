from __future__ import annotations

import flet as ft
import httpx
import pytest

from core import pattern_glossary as glossary
from main import app
from schemas.signal import Direction, Pattern, PATTERN_DIRECTION
from ui.components import pattern_sheet


def test_every_pattern_has_an_entry() -> None:
    """Yeni formasyon eklenirse sozluk kaydi da eklenmeli."""
    covered = {info.pattern for info in glossary.all_info()}
    assert covered == set(Pattern)


def test_directions_match_pattern_table() -> None:
    """Sozlukteki yon, PATTERN_DIRECTION ile celismemeli."""
    for info in glossary.all_info():
        assert info.direction is PATTERN_DIRECTION[info.pattern], info.pattern


@pytest.mark.parametrize("field", ["forms", "implication", "confirmation", "invalidation",
                                   "target", "pitfalls", "summary"])
def test_no_empty_sections(field: str) -> None:
    for info in glossary.all_info():
        value = getattr(info, field)
        assert len(value) > 20, f"{info.pattern.value}.{field} cok kisa"


def test_confirmation_states_a_direction() -> None:
    """Teyit metni hangi yone kapanis gerektigini acikca soylemeli."""
    for info in glossary.all_info():
        text = info.confirmation.upper()
        assert "ÜSTÜNDE" in text or "ALTINDA" in text, info.pattern.value


def test_family_values_are_known() -> None:
    assert {info.family for info in glossary.all_info()} <= {"dönüş", "devam"}


def test_lookup_accepts_string_and_enum() -> None:
    assert glossary.get_info("double_top").label == "Çift Tepe"
    assert glossary.get_info(Pattern.DOUBLE_TOP).label == "Çift Tepe"
    assert glossary.get_info(" DOUBLE_TOP ".strip().lower()).direction is Direction.SHORT


def test_unknown_pattern_is_safe() -> None:
    assert glossary.get_info_safe("yok_boyle_formasyon") is None
    with pytest.raises((KeyError, ValueError)):
        glossary.get_info("yok_boyle_formasyon")


def test_short_meaning_for_notifications() -> None:
    assert glossary.short_meaning(Pattern.ASC_TRIANGLE).startswith("Direnç sabit")
    assert glossary.short_meaning("bilinmeyen") == ""


# --- API ---------------------------------------------------------------


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_endpoint_returns_all(client: httpx.AsyncClient) -> None:
    response = await client.get("/patterns")

    assert response.status_code == 200
    assert len(response.json()) == len(Pattern)


async def test_detail_endpoint(client: httpx.AsyncClient) -> None:
    response = await client.get("/patterns/head_shoulders")

    assert response.status_code == 200
    payload = response.json()
    assert payload["label"] == "Omuz Baş Omuz"
    assert payload["direction"] == "SHORT"
    assert "boyun çizgisi" in payload["confirmation"].lower()


async def test_detail_endpoint_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/patterns/yok_boyle")).status_code == 404


async def test_notes_endpoint_carries_warnings(client: httpx.AsyncClient) -> None:
    payload = (await client.get("/patterns/notes")).json()

    assert "yatırım tavsiyesi değildir" in payload["disclaimer"]
    assert "kırılımın" in payload["detection_caveat"]


# --- UI bileseni -------------------------------------------------------


def test_dialog_builds_with_all_sections() -> None:
    info = glossary.get_info(Pattern.BULL_FLAG).model_dump(mode="json")
    notes = {"disclaimer": "uyari", "detection_caveat": "not"}

    dialog = pattern_sheet.build_dialog(info, notes, "GARAN.IS", lambda d: None)

    assert isinstance(dialog, ft.AlertDialog)
    body = dialog.content.content
    # 6 bolum + 2 uyari notu
    assert len(body.controls) == 8


def test_dialog_without_notes_omits_warning_boxes() -> None:
    info = glossary.get_info(Pattern.CUP_HANDLE).model_dump(mode="json")

    dialog = pattern_sheet.build_dialog(info, None, None, lambda d: None)

    assert len(dialog.content.content.controls) == 6


def test_header_shows_expected_direction() -> None:
    info = glossary.get_info(Pattern.DOUBLE_TOP).model_dump(mode="json")

    header = pattern_sheet.build_header(info, "ASELS.IS")
    chips = header.controls[1].controls

    assert "AŞAĞI" in chips[0].content.controls[-1].value
    assert chips[1].content.controls[-1].value == "Trend dönüşü"


def test_unavailable_dialog_names_the_pattern() -> None:
    dialog = pattern_sheet.unavailable_dialog("garip_formasyon", lambda d: None)

    assert "garip_formasyon" in dialog.content.value
