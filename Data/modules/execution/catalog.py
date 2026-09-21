from __future__ import annotations

from .types import CapabilityDefinition


class CapabilityCatalog:
    """Maps capability IDs to definitions (what can be done)."""

    def __init__(self) -> None:
        self._items: dict[str, CapabilityDefinition] = {}

    def register(self, definition: CapabilityDefinition) -> None:
        if definition.id in self._items:
            raise ValueError(f"Capability already registered: {definition.id}")
        self._items[definition.id] = definition

    def get(self, capability_id: str) -> CapabilityDefinition | None:
        return self._items.get(capability_id)

    def require(self, capability_id: str) -> CapabilityDefinition:
        item = self.get(capability_id)
        if item is None:
            raise KeyError(f"Unknown capability: {capability_id}")
        return item

    def list(self) -> list[CapabilityDefinition]:
        return sorted(self._items.values(), key=lambda item: item.id)

    def __contains__(self, capability_id: str) -> bool:
        return capability_id in self._items

    def __len__(self) -> int:
        return len(self._items)
