from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RACS_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "demo"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


class DeepSeekSettings(BaseSettings):
    """Configuration for the optional, single-provider T-204 model adapter."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deepseek_api_key: SecretStr | None = None
    deepseek_model: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = 20.0
    deepseek_config_version: str = "1"

    @property
    def is_configured(self) -> bool:
        return bool(
            self.deepseek_api_key
            and self.deepseek_api_key.get_secret_value().strip()
            and self.deepseek_model
            and self.deepseek_model.strip()
        )
