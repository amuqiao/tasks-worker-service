from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeSettings(ConfigSection):
    app_env: Literal["local", "dev", "test", "prd"] = "local"

    @property
    def is_release_env(self) -> bool:
        return self.app_env in {"test", "prd"}


class ServiceSettings(ConfigSection):
    name: str = "tasks-worker-service"
    title: str = "Tasks Worker Service"
    api_prefix: str = "/v1"

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("SERVICE__API_PREFIX must start with /")
        if len(value) > 1 and value.endswith("/"):
            raise ValueError("SERVICE__API_PREFIX must not end with /")
        return value


class SecuritySettings(ConfigSection):
    service_api_key: SecretStr = Field(default=SecretStr("dev-service-key"), repr=False)
    disable_auth: bool = False
    allowed_origins: str = "http://localhost:3000"

    @property
    def service_api_key_value(self) -> str:
        return self.service_api_key.get_secret_value()

    @property
    def allowed_origin_list(self) -> tuple[str, ...]:
        values = tuple(item.strip() for item in self.allowed_origins.split(",") if item.strip())
        if not values:
            raise ValueError("SECURITY__ALLOWED_ORIGINS must contain at least one origin")
        return values


class DatabaseSettings(ConfigSection):
    url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:25435/tasks_worker_service"
    ssl: bool = False
    pool_size: int = 5
    max_overflow: int = 10

    @model_validator(mode="after")
    def validate_database(self) -> "DatabaseSettings":
        if self.pool_size <= 0:
            raise ValueError("DATABASE__POOL_SIZE must be greater than 0")
        if self.max_overflow < 0:
            raise ValueError("DATABASE__MAX_OVERFLOW must be greater than or equal to 0")
        return self

    @property
    def sync_url(self) -> str:
        if self.url.startswith("postgresql+asyncpg://"):
            return self.url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        return self.url


class RedisSettings(ConfigSection):
    enabled: bool = False
    url: str = "redis://127.0.0.1:26382/0"


class TaskiqSettings(ConfigSection):
    broker_kind: str = "redis_stream"
    redis_url: str = "redis://127.0.0.1:26380/0"
    task_name: str = "job-platform.consume_queue_envelope"
    queue_name: str = "job.example-task.v1"

    @field_validator("broker_kind")
    @classmethod
    def validate_broker_kind(cls, value: str) -> str:
        if value != "redis_stream":
            raise ValueError("TASKIQ__BROKER_KIND must be redis_stream")
        return value


class WorkerSettings(ConfigSection):
    service_name: str = "worker-x"
    worker_name: str = "worker-x-taskiq"
    worker_session_id: str = "worker-x-local"
    job_service_base_url: str = "http://127.0.0.1:8110/internal/v1"
    job_service_api_key: SecretStr = Field(default=SecretStr("dev-worker-key"), repr=False)
    job_service_registry_api_key: SecretStr = Field(default=SecretStr("dev-registry-key"), repr=False)
    manifest_path: str = "app/worker/manifest.json"

    @field_validator("job_service_base_url")
    @classmethod
    def validate_job_service_base_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("WORKER__JOB_SERVICE_BASE_URL must start with http:// or https://")
        return value.rstrip("/")

    @property
    def job_service_api_key_value(self) -> str:
        return self.job_service_api_key.get_secret_value()

    @property
    def job_service_registry_api_key_value(self) -> str:
        return self.job_service_registry_api_key.get_secret_value()


class StorageSettings(ConfigSection):
    backend: Literal["disabled", "local", "s3_compatible"] = "disabled"
    local_path: str = "storage/objects"
    endpoint: str = ""
    bucket: str = ""
    region: str = ""
    access_key_id: str = ""
    access_key_secret: SecretStr = Field(default=SecretStr(""), repr=False)

    @model_validator(mode="after")
    def validate_storage(self) -> "StorageSettings":
        if self.backend == "local" and not self.local_path.strip():
            raise ValueError("STORAGE__LOCAL_PATH is required when STORAGE__BACKEND=local")
        if self.backend == "s3_compatible":
            required = {
                "STORAGE__ENDPOINT": self.endpoint,
                "STORAGE__BUCKET": self.bucket,
                "STORAGE__REGION": self.region,
                "STORAGE__ACCESS_KEY_ID": self.access_key_id,
                "STORAGE__ACCESS_KEY_SECRET": self.access_key_secret.get_secret_value(),
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"STORAGE__BACKEND=s3_compatible requires: {', '.join(missing)}")
        return self


class AudioStemSettings(ConfigSection):
    model_dir: str = ".data/models/htdemucs-ft"
    execution_provider: str = "CPUExecutionProvider"
    input_bucket: str = "audio-inputs"
    input_region: str = "local"
    max_input_bytes: int = 200 * 1024 * 1024
    output_prefix: str = "audio-stem-separation"
    output_bucket: str = "audio-outputs"
    output_region: str = "local"
    max_duration_seconds: float = 3600

    @field_validator("max_input_bytes")
    @classmethod
    def validate_max_input_bytes(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("AUDIO_STEM__MAX_INPUT_BYTES must be greater than 0")
        return value

    @field_validator("max_duration_seconds")
    @classmethod
    def validate_max_duration_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("AUDIO_STEM__MAX_DURATION_SECONDS must be greater than 0")
        return value


class AudioStemTritonSettings(ConfigSection):
    url: str = "http://127.0.0.1:8000"
    token: SecretStr = Field(default=SecretStr(""), repr=False)
    model_version: str = "1"
    request_timeout_seconds: float = 30

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("AUDIO_STEM_TRITON__URL must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("request_timeout_seconds")
    @classmethod
    def validate_request_timeout_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("AUDIO_STEM_TRITON__REQUEST_TIMEOUT_SECONDS must be greater than 0")
        return value

    @property
    def token_value(self) -> str:
        return self.token.get_secret_value()


class HttpClientSettings(ConfigSection):
    timeout_seconds: float = 5

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("HTTP_CLIENT__TIMEOUT_SECONDS must be greater than 0")
        return value


class ObservabilitySettings(ConfigSection):
    log_level: str = "INFO"
    access_log_enabled: bool = True
    health_access_log: bool = False

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("OBSERVABILITY__LOG_LEVEL must be a valid Python logging level")
        return normalized
