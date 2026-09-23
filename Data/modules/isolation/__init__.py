"""Isolation — requested vs effective isolation honesty + fixture sandbox."""

from .guard import IsolationGuard
from .sandbox_fixture import FixtureSandboxBackend, SandboxLimits, SandboxSession
from .types import IsolationEffective, IsolationMode, IsolationReport, IsolationRequest

__all__ = [
    "FixtureSandboxBackend",
    "IsolationEffective",
    "IsolationGuard",
    "IsolationMode",
    "IsolationReport",
    "IsolationRequest",
    "SandboxLimits",
    "SandboxSession",
]
