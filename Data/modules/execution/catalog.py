from __future__ import annotations

from typing import Any

from .types import CapabilityDefinition, CapabilityProviderKind


class CapabilityCatalog:
    """Maps capability IDs to definitions (what can be done)."""

    def __init__(self) -> None:
        self._items: dict[str, CapabilityDefinition] = {}

    def register(self, definition: CapabilityDefinition) -> None:
        if definition.id in self._items:
            raise ValueError(f"Capability already registered: {definition.id}")
        self._items[definition.id] = definition

    def upsert(self, definition: CapabilityDefinition) -> CapabilityDefinition:
        """Register or replace a capability identity (MCP reconnect / schema update)."""
        self._items[definition.id] = definition
        return definition

    def set_availability(
        self,
        capability_id: str,
        *,
        available: bool,
        reason: str | None = None,
    ) -> CapabilityDefinition | None:
        item = self._items.get(capability_id)
        if item is None:
            return None
        updated = CapabilityDefinition(
            id=item.id,
            name=item.name,
            description=item.description,
            side_effects=item.side_effects,
            provider_kind=item.provider_kind,
            provider_ref=item.provider_ref,
            input_schema=item.input_schema,
            output_schema=item.output_schema,
            required_permissions=item.required_permissions,
            available=available,
            availability_reason=reason,
            enabled=item.enabled,
            schema_hash=item.schema_hash,
            metadata=dict(item.metadata),
        )
        self._items[capability_id] = updated
        return updated

    def get(self, capability_id: str) -> CapabilityDefinition | None:
        return self._items.get(capability_id)

    def require(self, capability_id: str) -> CapabilityDefinition:
        item = self.get(capability_id)
        if item is None:
            raise KeyError(f"Unknown capability: {capability_id}")
        return item

    def list(self) -> list[CapabilityDefinition]:
        return sorted(self._items.values(), key=lambda item: item.id)

    def search(self, query: str, *, limit: int = 20) -> list[CapabilityDefinition]:
        """Shortlist capabilities by id/name/description — no schema dump."""
        q = (query or "").strip().lower()
        if not q:
            return self.list()[:limit]
        scored: list[tuple[int, CapabilityDefinition]] = []
        for item in self._items.values():
            hay = f"{item.id} {item.name} {item.description}".lower()
            if q not in hay and not all(part in hay for part in q.split()):
                continue
            score = 0
            if q in item.id.lower():
                score += 40
            if q in item.name.lower():
                score += 30
            if q in item.description.lower():
                score += 10
            if item.available:
                score += 5
            scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [item for _, item in scored[:limit]]

    def list_by_provider(self, kind: CapabilityProviderKind) -> list[CapabilityDefinition]:
        return [item for item in self.list() if item.provider_kind == kind]

    def inspect(self, capability_id: str) -> dict[str, Any] | None:
        item = self.get(capability_id)
        return item.public_dict() if item else None

    def __contains__(self, capability_id: str) -> bool:
        return capability_id in self._items

    def __len__(self) -> int:
        return len(self._items)
