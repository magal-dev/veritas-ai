"""Configuração da API. Nenhum secret de processo — só operação."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://veritas:veritas@127.0.0.1:5433/veritas_ai"
    job_ttl_seconds: int = 900
    max_upload_mb: int = 80
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    frontend_origin: str = "http://127.0.0.1:4174"


settings = Settings()
