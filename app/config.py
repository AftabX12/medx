from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    app_debug: bool = True

    database_url: str = "sqlite+aiosqlite:///./medx.db"

    jwt_secret: str = Field(default="dev-secret-change-me")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    document_store: str = "local"
    local_store_path: str = "./uploads"

    anthropic_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
