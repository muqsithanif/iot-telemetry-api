"""Application settings, read from environment with sane local defaults."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite by default so the project runs with no external service.
    # Point this at MySQL to exercise the same code against a real server:
    #   mysql+pymysql://telemetry:telemetry@localhost:3306/telemetry
    database_url: str = "sqlite:///./telemetry.db"

    # Override in .env for anything that is not a throwaway local run.
    jwt_secret: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60

    # Readings older than this are rejected as clock-skew or replayed data.
    max_reading_age_hours: int = 48


@lru_cache
def get_settings() -> Settings:
    return Settings()
