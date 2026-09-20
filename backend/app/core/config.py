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
    app_name: str = Field(default="MIZAN Smart Portfolio Manager", alias="APP_NAME")
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

    api_auth_token: str = Field(default="", alias="API_AUTH_TOKEN")

    # --- Supabase Auth (P0-3B) ---
    # supabase_url was already reserved (see .env.example) but unread by any
    # code before this phase. It is the same project as DATABASE_URL points
    # at, so no new secret is introduced: issuer/JWKS URL below are derived
    # from it using Supabase's own documented URL layout, never guessed or
    # hardcoded to one project. supabase_jwt_audience defaults to "authenticated",
    # which is Supabase's own documented standard audience claim value for
    # every Supabase Auth-issued access token (not a project-specific secret).
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_jwt_audience: str = Field(default="authenticated", alias="SUPABASE_JWT_AUDIENCE")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def supabase_jwt_issuer(self) -> str:
        """Supabase Auth's documented issuer for every access token it
        signs: `{project URL}/auth/v1`. Empty when supabase_url is unset
        (require_supabase_user's caller must treat that as "not configured",
        never as a wildcard issuer)."""
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else ""

    @property
    def supabase_jwks_url(self) -> str:
        """Supabase Auth's documented JWKS endpoint, used to fetch the
        public key(s) that verify its JWT signatures (asymmetric
        RS256/ES256 -- never a shared secret)."""
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json" if self.supabase_url else ""


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Environment variables are read once per process."""
    return Settings()
