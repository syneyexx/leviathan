"""Source handler protocol and registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..settings import SourceIngestionSettings
from ..types import DetectionResult, NormalizedArtifact, SourceKind


@dataclass(frozen=True)
class HandlerCapabilities:
    handler_id: str
    kinds: frozenset[SourceKind]
    extensions: frozenset[str] = field(default_factory=frozenset)
    mime_types: frozenset[str] = field(default_factory=frozenset)
    max_bytes: int | None = None
    supports_stream: bool = False
    requires_path: bool = False


@runtime_checkable
class SourceHandler(Protocol):
    capabilities: HandlerCapabilities

    def can_handle(self, detection: DetectionResult, *, filename: str) -> bool: ...

    def inspect(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        settings: SourceIngestionSettings,
    ) -> dict[str, Any]: ...

    def ingest(
        self,
        path: Path,
        *,
        detection: DetectionResult,
        relative_path: str,
        settings: SourceIngestionSettings,
        staging_root: Path | None = None,
    ) -> NormalizedArtifact: ...


class HandlerRegistry:
    """Authoritative registry for source format handlers."""

    def __init__(self) -> None:
        self._handlers: list[SourceHandler] = []
        self._by_id: dict[str, SourceHandler] = {}

    def register(self, handler: SourceHandler) -> None:
        hid = handler.capabilities.handler_id
        if hid in self._by_id:
            raise ValueError(f"Handler already registered: {hid}")
        self._by_id[hid] = handler
        self._handlers.append(handler)

    def get(self, handler_id: str) -> SourceHandler | None:
        return self._by_id.get(handler_id)

    def list_handlers(self) -> list[SourceHandler]:
        return list(self._handlers)

    def resolve(
        self,
        detection: DetectionResult,
        *,
        filename: str,
    ) -> SourceHandler | None:
        # Prefer handler_hint exact match
        if detection.handler_hint:
            hinted = self._by_id.get(detection.handler_hint)
            if hinted is not None and hinted.can_handle(detection, filename=filename):
                return hinted
            # also try common aliases
            for handler in self._handlers:
                if handler.capabilities.handler_id == detection.handler_hint:
                    if handler.can_handle(detection, filename=filename):
                        return handler
        for handler in self._handlers:
            if handler.can_handle(detection, filename=filename):
                return handler
        return None

    def supported_extensions(self) -> list[str]:
        exts: set[str] = set()
        for handler in self._handlers:
            exts.update(handler.capabilities.extensions)
        return sorted(exts)


_DEFAULT_REGISTRY: HandlerRegistry | None = None


def get_default_registry() -> HandlerRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY


def build_default_registry() -> HandlerRegistry:
    from .code import SourceCodeHandler
    from .dataset_route import DatasetRouteHandler
    from .documents import DocumentHandler
    from .image import ImageHandler
    from .office import OfficeHandler
    from .plain_text import PlainTextHandler
    from .structured import StructuredDataHandler
    from .unsupported import UnsupportedBinaryHandler

    registry = HandlerRegistry()
    for handler in (
        DocumentHandler(),
        StructuredDataHandler(),
        SourceCodeHandler(),
        OfficeHandler(),
        DatasetRouteHandler(),
        ImageHandler(),
        PlainTextHandler(),
        UnsupportedBinaryHandler(),
    ):
        registry.register(handler)
    return registry
