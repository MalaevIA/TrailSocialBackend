from typing import List, Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://ilamalaev@localhost:5432/trail_social"

    # Auth
    JWT_SECRET_KEY: str = "change-me-to-a-secure-random-string-at-least-32-chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    BCRYPT_ROUNDS: int = 12
    TOKEN_CLEANUP_INTERVAL_SECONDS: int = 3600

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]

    # Uploads
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # Redis (оставить пустым чтобы отключить кэш)
    REDIS_URL: str = ""
    CACHE_TTL_SECONDS: int = 300  # 5 минут

    # WebSocket
    WS_AUTH_TIMEOUT_SECONDS: int = 10

    # Yandex / AI
    YANDEX_GPT_API_KEY: str = ""
    YANDEX_GPT_FOLDER_ID: str = ""
    YANDEX_GPT_MODEL: str = "qwen3-235b-a22b-fp8/latest"
    YANDEX_GEOCODER_API_KEY: str = ""

    # ЮКасса (оставить пустым чтобы отключить оплату)
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    # Процент платформы от каждой подписки (остаток уходит автору)
    PLATFORM_FEE_PERCENT: int = 10


settings = Settings()
