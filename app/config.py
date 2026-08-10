"""
Uygulama konfigurasyonu.
Spec referansi: AcaTurkAI_Project_Spec.md - Bolum 13.1 (Backend Stack) ve
'Notlar ve Gelistirici Icin Ek Bilgiler' -> .env ornegi.

Tum degerler .env dosyasindan okunur; hicbir sir kod icine gomulmez.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "AcaTurkAI"
    ENV: str = "development"

    # Database
    DATABASE_URL: str = "postgresql://acaturkai:acaturkai@localhost:5432/acaturkai"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_ENV"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None

    # AI
    ANTHROPIC_API_KEY: str | None = None
    OPENALEX_EMAIL: str | None = None

    # Storage
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    S3_BUCKET_NAME: str = "acaturkai-uploads"
    S3_ENDPOINT_URL: str | None = None  # Cloudflare R2 kullanilirsa doldurulur

    # Payments
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None

    # Vector DB
    QDRANT_URL: str | None = None
    QDRANT_API_KEY: str | None = None

    # App
    FRONTEND_URL: str = "http://localhost:3000"

    # Uygulama limitleri (spec Bolum 16.1 - plan bazli kullanim limitleri)
    FREE_MONTHLY_LIMIT: int = 1
    STARTER_MONTHLY_LIMIT: int = 5
    FILE_RETENTION_DAYS: int = 30  # spec Bolum 18.1


@lru_cache
def get_settings() -> Settings:
    return Settings()
