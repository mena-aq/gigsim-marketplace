"""GigBid runtime configuration, independent of the simulator."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://gigbid:gigbid@localhost:5432/gigbid"
    redis_url: str = "redis://localhost:6379/0"
