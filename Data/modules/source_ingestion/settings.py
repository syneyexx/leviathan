"""Centralized source-ingestion settings (operator-configurable, safe defaults)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass
class SourceIngestionSettings:
    """Limits and policies for source ingestion.

    Defaults are safe for a local workstation; raise via env / settings plane.
    """

    enabled: bool = True
    # 8 GiB default ceiling — not an architectural hard limit at 100 MiB.
    max_upload_bytes: int = 8 * 1024 * 1024 * 1024
    max_member_count: int = 50_000
    max_member_bytes: int = 512 * 1024 * 1024
    max_total_uncompressed_bytes: int = 8 * 1024 * 1024 * 1024
    max_compression_ratio: float = 200.0
    max_nested_archive_depth: int = 2
    max_path_depth: int = 64
    max_filename_length: int = 255
    allow_7z: bool = False
    allow_rar: bool = False
    allow_unknown_text: bool = True
    secret_policy: str = "quarantine"  # quarantine | skip | redact
    worker_poll_interval: float = 0.5
    worker_concurrency: int = 1
    lease_ttl_seconds: float = 60.0
    # inprocess | external | none  (mirrors dataset_jobs_runner)
    runner: str = "inprocess"
    dataset_route_min_bytes: int = 32 * 1024 * 1024
    dataset_route_formats: tuple[str, ...] = (
        ".parquet",
        ".jsonl",
        ".ndjson",
    )
    code_repo_ignore_defaults: bool = True
    sync_small_files_inline: bool = False  # always prefer job path; keep False

    def validate(self) -> None:
        if self.max_upload_bytes < 1024:
            raise ValueError("source_ingestion.max_upload_bytes must be >= 1024")
        if self.max_member_count < 1:
            raise ValueError("source_ingestion.max_member_count must be >= 1")
        if self.max_member_bytes < 1:
            raise ValueError("source_ingestion.max_member_bytes must be >= 1")
        if self.max_total_uncompressed_bytes < 1:
            raise ValueError("source_ingestion.max_total_uncompressed_bytes must be >= 1")
        if self.max_compression_ratio < 1.0:
            raise ValueError("source_ingestion.max_compression_ratio must be >= 1")
        if self.max_nested_archive_depth < 0:
            raise ValueError("source_ingestion.max_nested_archive_depth must be >= 0")
        if self.worker_concurrency < 1:
            raise ValueError("source_ingestion.worker_concurrency must be >= 1")
        if self.secret_policy not in {"quarantine", "skip", "redact"}:
            raise ValueError("source_ingestion.secret_policy must be quarantine|skip|redact")
        if self.runner not in {"inprocess", "external", "none"}:
            raise ValueError("source_ingestion.runner must be inprocess|external|none")

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_upload_bytes": self.max_upload_bytes,
            "max_member_count": self.max_member_count,
            "max_member_bytes": self.max_member_bytes,
            "max_total_uncompressed_bytes": self.max_total_uncompressed_bytes,
            "max_compression_ratio": self.max_compression_ratio,
            "max_nested_archive_depth": self.max_nested_archive_depth,
            "max_path_depth": self.max_path_depth,
            "max_filename_length": self.max_filename_length,
            "allow_7z": self.allow_7z,
            "allow_rar": self.allow_rar,
            "allow_unknown_text": self.allow_unknown_text,
            "secret_policy": self.secret_policy,
            "worker_poll_interval": self.worker_poll_interval,
            "worker_concurrency": self.worker_concurrency,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "runner": self.runner,
            "dataset_route_min_bytes": self.dataset_route_min_bytes,
            "dataset_route_formats": list(self.dataset_route_formats),
            "code_repo_ignore_defaults": self.code_repo_ignore_defaults,
        }


def load_source_ingestion_settings(
    *,
    research_integration: Any | None = None,
) -> SourceIngestionSettings:
    """Load settings from env with optional ResearchIntegrationSettings overlay."""
    ri = research_integration
    runner = (os.environ.get("LEVIATHAN_SOURCE_INGESTION_RUNNER") or "").strip().lower()
    if not runner and ri is not None:
        runner = str(getattr(ri, "source_ingestion_runner", "") or "").strip().lower()
    if runner not in {"inprocess", "external", "none"}:
        runner = "inprocess"

    settings = SourceIngestionSettings(
        enabled=_env_bool("LEVIATHAN_SOURCE_INGESTION_ENABLED", True),
        max_upload_bytes=_env_int(
            "LEVIATHAN_SOURCE_INGESTION_MAX_UPLOAD_BYTES",
            8 * 1024 * 1024 * 1024,
        ),
        max_member_count=_env_int("LEVIATHAN_SOURCE_INGESTION_MAX_MEMBER_COUNT", 50_000),
        max_member_bytes=_env_int(
            "LEVIATHAN_SOURCE_INGESTION_MAX_MEMBER_BYTES",
            512 * 1024 * 1024,
        ),
        max_total_uncompressed_bytes=_env_int(
            "LEVIATHAN_SOURCE_INGESTION_MAX_TOTAL_UNCOMPRESSED_BYTES",
            8 * 1024 * 1024 * 1024,
        ),
        max_compression_ratio=_env_float(
            "LEVIATHAN_SOURCE_INGESTION_MAX_COMPRESSION_RATIO",
            200.0,
        ),
        max_nested_archive_depth=_env_int(
            "LEVIATHAN_SOURCE_INGESTION_MAX_NESTED_DEPTH",
            2,
        ),
        max_path_depth=_env_int("LEVIATHAN_SOURCE_INGESTION_MAX_PATH_DEPTH", 64),
        max_filename_length=_env_int("LEVIATHAN_SOURCE_INGESTION_MAX_FILENAME_LENGTH", 255),
        allow_7z=_env_bool("LEVIATHAN_SOURCE_INGESTION_ALLOW_7Z", False),
        allow_unknown_text=_env_bool("LEVIATHAN_SOURCE_INGESTION_ALLOW_UNKNOWN_TEXT", True),
        secret_policy=(
            os.environ.get("LEVIATHAN_SOURCE_INGESTION_SECRET_POLICY") or "quarantine"
        ).strip().lower()
        or "quarantine",
        worker_poll_interval=_env_float("LEVIATHAN_SOURCE_INGESTION_WORKER_POLL", 0.5),
        worker_concurrency=_env_int("LEVIATHAN_SOURCE_INGESTION_WORKER_CONCURRENCY", 1),
        lease_ttl_seconds=_env_float("LEVIATHAN_SOURCE_INGESTION_LEASE_TTL", 60.0),
        runner=runner,
        dataset_route_min_bytes=_env_int(
            "LEVIATHAN_SOURCE_INGESTION_DATASET_ROUTE_MIN_BYTES",
            32 * 1024 * 1024,
        ),
        code_repo_ignore_defaults=_env_bool(
            "LEVIATHAN_SOURCE_INGESTION_CODE_REPO_IGNORE_DEFAULTS",
            True,
        ),
    )
    settings.validate()
    return settings
