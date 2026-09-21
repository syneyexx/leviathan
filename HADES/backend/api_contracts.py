"""Shared transport contracts for important API responses (work package L).

Used by OpenAPI generation and explicit response_model annotations. Keep
nullability, enums, time fields, pagination and error objects honest here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiErrorBody(BaseModel):
    detail: str
    code: str | None = None
    retryable: bool | None = None


class PageMeta(BaseModel):
    """Pagination / truncation metadata shared across list endpoints."""

    limit: int = Field(ge=1)
    offset: int = Field(default=0, ge=0)
    returned: int = Field(ge=0)
    truncated: bool = False
    total_hint: int | None = None


class IsoTimestamp(BaseModel):
    """Document ISO-8601 string fields at the transport boundary."""

    value: str = Field(description="ISO-8601 UTC timestamp, preferably with offset or Z")


class CodingJobsListResponse(BaseModel):
    jobs: list[dict[str, Any]]
    page: PageMeta | None = None


class HostCapabilityStatus(BaseModel):
    status: Literal[
        "PASS",
        "FAIL",
        "SKIPPED",
        "UNAVAILABLE",
        "UNVERIFIED_ON_HOST",
        "DEGRADED",
        "SIMULATED_ONLY",
    ]
    detail: str | None = None
