from pathlib import Path

from pydantic_settings import BaseSettings

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "BankAI Platform"
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./bankai.db"
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "change-me-in-production"
    model_path: str = "/models/Phi-3-mini-4k-instruct-q4.gguf"
    care_jwt_secret: str = "dev-care-secret-change-me"
    strict_model_loading: bool = True
    allow_heuristic_fallback: bool = False

    rate_limit_per_minute: int = 1000
    api_key_header: str = "X-API-Key"
    tenant_header: str = "X-Tenant-ID"

    class Config:
        env_file = _ENV_FILE
        env_file_encoding = "utf-8"


settings = Settings()
