"""Read-only operator projections for the native backend host.

These functions do not own jobs, workers, ingestion, or native compute.
They project canonical stores and probes for ``run_leviathan.exe``.
"""

from .read_model import (
    build_host_overview,
    build_native_operations_read_model,
    build_source_ingestion_read_model,
    redact_host_text,
)

__all__ = [
    "build_host_overview",
    "build_native_operations_read_model",
    "build_source_ingestion_read_model",
    "redact_host_text",
]
