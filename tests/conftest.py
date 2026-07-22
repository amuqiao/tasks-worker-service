import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import AppSettings
from app.db.base import Base
from app.db.database import clear_session_factory, configure_session_factory, current_session_factory
from app.main import create_app
from app.models import Item  # noqa: F401


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


@pytest_asyncio.fixture
async def sqlite_session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    previous = current_session_factory()
    configure_session_factory(factory)
    try:
        yield factory
    finally:
        if previous is None:
            clear_session_factory()
        else:
            configure_session_factory(previous)
        await engine.dispose()
