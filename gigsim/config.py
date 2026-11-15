"""Environment-driven settings for GigSim (all variables prefixed GIGSIM_)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GIGSIM_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./gigsim.db"
    admin_token: str = "gigsim-admin-token"

    token_ml_engineer: str = "test-token-ml-engineer"
    token_fullstack_dev: str = "test-token-fullstack-dev"
    token_data_analyst: str = "test-token-data-analyst"

    rate_limit_per_minute: int = 60
    chaos_enabled: bool = True
    chaos_error_rate: float = 0.05
    chaos_seed: int | None = None

    reply_delay_min_seconds: float = 5.0
    reply_delay_max_seconds: float = 30.0

    initial_connects: int = 60
    connects_cost_low: int = 8
    connects_cost_high: int = 16
    connects_high_budget_threshold: float = 1000.0

    data_dir: str = "data/processed"

    @property
    def freelancer_tokens(self) -> dict[str, str]:
        return {
            "ml_engineer": self.token_ml_engineer,
            "fullstack_dev": self.token_fullstack_dev,
            "data_analyst": self.token_data_analyst,
        }
