from dataclasses import dataclass


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    method: str
    path: str
    success_status: int
    errors: frozenset[str]


class OperationRegistry:
    def __init__(self) -> None:
        self._items: dict[str, OperationSpec] = {}
        self._frozen = False

    def register(self, spec: OperationSpec) -> None:
        if self._frozen:
            raise RuntimeError("operation registry is frozen")
        if spec.operation_id in self._items:
            raise RuntimeError(f"duplicate operation id: {spec.operation_id}")
        self._items[spec.operation_id] = spec

    def all(self) -> tuple[OperationSpec, ...]:
        return tuple(self._items.values())

    def freeze(self) -> None:
        self._frozen = True

    def validate(self) -> None:
        if not self._items:
            raise RuntimeError("operation registry must not be empty")


operation_registry = OperationRegistry()
operation_registry.register(OperationSpec("health", "GET", "/health", 200, frozenset()))
operation_registry.register(OperationSpec("ready", "GET", "/ready", 200, frozenset({"DEPENDENCY_UNAVAILABLE"})))
operation_registry.validate()
operation_registry.freeze()

