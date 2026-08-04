from __future__ import annotations

from typing import Any

import httpx

from config.settings import get_settings
from core.logger import get_logger

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(60.0)


class ApiError(RuntimeError):
    """API'ye ulasilamadi veya hata dondu; UI bunu kullaniciya gosterir."""


class ApiClient:
    """FastAPI katmanina ince async istemci. UI dogrudan DB'ye dokunmaz."""

    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        host = settings.api_host if settings.api_host != "0.0.0.0" else "127.0.0.1"  # noqa: S104
        self.base_url = base_url or f"http://{host}:{settings.api_port}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=TIMEOUT, transport=transport
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(f"API'ye ulasilamadi ({self.base_url}): {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:200]
            raise ApiError(f"{method} {url} -> {response.status_code}: {detail}")
        return response

    async def _get_json(self, url: str, **params: Any) -> Any:
        clean = {key: value for key, value in params.items() if value is not None}
        response = await self._request("GET", url, params=clean)
        return response.json()

    async def health(self) -> dict[str, Any]:
        return await self._get_json("/health")

    async def signals(
        self, limit: int = 50, ticker: str | None = None, min_score: float | None = None
    ) -> list[dict[str, Any]]:
        return await self._get_json("/signals", limit=limit, ticker=ticker, min_score=min_score)

    async def news(self, limit: int = 50, ticker: str | None = None) -> list[dict[str, Any]]:
        return await self._get_json("/news", limit=limit, ticker=ticker)

    async def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._get_json("/jobs", limit=limit)

    async def symbols(self, active_only: bool = False) -> list[dict[str, Any]]:
        return await self._get_json("/symbols", active_only=active_only)

    async def add_symbol(self, ticker: str, interval: str = "1h") -> dict[str, Any]:
        response = await self._request(
            "POST", "/symbols", json={"ticker": ticker, "interval": interval}
        )
        return response.json()

    async def set_symbol_active(self, ticker: str, is_active: bool) -> dict[str, Any]:
        response = await self._request(
            "PATCH", f"/symbols/{ticker}", json={"is_active": is_active}
        )
        return response.json()

    async def delete_symbol(self, ticker: str) -> None:
        await self._request("DELETE", f"/symbols/{ticker}")

    async def trigger_scan(
        self, tickers: list[str] | None = None, background: bool = True
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"background": background}
        if tickers:
            payload["tickers"] = tickers
        response = await self._request("POST", "/scan", json=payload)
        return response.json()

    async def trigger_news_poll(self) -> dict[str, Any]:
        response = await self._request("POST", "/news/poll", params={"background": True})
        return response.json()

    async def chart_png(
        self,
        ticker: str,
        interval: str = "1h",
        width: int | None = None,
        height: int | None = None,
        candles: int = 120,
    ) -> bytes | None:
        """Grafik PNG'si; hata durumunda None doner (UI placeholder gosterir)."""
        params = {"interval": interval, "candles": candles}
        if width:
            params["width"] = width
        if height:
            params["height"] = height
        try:
            response = await self._request("GET", f"/charts/{ticker}", params=params)
        except ApiError as exc:
            logger.warning("ui.chart_unavailable", ticker=ticker, error=str(exc))
            return None
        return response.content
