from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "postgresql+asyncpg://ilamalaev@localhost:5432/trail_social"
    JWT_SECRET_KEY: str = "change-me-to-a-secure-random-string-at-least-32-chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 10
    YANDEX_GPT_API_KEY: str = ""
    YANDEX_GPT_FOLDER_ID: str = ""
    YANDEX_GPT_MODEL: str = "qwen3-235b-a22b-fp8/latest"
    YANDEX_GEOCODER_API_KEY: str = ""


settings = Settings()
