"""Application settings.

The Supervisor token lives here and nowhere else. It is never serialised into a
response, never logged, and never sent to the frontend.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Home Assistant Core, reached through the Supervisor proxy. This is the only
#: base URL used when running as an app; it needs no configuration.
SUPERVISOR_API_BASE = "http://supervisor/core/api"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BOBI_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: "auto" picks the real bridge when SUPERVISOR_TOKEN is present and falls
    #: back to mock otherwise. Explicit values are honoured for tests and local
    #: development.
    adapter: Literal["auto", "mock", "real"] = "auto"

    host: str = "0.0.0.0"
    port: int = 8099
    log_level: str = "info"

    #: Logs bridge request/response bodies. Off by default so household data is
    #: never written to the add-on log in normal operation.
    debug_http: bool = False

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    #: Overridable for tests; defaults to the Supervisor proxy.
    ha_base_url: str = SUPERVISOR_API_BASE
    ha_timeout_seconds: float = 30.0

    data_dir: Path = Path("./data")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def ha_token(self) -> str:
        """The Supervisor-injected token.

        Read straight from the environment rather than stored as a field, so it
        cannot be picked up by `model_dump()` and accidentally serialised.
        """
        return os.environ.get("SUPERVISOR_TOKEN", "")

    @property
    def has_supervisor_token(self) -> bool:
        return bool(self.ha_token)

    @property
    def resolved_adapter(self) -> Literal["mock", "real"]:
        """Which adapter will actually be used."""
        if self.adapter == "auto":
            return "real" if self.has_supervisor_token else "mock"
        return self.adapter


@lru_cache
def get_settings() -> Settings:
    return Settings()
