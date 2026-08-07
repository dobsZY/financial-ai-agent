from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from core.logger import get_logger
from database import db_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    direction: str
    price: float
    note: str | None = None
    is_active: bool
    created_at: datetime
    triggered_at: datetime | None = None
    triggered_price: float | None = None


class AlertCreate(BaseModel):
    ticker: str
    direction: str = Field(pattern="^(above|below)$", description="above: üstüne çıkınca, below: altına inince")
    price: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=256)


@router.get("", response_model=list[AlertRead])
async def list_alerts(active_only: bool = Query(default=False)) -> list[AlertRead]:
    alerts = await db_manager.list_alerts(active_only=active_only)
    return [AlertRead.model_validate(alert) for alert in alerts]


@router.post("", response_model=AlertRead, status_code=status.HTTP_201_CREATED)
async def create_alert(payload: AlertCreate) -> AlertRead:
    """Fiyat alarmı kurar. Tetiklendiğinde bildirim gider ve alarm kapanır (tek atımlık)."""
    alert = await db_manager.create_alert(
        payload.ticker, payload.direction, payload.price, payload.note
    )
    return AlertRead.model_validate(alert)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_alert(alert_id: int) -> Response:
    if not await db_manager.delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alarm bulunamadı")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
