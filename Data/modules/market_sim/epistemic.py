"""Complete trading epistemic-time firewall.

Historical agents may only access information with ``available_at <= as_of``.
Event time alone is insufficient — publication / availability is the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .types import CausalityViolation, MarketSimError


class EvaluationWindow(str, Enum):
    """Chronological evaluation windows — never shuffle financial time."""

    RESEARCH = "RESEARCH"
    VALIDATION = "VALIDATION"
    SEALED_TEST = "SEALED_TEST"
    LIVE_SHADOW = "LIVE_SHADOW"
    LIVE_PAPER = "LIVE_PAPER"


class TemporalClass(str, Enum):
    """Information temporal class for historical decision access."""

    TIME_SENSITIVE = "TIME_SENSITIVE"
    TIMELESS_REFERENCE = "TIMELESS_REFERENCE"
    UNKNOWN = "UNKNOWN"


# Keys inspected when resolving availability on heterogeneous records.
_AVAILABLE_AT_KEYS = (
    "available_at",
    "availableAt",
)
_FALLBACK_TIME_KEYS = (
    "publication_time",
    "published_at",
    "publishedAt",
    "effective_at",
    "effectiveAt",
    "observed_at",
    "observedAt",
    "ingested_at",
    "ingestedAt",
    "received_at",
    "receivedAt",
    "provider_time",
    "providerTime",
    "created_at",
    "createdAt",
    "timestamp",
    "ts",
    "event_time",
    "eventTime",
)

_TIMELESS_MARKERS = (
    "timeless",
    "TIMELESS_REFERENCE",
    "reference_definition",
    "educational_reference",
    "general_reference",
)


def parse_ts(value: str | datetime | None) -> datetime | None:
    """Parse ISO / common market timestamps to timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise MarketSimError(
            "INVALID_TIMESTAMP",
            f"Cannot parse timestamp for causal compare: {text!r}",
            http_status=400,
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compare_ts(a: str | datetime, b: str | datetime) -> int:
    """Return -1 / 0 / 1 for a < b / a == b / a > b (UTC-aware)."""
    da = parse_ts(a)
    db = parse_ts(b)
    if da is None or db is None:
        raise MarketSimError("INVALID_TIMESTAMP", "Missing timestamp for causal compare")
    if da < db:
        return -1
    if da > db:
        return 1
    return 0


def is_available(*, available_at: str | datetime, as_of: str | datetime) -> bool:
    """True iff available_at <= as_of (the epistemic boundary)."""
    return compare_ts(available_at, as_of) <= 0


def resolve_available_at(record: Mapping[str, Any]) -> str | None:
    """Resolve the causal availability stamp from a heterogeneous record."""
    for key in _AVAILABLE_AT_KEYS:
        value = record.get(key)
        if value:
            return str(value)
    meta = record.get("metadata")
    if isinstance(meta, dict):
        for key in _AVAILABLE_AT_KEYS:
            value = meta.get(key)
            if value:
                return str(value)
    # Prefer max(publication, received) when both exist — information cannot
    # be known before it was published AND received.
    candidates: list[str] = []
    for key in _FALLBACK_TIME_KEYS:
        value = record.get(key)
        if value:
            candidates.append(str(value))
        if isinstance(meta, dict):
            mval = meta.get(key)
            if mval:
                candidates.append(str(mval))
    if not candidates:
        return None
    parsed = [(parse_ts(c), c) for c in candidates]
    parsed = [(dt, raw) for dt, raw in parsed if dt is not None]
    if not parsed:
        return None
    # Latest of known stamps is the conservative availability bound.
    parsed.sort(key=lambda item: item[0])
    return parsed[-1][1]


def resolve_temporal_class(record: Mapping[str, Any]) -> TemporalClass:
    """Classify whether content may be treated as timeless reference knowledge.

    Missing timestamp must NOT automatically imply timeless.
    Only explicitly marked reference/general educational content is timeless.
    """
    for key in ("temporal_class", "temporalClass", "knowledge_class", "knowledgeClass"):
        raw = record.get(key)
        if raw:
            try:
                return TemporalClass(str(raw).upper())
            except ValueError:
                pass
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for key in ("temporal_class", "temporalClass", "knowledge_class", "knowledgeClass"):
        raw = meta.get(key)
        if raw:
            try:
                return TemporalClass(str(raw).upper())
            except ValueError:
                pass
    for marker in _TIMELESS_MARKERS:
        if record.get(marker) is True or meta.get(marker) is True:
            return TemporalClass.TIMELESS_REFERENCE
        if str(record.get("kind") or "").lower() == marker.lower():
            return TemporalClass.TIMELESS_REFERENCE
        if str(meta.get("kind") or "").lower() == marker.lower():
            return TemporalClass.TIMELESS_REFERENCE
    # Explicit content-type hints for trading/news/fundamentals are time-sensitive.
    source_kind = str(record.get("source_kind") or record.get("sourceKind") or record.get("source") or "").lower()
    title = str(record.get("title") or "").lower()
    if any(tok in source_kind or tok in title for tok in ("news", "filing", "earnings", "fundamental", "macro", "quote", "trade")):
        return TemporalClass.TIME_SENSITIVE
    if resolve_available_at(record) is not None:
        return TemporalClass.TIME_SENSITIVE
    return TemporalClass.UNKNOWN


@dataclass
class LeakageReceipt:
    """Bounded truth metadata when future information is excluded."""

    reason: str
    as_of: str
    available_at: str | None = None
    temporal_class: str | None = None
    document_id: str | None = None
    source_kind: str | None = None
    title: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "asOf": self.as_of,
            "availableAt": self.available_at,
            "temporalClass": self.temporal_class,
            "documentId": self.document_id,
            "sourceKind": self.source_kind,
            "title": (self.title or "")[:120],
            "truth": {
                "content_blob_not_logged": True,
                "available_at_is_primary_boundary": True,
            },
        }


def filter_hits_for_as_of(
    hits: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    time_sensitive_default: bool = True,
    allow_timeless_reference: bool = True,
    firewall: EpistemicFirewall | None = None,
) -> tuple[list[dict[str, Any]], list[LeakageReceipt]]:
    """Fail-closed filter for historical trading knowledge/data access.

    Rules:
    - TIMELESS_REFERENCE may pass without available_at when explicitly marked.
    - TIME_SENSITIVE / UNKNOWN without available_at are blocked by default.
    - available_at > as_of is blocked.
    """
    kept: list[dict[str, Any]] = []
    receipts: list[LeakageReceipt] = []
    for raw in hits:
        item = dict(raw)
        # Neuro assessments generated at decision time are not historical docs.
        if str(item.get("source") or "") == "neuro":
            kept.append(item)
            continue
        temporal = resolve_temporal_class(item)
        stamp = resolve_available_at(item)
        doc_id = item.get("document_id") or item.get("documentId") or item.get("refId")
        title = item.get("title")
        source_kind = item.get("source_kind") or item.get("sourceKind") or item.get("source")

        if stamp is None:
            if temporal == TemporalClass.TIMELESS_REFERENCE and allow_timeless_reference:
                kept.append(item)
                continue
            # Missing timestamp: NOT timeless by default.
            if time_sensitive_default or temporal in {
                TemporalClass.TIME_SENSITIVE,
                TemporalClass.UNKNOWN,
            }:
                if firewall is not None:
                    firewall.violations += 1
                receipts.append(
                    LeakageReceipt(
                        reason="missing_available_at_blocked",
                        as_of=as_of,
                        available_at=None,
                        temporal_class=temporal.value,
                        document_id=str(doc_id) if doc_id else None,
                        source_kind=str(source_kind) if source_kind else None,
                        title=str(title) if title else None,
                    )
                )
                continue
            kept.append(item)
            continue

        if not is_available(available_at=stamp, as_of=as_of):
            if firewall is not None:
                firewall.violations += 1
            receipts.append(
                LeakageReceipt(
                    reason="available_at_after_as_of",
                    as_of=as_of,
                    available_at=str(stamp),
                    temporal_class=temporal.value,
                    document_id=str(doc_id) if doc_id else None,
                    source_kind=str(source_kind) if source_kind else None,
                    title=str(title) if title else None,
                )
            )
            continue
        kept.append(item)
    return kept, receipts


@dataclass(frozen=True)
class TimedWindow:
    """Inclusive chronological window bound to an evaluation role."""

    role: EvaluationWindow
    start_ts: str
    end_ts: str
    sealed: bool = False

    def contains(self, ts: str) -> bool:
        return compare_ts(self.start_ts, ts) <= 0 and compare_ts(ts, self.end_ts) <= 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "sealed": self.sealed,
        }


@dataclass
class EpistemicFirewall:
    """Authoritative as-of boundary for one historical / paper run.

    Agents, Brain, Memory, StrategyMemory, news and market views must consult
    this firewall rather than reading raw unrestricted stores.
    """

    as_of: str
    window: EvaluationWindow = EvaluationWindow.RESEARCH
    sealed_windows: list[TimedWindow] = field(default_factory=list)
    strategy_version: int | None = None
    run_id: str | None = None
    violations: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "window": self.window.value,
            "strategy_version": self.strategy_version,
            "run_id": self.run_id,
            "sealed_windows": [w.public_dict() for w in self.sealed_windows],
            "violations": self.violations,
            "truth": {
                "boundary": "available_at <= as_of",
                "event_time_alone_insufficient": True,
            },
        }

    def advance_as_of(self, ts: str) -> None:
        """Move the clock forward only (never backward)."""
        if compare_ts(ts, self.as_of) < 0:
            self.violations += 1
            raise CausalityViolation(
                f"Epistemic clock cannot move backward: {ts} < as_of {self.as_of}"
            )
        self.as_of = ts

    def assert_available(self, available_at: str | datetime | None, *, label: str = "record") -> None:
        if available_at is None:
            # Untimestamped time-sensitive records are refused in historical windows.
            if self.window in {
                EvaluationWindow.RESEARCH,
                EvaluationWindow.VALIDATION,
                EvaluationWindow.SEALED_TEST,
            }:
                self.violations += 1
                raise CausalityViolation(
                    f"{label} missing available_at under historical window {self.window.value}"
                )
            return
        if not is_available(available_at=available_at, as_of=self.as_of):
            self.violations += 1
            raise CausalityViolation(
                f"Look-ahead refused: {label} available_at={available_at} > as_of={self.as_of}"
            )

    def filter_records(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        label: str = "record",
        drop_missing: bool = True,
    ) -> list[dict[str, Any]]:
        """Return only records whose available_at <= as_of."""
        kept: list[dict[str, Any]] = []
        for raw in records:
            item = dict(raw)
            stamp = resolve_available_at(item)
            if stamp is None:
                if drop_missing:
                    continue
                self.assert_available(None, label=label)
                kept.append(item)
                continue
            if is_available(available_at=stamp, as_of=self.as_of):
                kept.append(item)
        return kept

    def assert_not_in_sealed_holdout(self, ts: str, *, purpose: str = "strategy_design") -> None:
        """Refuse sealed-holdout timestamps during research/design for this version."""
        if self.window == EvaluationWindow.SEALED_TEST:
            return  # Evaluator phase may read sealed window.
        for window in self.sealed_windows:
            if not window.sealed:
                continue
            if window.contains(ts):
                self.violations += 1
                raise CausalityViolation(
                    f"Sealed holdout refused during {purpose}: ts={ts} in "
                    f"{window.start_ts}..{window.end_ts}"
                )

    def assert_dataset_readable(
        self,
        *,
        dataset_sealed: bool,
        dataset_role: EvaluationWindow | str | None = None,
        purpose: str = "read",
    ) -> None:
        """Sealed test datasets are invisible during strategy creation/research."""
        role = dataset_role
        if isinstance(role, str):
            role = EvaluationWindow(role)
        if not dataset_sealed:
            return
        if role == EvaluationWindow.SEALED_TEST and self.window != EvaluationWindow.SEALED_TEST:
            self.violations += 1
            raise CausalityViolation(
                f"Sealed test dataset refused during window={self.window.value} purpose={purpose}"
            )


def assert_no_future_ts(timestamps: Sequence[str], clock_ts: str) -> None:
    """Fail if any timestamp is strictly after the clock (datetime-aware)."""
    for ts in timestamps:
        if compare_ts(ts, clock_ts) > 0:
            raise CausalityViolation(f"Event {ts} is after clock {clock_ts}")
