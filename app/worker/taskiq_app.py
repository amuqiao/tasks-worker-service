from __future__ import annotations

from taskiq_redis import RedisStreamBroker

from app.core.config import get_settings

settings = get_settings()


def _build_broker():
    if settings.taskiq.broker_kind == "redis_stream":
        return RedisStreamBroker(settings.taskiq.redis_url, queue_name=settings.taskiq.queue_name)
    raise RuntimeError(f"unsupported TASKIQ__BROKER_KIND: {settings.taskiq.broker_kind}")


broker = _build_broker()
