from __future__ import annotations

from dataclasses import dataclass


APPLICATION_ENV_KEYS = frozenset(
    {
        "RUNTIME__APP_ENV",
        "SERVICE__NAME",
        "SERVICE__TITLE",
        "SERVICE__API_PREFIX",
        "SECURITY__SERVICE_API_KEY",
        "SECURITY__DISABLE_AUTH",
        "SECURITY__ALLOWED_ORIGINS",
        "DATABASE__URL",
        "DATABASE__SSL",
        "DATABASE__POOL_SIZE",
        "DATABASE__MAX_OVERFLOW",
        "REDIS__ENABLED",
        "REDIS__URL",
        "TASKIQ__BROKER_KIND",
        "TASKIQ__REDIS_URL",
        "TASKIQ__TASK_NAME",
        "TASKIQ__QUEUE_NAME",
        "WORKER__SERVICE_NAME",
        "WORKER__WORKER_NAME",
        "WORKER__WORKER_SESSION_ID",
        "WORKER__JOB_SERVICE_BASE_URL",
        "WORKER__JOB_SERVICE_API_KEY",
        "WORKER__JOB_SERVICE_REGISTRY_API_KEY",
        "WORKER__MANIFEST_PATH",
        "STORAGE__BACKEND",
        "STORAGE__LOCAL_PATH",
        "STORAGE__ENDPOINT",
        "STORAGE__PUBLIC_ENDPOINT",
        "STORAGE__ENDPOINT_STYLE",
        "STORAGE__SCHEME",
        "STORAGE__BUCKET",
        "STORAGE__REGION",
        "STORAGE__PROJECT_ROOT",
        "STORAGE__ACCESS_KEY_ID",
        "STORAGE__ACCESS_KEY_SECRET",
        "AUDIO_STEM__MODEL_DIR",
        "AUDIO_STEM__EXECUTION_PROVIDER",
        "AUDIO_STEM__INPUT_BUCKET",
        "AUDIO_STEM__INPUT_REGION",
        "AUDIO_STEM__MAX_INPUT_BYTES",
        "AUDIO_STEM__OUTPUT_PREFIX",
        "AUDIO_STEM__OUTPUT_BUCKET",
        "AUDIO_STEM__OUTPUT_REGION",
        "AUDIO_STEM__MAX_DURATION_SECONDS",
        "AUDIO_STEM_TRITON__URL",
        "AUDIO_STEM_TRITON__TOKEN",
        "AUDIO_STEM_TRITON__MODEL_VERSION",
        "AUDIO_STEM_TRITON__REQUEST_TIMEOUT_SECONDS",
        "HTTP_CLIENT__TIMEOUT_SECONDS",
        "OBSERVABILITY__LOG_LEVEL",
        "OBSERVABILITY__ACCESS_LOG_ENABLED",
        "OBSERVABILITY__HEALTH_ACCESS_LOG",
    }
)

LAUNCHER_ENV_KEYS = frozenset(
    {
        "API_HOST",
        "API_PORT",
        "API_HOST_PORT",
        "COMPOSE_PROJECT_NAME",
        "POSTGRES_DB",
        "POSTGRES_HOST_PORT",
        "REDIS_HOST_PORT",
    }
)

DERIVED_ENV_KEYS = frozenset({"DATABASE__SYNC_URL"})
DEPRECATED_ENV_KEYS = frozenset({"SERVICE__ENV", "SERVICE__API_KEY", "LOG_LEVEL"})


@dataclass(frozen=True)
class EnvKeyManifest:
    application_keys: frozenset[str]
    launcher_keys: frozenset[str]
    derived_keys: frozenset[str]
    deprecated_keys: frozenset[str]

    @property
    def example_keys(self) -> frozenset[str]:
        return self.application_keys | self.launcher_keys

    @property
    def forbidden_keys(self) -> frozenset[str]:
        return self.derived_keys | self.deprecated_keys


ENV_KEY_MANIFEST = EnvKeyManifest(
    application_keys=APPLICATION_ENV_KEYS,
    launcher_keys=LAUNCHER_ENV_KEYS,
    derived_keys=DERIVED_ENV_KEYS,
    deprecated_keys=DEPRECATED_ENV_KEYS,
)
