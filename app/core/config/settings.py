from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.sections import (
    DatabaseSettings,
    HttpClientSettings,
    ObservabilitySettings,
    RedisSettings,
    RuntimeSettings,
    SecuritySettings,
    ServiceSettings,
    StorageSettings,
)
from app.core.config.validation import validate_release_invariants

ROOT_DIR = Path(__file__).resolve().parents[3]


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    service: ServiceSettings = Field(default_factory=ServiceSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    http_client: HttpClientSettings = Field(default_factory=HttpClientSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    @model_validator(mode="after")
    def validate_invariants(self) -> "AppSettings":
        self.security.allowed_origin_list
        validate_release_invariants(
            runtime=self.runtime,
            security=self.security,
            storage=self.storage,
            database_url=self.database.url,
            redis_url=self.redis.url,
        )
        return self


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
