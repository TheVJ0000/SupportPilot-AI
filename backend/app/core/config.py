from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Environment-driven application settings with safe local defaults."""

    app_env: str = "development"
    frontend_url: AnyHttpUrl = AnyHttpUrl("http://localhost:5173")
    supabase_url: AnyHttpUrl | None = None
    supabase_publishable_key: str | None = None
    supabase_secret_key: SecretStr | None = None
    embedding_provider: Literal["gemini"] = "gemini"
    gemini_api_key: SecretStr | None = None
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_dimension: Literal[768] = 768

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [str(self.frontend_url).rstrip("/")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
