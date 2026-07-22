import pytest

from app.core.config import AppSettings
from app.main import create_app


@pytest.fixture
def test_settings() -> AppSettings:
    return AppSettings(
        runtime={"app_env": "local"},
        security={"service_api_key": "test-service-key", "disable_auth": False},
        storage={"backend": "disabled"},
        observability={"access_log_enabled": False},
    )


@pytest.fixture
def app(test_settings):
    return create_app(test_settings)

