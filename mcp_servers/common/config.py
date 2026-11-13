"""Configuration for owned MCP servers; no live marketplace integration."""

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://gigbid:gigbid@localhost:5432/gigbid"
    redis_url: str = "redis://localhost:6379/0"
    marketplace_mode: str = "gigsim"
    gigsim_base_url: str = "http://localhost:8081"
    gigsim_token_ml_engineer: str = "test-token-ml-engineer"
    gigsim_token_fullstack_dev: str = "test-token-fullstack-dev"
    gigsim_token_data_analyst: str = "test-token-data-analyst"
    mcp_persona_dir: Path = Path("data/personas")
    mcp_requests_per_minute: int = Field(default=20, ge=1, le=50)
    mcp_timeout_seconds: float = Field(default=10, gt=0, le=60)
    mcp_base_url: str = "http://localhost:8101"

    @model_validator(mode="after")
    def gigsim_only(self):
        if self.marketplace_mode != "gigsim":
            raise ValueError("Only MARKETPLACE_MODE=gigsim is supported")
        return self

    def simulator_token(self, persona: str) -> str:
        return getattr(self, f"gigsim_token_{persona}")
