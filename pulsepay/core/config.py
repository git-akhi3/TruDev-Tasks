from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
	model_config = SettingsConfigDict(
		env_file=".env",
		env_file_encoding="utf-8",
		case_sensitive=True,
		extra="ignore",
	)

	DATABASE_URL: str
	SECRET_KEY: str
	ENVIRONMENT: Literal["development", "staging", "production"] = "development"
	API_RATE_LIMIT_PER_MINUTE: int = Field(default=100, ge=1)
	API_BURST_LIMIT_PER_SECOND: int = Field(default=20, ge=1)
	WEBHOOK_SIGNING_SECRET: str
	MAX_PAYMENT_RETRY_ATTEMPTS: int = Field(default=3, ge=1)
	SEED_ON_STARTUP: bool = False

	DB_POOL_SIZE: int = Field(default=10, ge=1)
	DB_MAX_OVERFLOW: int = Field(default=20, ge=0)
	DB_POOL_TIMEOUT_SECONDS: int = Field(default=30, ge=1)
	DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=1)


@lru_cache(maxsize=1)
def settings() -> Settings:
	return Settings()
