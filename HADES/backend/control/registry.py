"""Setting definition registry — single catalogue of HADES-controlled knobs."""

from __future__ import annotations

from typing import Any, Iterable

from .types import SettingDefinition


class SettingRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, SettingDefinition] = {}
        self._by_storage: dict[str, SettingDefinition] = {}

    def register(self, definition: SettingDefinition) -> SettingDefinition:
        if definition.id in self._by_id:
            raise ValueError(f"duplicate setting id: {definition.id}")
        if definition.storage_key in self._by_storage:
            raise ValueError(f"duplicate storage key: {definition.storage_key}")
        self._by_id[definition.id] = definition
        self._by_storage[definition.storage_key] = definition
        return definition

    def register_many(self, definitions: Iterable[SettingDefinition]) -> None:
        for item in definitions:
            self.register(item)

    def get(self, setting_id: str) -> SettingDefinition | None:
        return self._by_id.get(setting_id) or self._by_storage.get(setting_id)

    def require(self, setting_id: str) -> SettingDefinition:
        found = self.get(setting_id)
        if not found:
            raise KeyError(f"unknown setting: {setting_id}")
        return found

    def all(self) -> list[SettingDefinition]:
        return list(self._by_id.values())

    def by_category(self, category: str) -> list[SettingDefinition]:
        return [d for d in self._by_id.values() if d.category == category]

    def categories(self) -> list[str]:
        return sorted({d.category for d in self._by_id.values()})

    def defaults_map(self) -> dict[str, Any]:
        """Flat storage_key → default_value map for SQLite / DEFAULT_SETTINGS merge."""
        return {d.storage_key: d.default_value for d in self._by_id.values()}

    def storage_keys(self) -> set[str]:
        return set(self._by_storage.keys())

    def public_definitions(self) -> list[dict[str, Any]]:
        return [d.to_public() for d in self._by_id.values()]
