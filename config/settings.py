from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    log_json: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    database_url: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'finance.db').as_posix()}"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    llm_daily_call_limit: int = 500

    pushover_token: str = ""
    pushover_user: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    scan_concurrency: int = 5
    min_confidence: float = 0.55
    signal_cooldown_minutes: int = 240
    intraday_interval: str = "1h"
    bist_symbols: str = ""
    nasdaq_symbols: str = ""

    weight_vision: float = 0.5
    weight_sentiment: float = 0.3
    weight_indicator: float = 0.2

    yolo_model_path: str = "models/yolov8n.pt"
    chart_width: int = 640
    chart_height: int = 640

    sec_user_agent: str = "financial-ai-agent contact@example.com"

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def bist_tickers(self) -> list[str]:
        return self._split_csv(self.bist_symbols)

    @property
    def nasdaq_tickers(self) -> list[str]:
        return self._split_csv(self.nasdaq_symbols)

    @property
    def all_symbols(self) -> list[str]:
        return [*self.bist_tickers, *self.nasdaq_tickers]

    @property
    def pushover_enabled(self) -> bool:
        return bool(self.pushover_token and self.pushover_user)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
