from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.pattern_glossary import DETECTION_CAVEAT, DISCLAIMER, all_info, get_info_safe
from schemas.signal import PatternInfo

router = APIRouter(tags=["patterns"])


@router.get("/patterns", response_model=list[PatternInfo])
async def list_patterns() -> list[PatternInfo]:
    """Tum formasyonlarin aciklamasi (sozluk)."""
    return all_info()


@router.get("/patterns/notes")
async def pattern_notes() -> dict[str, str]:
    """Her aciklamanin yaninda gosterilmesi gereken uyarilar."""
    return {"disclaimer": DISCLAIMER, "detection_caveat": DETECTION_CAVEAT}


@router.get("/patterns/{pattern}", response_model=PatternInfo)
async def get_pattern(pattern: str) -> PatternInfo:
    """Tek bir formasyonun aciklamasi: ne demek, nasil teyit edilir, nerede gecersiz."""
    info = get_info_safe(pattern)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Bilinmeyen formasyon: {pattern}")
    return info
