from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FlowGuard Control Plane"
    database_url: str = "sqlite:///./flowguard.db"
    redis_url: str = "redis://localhost:6379/0"
    n8n_shared_secret: str = "change-me-in-production"
    max_auto_cost_usd: float = 0.50
    cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
