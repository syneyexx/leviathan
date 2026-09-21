from __future__ import annotations

from .types import FunctionDefinition


class FunctionRegistry:
    """Canonical registry of on-demand / cold-path functions."""

    def __init__(self) -> None:
        self._defs: dict[str, FunctionDefinition] = {}

    def register(self, definition: FunctionDefinition) -> None:
        if definition.id in self._defs:
            raise ValueError(f"Function already registered: {definition.id}")
        self._defs[definition.id] = definition

    def get(self, function_id: str) -> FunctionDefinition | None:
        return self._defs.get(function_id)

    def require(self, function_id: str) -> FunctionDefinition:
        definition = self.get(function_id)
        if definition is None:
            raise KeyError(f"Unknown function: {function_id}")
        return definition

    def list(self) -> list[FunctionDefinition]:
        return sorted(self._defs.values(), key=lambda item: item.id)

    def __contains__(self, function_id: str) -> bool:
        return function_id in self._defs

    def __len__(self) -> int:
        return len(self._defs)
