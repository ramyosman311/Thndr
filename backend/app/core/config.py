from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced entirely from environment variables.

    No credentials, secrets, or environment-specific URLs are hardcoded here —
    every field below is overridden by the corresponding environment variable
    (see .env.example for the authoritative list).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="THNDR Smart Portfolio", alias="APP_NAME")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    dev_mode: bool = Field(default=True, alias="DEV_MODE")

    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    backend_cors_origins: str = Field(
        default="http://localhost:3000", alias="BACKEND_CORS_ORIGINS"
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/thndr_portfolio",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/thndr_portfolio",
        alias="DATABASE_URL_SYNC",
    )

    secret_key: str = Field(default="change-me-in-production", alias="SECRET_KEY")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    telegram_enabled: bool = Field(default=False, alias="TELEGRAM_ENABLED")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Environment variables are read once per process."""
    return Settings()
