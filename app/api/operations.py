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
operation_registry.register(OperationSpec("create_item", "POST", "/v1/items", 201, frozenset({"ITEM_NAME_CONFLICT"})))
operation_registry.register(OperationSpec("get_item", "GET", "/v1/items/{item_id}", 200, frozenset({"ITEM_NOT_FOUND"})))
operation_registry.register(OperationSpec("list_items", "GET", "/v1/items", 200, frozenset({"REQUEST_INVALID"})))
operation_registry.register(
    OperationSpec(
        "update_item",
        "PATCH",
        "/v1/items/{item_id}",
        200,
        frozenset({"ITEM_NOT_FOUND", "ITEM_NAME_CONFLICT", "ITEM_VERSION_CONFLICT"}),
    )
)
operation_registry.register(
    OperationSpec(
        "delete_item",
        "DELETE",
        "/v1/items/{item_id}",
        200,
        frozenset({"ITEM_NOT_FOUND", "ITEM_VERSION_CONFLICT"}),
    )
)
operation_registry.validate()
operation_registry.freeze()
