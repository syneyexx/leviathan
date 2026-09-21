"""Resolve PEP 563 annotations on nested FastAPI handlers.

`from __future__ import annotations` stores types as strings. FastAPI/Pydantic
look those names up on the *module* globals of the endpoint. Nested mount/
register functions bind models in *locals*, so OpenAPI generation wraps an
unresolved ForwardRef in Query and raises:

    TypeAdapter[Annotated[ForwardRef('BuildPlanInput'), Query(...)]]
    is not fully defined

This module patches `APIRouter.add_api_route` so annotations are evaluated
with enclosing mount/register locals before FastAPI builds the dependant.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from typing import Any, get_type_hints

from fastapi.routing import APIRouter

_PATCHED = False
_MOUNT_PREFIXES = ("mount_", "register_")


def enclosing_locals(start_frame_depth: int = 1) -> dict[str, Any]:
    """Merge locals from caller frames, stopping at a mount/register function."""
    merged: dict[str, Any] = {}
    frame = sys._getframe(start_frame_depth)
    while frame is not None:
        merged.update(frame.f_locals)
        name = frame.f_code.co_name
        if name.startswith(_MOUNT_PREFIXES):
            break
        frame = frame.f_back
    return merged


def materialize_endpoint_annotations(
    endpoint: Callable[..., Any],
    localns: Mapping[str, Any] | None = None,
) -> Callable[..., Any]:
    annotations = getattr(endpoint, "__annotations__", None)
    if not annotations or not callable(endpoint):
        return endpoint
    ns = dict(localns or {})
    try:
        endpoint.__annotations__ = get_type_hints(
            endpoint,
            globalns=dict(getattr(endpoint, "__globals__", {}) or {}),
            localns=ns,
        )
    except Exception:
        return endpoint
    return endpoint


def _patched_add_api_route(self: APIRouter, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
    if callable(endpoint):
        materialize_endpoint_annotations(endpoint, enclosing_locals(2))
    return _ORIGINAL_ADD_API_ROUTE(self, path, endpoint, **kwargs)


_ORIGINAL_ADD_API_ROUTE = APIRouter.add_api_route


def install_nested_annotation_patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    APIRouter.add_api_route = _patched_add_api_route  # type: ignore[method-assign]
    _PATCHED = True


install_nested_annotation_patch()
