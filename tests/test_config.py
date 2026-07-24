from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppSettings
from app.core.config.settings import validate_app_env_key_drift
from scripts.verify.env_config_check import check_env_file, check_example_alignment


def test_settings_are_sectioned_and_load_defaults():
    settings = AppSettings(_env_file=None)

    assert settings.runtime.app_env == "local"
    assert settings.service.name == "tasks-worker-service"
    assert settings.service.title == "Tasks Worker Service"
    assert settings.service.api_prefix == "/v1"
    assert settings.database.url == "postgresql+asyncpg://postgres:postgres@127.0.0.1:25435/tasks_worker_service"
    assert settings.redis.url == "redis://127.0.0.1:26382/0"
    assert settings.taskiq.broker_kind == "redis_stream"
    assert settings.taskiq.redis_url == "redis://127.0.0.1:26380/0"
    assert settings.worker.service_name == "worker-x"
    assert settings.worker.job_service_base_url == "http://127.0.0.1:8110/internal/v1"
    assert settings.storage.backend == "disabled"


def test_release_rejects_placeholder_secret():
    with pytest.raises(ValidationError, match="SECURITY__SERVICE_API_KEY"):
        AppSettings(runtime={"app_env": "prd"}, storage={"backend": "disabled"})


def test_release_rejects_local_storage():
    with pytest.raises(ValidationError, match="STORAGE__BACKEND=local"):
        AppSettings(
            runtime={"app_env": "prd"},
            security={"service_api_key": "prd-secret-token-123456"},
            storage={"backend": "local"},
        )


def test_aliyun_oss_requires_credentials():
    with pytest.raises(ValidationError, match="STORAGE__BACKEND=aliyun_oss"):
        AppSettings(_env_file=None, storage={"backend": "aliyun_oss"})


def test_aliyun_oss_rejects_insecure_or_untrusted_endpoint():
    base = {
        "backend": "aliyun_oss",
        "bucket": "storage-bucket",
        "region": "cn-test",
        "access_key_id": "ak",
        "access_key_secret": "sk",
    }
    with pytest.raises(ValidationError, match="STORAGE__SCHEME=https"):
        AppSettings(_env_file=None, storage=base | {"scheme": "http"})
    with pytest.raises(ValidationError, match="aliyuncs.com"):
        AppSettings(_env_file=None, storage=base | {"endpoint": "example.test"})


def test_aliyun_oss_requires_audio_stem_bucket_alignment():
    with pytest.raises(ValidationError, match="AUDIO_STEM__INPUT_BUCKET"):
        AppSettings(
            _env_file=None,
            storage={
                "backend": "aliyun_oss",
                "bucket": "storage-bucket",
                "region": "cn-test",
                "access_key_id": "ak",
                "access_key_secret": "sk",
            },
        )


def test_aliyun_oss_requires_audio_stem_region_alignment():
    with pytest.raises(ValidationError, match="AUDIO_STEM__INPUT_REGION"):
        AppSettings(
            _env_file=None,
            storage={
                "backend": "aliyun_oss",
                "bucket": "storage-bucket",
                "region": "cn-test",
                "access_key_id": "ak",
                "access_key_secret": "sk",
            },
            audio_stem={
                "input_bucket": "storage-bucket",
                "output_bucket": "storage-bucket",
            },
        )


def test_taskiq_rejects_redis_list_broker():
    with pytest.raises(ValidationError, match="TASKIQ__BROKER_KIND"):
        AppSettings(taskiq={"broker_kind": "redis_list"})


def test_env_example_matches_manifest():
    issues = check_example_alignment(Path(".env.example"))

    assert issues == []


def test_env_file_rejects_deprecated_and_derived_keys(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SERVICE__ENV=local\nDATABASE__SYNC_URL=postgresql://x\n", encoding="utf-8")

    issues = check_env_file(env_file)

    assert any("deprecated config key: SERVICE__ENV" in issue for issue in issues)
    assert any("derived config key must not be set: DATABASE__SYNC_URL" in issue for issue in issues)


def test_runtime_env_rejects_unknown_application_key(monkeypatch):
    monkeypatch.setenv("DATABASE__URLL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:25435/app")

    with pytest.raises(ValueError, match="unknown application config key: DATABASE__URLL"):
        validate_app_env_key_drift()


def test_runtime_env_allows_launcher_keys(monkeypatch):
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "tasks-worker-service-test")

    validate_app_env_key_drift()
