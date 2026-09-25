"""Allowlisted commit handler registry — no arbitrary producer SQL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from Data.modules.db_commit.errors import UnknownOperationError
from Data.modules.db_commit.types import CommitIntent, CommitReceipt


class CommitHandler(Protocol):
    operation: str

    def validate(self, intent: CommitIntent, payload: dict[str, Any]) -> None: ...

    def apply(
        self,
        intent: CommitIntent,
        payload: dict[str, Any],
        *,
        db_path: Path,
        settings: Any,
    ) -> CommitReceipt: ...


HandlerFn = Callable[[CommitIntent, dict[str, Any], Path, Any], CommitReceipt]


@dataclass
class FunctionHandler:
    operation: str
    fn: HandlerFn
    required_payload_keys: tuple[str, ...] = ()

    def validate(self, intent: CommitIntent, payload: dict[str, Any]) -> None:
        for key in self.required_payload_keys:
            if key not in payload:
                raise ValueError(f"payload missing required key: {key}")

    def apply(
        self,
        intent: CommitIntent,
        payload: dict[str, Any],
        *,
        db_path: Path,
        settings: Any,
    ) -> CommitReceipt:
        self.validate(intent, payload)
        return self.fn(intent, payload, db_path, settings)


class CommitHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, CommitHandler] = {}

    def register(self, handler: CommitHandler) -> None:
        self._handlers[handler.operation] = handler

    def get(self, operation: str) -> CommitHandler:
        handler = self._handlers.get(operation)
        if handler is None:
            raise UnknownOperationError(operation)
        return handler

    def operations(self) -> list[str]:
        return sorted(self._handlers)

    def has(self, operation: str) -> bool:
        return operation in self._handlers


def load_payload_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    return data


def build_default_registry() -> CommitHandlerRegistry:
    from . import knowledge as knowledge_handlers
    from . import research as research_handlers
    from . import dataset as dataset_handlers
    from . import market_sim as market_sim_handlers
    from . import evaluation as evaluation_handlers
    from . import training as training_handlers
    from . import source_ingestion as source_ingestion_handlers
    from . import generic as generic_handlers

    registry = CommitHandlerRegistry()
    for module in (
        knowledge_handlers,
        research_handlers,
        dataset_handlers,
        market_sim_handlers,
        evaluation_handlers,
        training_handlers,
        source_ingestion_handlers,
        generic_handlers,
    ):
        for handler in module.handlers():
            registry.register(handler)
    return registry
