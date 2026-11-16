"""Env-driven configuration — the only place the environment is read."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://localhost/stanzabonanza"
    # Comma-separated origins allowed for cross-origin browser calls.
    # Empty in production: the SPA is same-origin (docs/DESIGN.md §5.7).
    allowed_origins: str = ""
    rate_limit_per_minute: int = 30
    rate_limit_burst: int = 10

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
