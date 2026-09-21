from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the local HADES bridge."""

    app_name: str = "HADES Local Bridge"
    app_version: str = "0.4.1"
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    lm_studio_api_key: str = "lm-studio"
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    database_path: str = str(Path(__file__).resolve().parent / "data" / "hades.db")
    max_concurrent_tasks: int = Field(default=2, ge=1)
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:4173,http://localhost:4173"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="HADES_", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
