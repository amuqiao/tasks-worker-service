from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

HealthStatus = Literal["ok", "failed", "degraded"]
HealthCheckFunc = Callable[[], Awaitable["HealthCheckResult"]]


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    status: HealthStatus
    details: dict[str, object]


@dataclass(frozen=True)
class HealthCheck:
    name: str
    check: HealthCheckFunc
    timeout_seconds: float = 1
    required: bool = True


class HealthCheckRegistry:
    def __init__(self) -> None:
        self._items: dict[str, HealthCheck] = {}
        self._frozen = False

    def register(self, item: HealthCheck) -> None:
        if self._frozen:
            raise RuntimeError("health check registry is frozen")
        if item.name in self._items:
            raise RuntimeError(f"duplicate health check: {item.name}")
        self._items[item.name] = item

    def all(self) -> tuple[HealthCheck, ...]:
        return tuple(self._items.values())

    def freeze(self) -> None:
        self._frozen = True

    def validate(self) -> None:
        for item in self._items.values():
            if item.timeout_seconds <= 0:
                raise RuntimeError(f"health check timeout must be positive: {item.name}")


async def run_health_checks(registry: HealthCheckRegistry) -> dict[str, object]:
    checks = []
    for item in registry.all():
        try:
            result = await asyncio.wait_for(item.check(), timeout=item.timeout_seconds)
        except TimeoutError:
            result = HealthCheckResult(item.name, "failed", {"reason": "timeout"})
        except Exception as exc:
            result = HealthCheckResult(item.name, "failed", {"reason": type(exc).__name__})
        checks.append((item, result))

    required_failed = any(item.required and result.status == "failed" for item, result in checks)
    degraded = any((not item.required and result.status == "failed") or result.status == "degraded" for item, result in checks)
    status = "failed" if required_failed else "degraded" if degraded else "ok"
    return {
        "status": status,
        "checks": [
            {
                "name": result.name,
                "status": result.status,
                "required": item.required,
                "details": result.details,
            }
            for item, result in checks
        ],
    }


async def process_health_check() -> HealthCheckResult:
    return HealthCheckResult(name="process", status="ok", details={})


def build_health_registry() -> HealthCheckRegistry:
    registry = HealthCheckRegistry()
    registry.register(HealthCheck(name="process", check=process_health_check, required=True))
    registry.validate()
    registry.freeze()
    return registry

