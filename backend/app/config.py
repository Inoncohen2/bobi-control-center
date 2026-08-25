"""Application settings, loaded from the environment.

Secrets live here and nowhere else. Nothing in this module is serialised into an
API response — the settings endpoint builds its own masked view.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BOBI_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    adapter: Literal["mock", "real"] = Field(
        default="mock",
        description="Which HomeAssistantAdapter to serve. Phase 1 ships 'mock'.",
    )
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # --- Home Assistant (Phase 2 only) ------------------------------------
    ha_url: str = ""
    ha_token: str = ""
    ha_verify_ssl: bool = True

    data_dir: Path = Path("./data")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string as well as a real list."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_mock(self) -> bool:
        return self.adapter == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
