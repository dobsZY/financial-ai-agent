from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from core.logger import get_logger
from database import db_manager
from schemas.market import SymbolCreate, SymbolRead, SymbolUpdate

logger = get_logger(__name__)

router = APIRouter(prefix="/symbols", tags=["symbols"])


@router.get("", response_model=list[SymbolRead])
async def list_symbols(active_only: bool = False) -> list[SymbolRead]:
    symbols = await db_manager.list_symbols(active_only=active_only)
    return [SymbolRead.model_validate(symbol) for symbol in symbols]


@router.post("", response_model=SymbolRead, status_code=status.HTTP_201_CREATED)
async def create_symbol(payload: SymbolCreate) -> SymbolRead:
    """Izleme listesine ekler; ayni ticker tekrar gonderilirse mevcut kayit doner."""
    symbol = await db_manager.add_symbol(
        payload.ticker, interval=payload.interval, name=payload.name
    )
    return SymbolRead.model_validate(symbol)


@router.patch("/{ticker}", response_model=SymbolRead)
async def update_symbol(ticker: str, payload: SymbolUpdate) -> SymbolRead:
    symbol = await db_manager.update_symbol(
        ticker, is_active=payload.is_active, interval=payload.interval, name=payload.name
    )
    if symbol is None:
        raise HTTPException(status_code=404, detail="Sembol bulunamadı")
    return SymbolRead.model_validate(symbol)


@router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_symbol(ticker: str) -> Response:
    if not await db_manager.delete_symbol(ticker):
        raise HTTPException(status_code=404, detail="Sembol bulunamadı")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
