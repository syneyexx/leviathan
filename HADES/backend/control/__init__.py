"""HADES Control Plane — policy-driven configuration architecture.

Public entry points:
  - init_control_service / get_control_service
  - resolve_setting
  - router (FastAPI)
"""

from .definitions import create_default_registry
from .routes import router as control_router
from .service import get_control_service, init_control_service, resolve_setting
from .types import CONFIG_SCHEMA_VERSION, LimitEvent, ResolveContext

__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "LimitEvent",
    "ResolveContext",
    "control_router",
    "create_default_registry",
    "get_control_service",
    "init_control_service",
    "resolve_setting",
]
