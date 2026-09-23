"""Isolation posture — intended vs OS-enforced, plus measured sandbox probes."""

from .guard import IsolationGuard
from .sandbox import (
    BoundaryProbeResult,
    ProbeOutcome,
    SandboxProbeReport,
    UntrustedExecutionProber,
    run_workspace_sandbox_probes,
)
from .types import IsolationEffective, IsolationMode, IsolationReport, IsolationRequest

__all__ = [
    "BoundaryProbeResult",
    "IsolationEffective",
    "IsolationGuard",
    "IsolationMode",
    "IsolationReport",
    "IsolationRequest",
    "ProbeOutcome",
    "SandboxProbeReport",
    "UntrustedExecutionProber",
    "run_workspace_sandbox_probes",
]
