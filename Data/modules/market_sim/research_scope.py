"""Multi-asset / multi-timeframe research scope — references only, no data duplication.

Wave 5: ResearchDatasetBundle points at existing source_ids / dataset versions.
Episodes are scheduled per source. Missing PIT data → UNMEASURED (never invented).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .learning_types import MeasurementStatus


class EdgeScope(str, Enum):
    """What kind of edge a research objective claims to seek."""

    ASSET_SPECIFIC_EDGE = "ASSET_SPECIFIC_EDGE"
    REGIME_SPECIFIC_EDGE = "REGIME_SPECIFIC_EDGE"
    GENERALIZED_EDGE = "GENERALIZED_EDGE"


def validate_edge_scope(raw: str | None) -> str:
    text = str(raw or EdgeScope.ASSET_SPECIFIC_EDGE.value).strip().upper()
    try:
        return EdgeScope(text).value
    except ValueError as exc:
        raise ValueError(f"unsupported EdgeScope: {raw!r}") from exc


@dataclass(frozen=True)
class DatasetRef:
    """Pointer to an existing market-data source / dataset version — never a copy."""

    source_id: str
    dataset_id: str | None = None
    dataset_version: int | str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    role: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "role": self.role,
            "metadata": dict(self.metadata),
            "truth": {
                "reference_only_no_duplication": True,
                "missing_is_unmeasured": True,
            },
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "DatasetRef":
        raw = dict(raw or {})
        sid = str(raw.get("source_id") or raw.get("sourceId") or "").strip()
        if not sid:
            raise ValueError("DatasetRef requires source_id")
        ver = raw.get("dataset_version", raw.get("datasetVersion"))
        return cls(
            source_id=sid,
            dataset_id=(
                str(raw["dataset_id"])
                if raw.get("dataset_id") is not None
                else (str(raw["datasetId"]) if raw.get("datasetId") is not None else None)
            ),
            dataset_version=ver,
            symbol=(str(raw["symbol"]) if raw.get("symbol") is not None else None),
            timeframe=(str(raw["timeframe"]) if raw.get("timeframe") is not None else None),
            role=(str(raw["role"]) if raw.get("role") is not None else None),
            metadata=dict(raw.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ResearchDatasetBundle:
    """Bundle of dataset refs for multi-asset / multi-timeframe research."""

    bundle_id: str
    refs: tuple[DatasetRef, ...]
    edge_scope: str = EdgeScope.ASSET_SPECIFIC_EDGE.value
    primary_source_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_scope", validate_edge_scope(self.edge_scope))
        if not self.refs:
            raise ValueError("ResearchDatasetBundle requires at least one DatasetRef")
        primary = self.primary_source_id or self.refs[0].source_id
        object.__setattr__(self, "primary_source_id", primary)

    @property
    def source_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for ref in self.refs:
            if ref.source_id not in seen:
                seen.append(ref.source_id)
        return tuple(seen)

    @property
    def universe(self) -> tuple[str, ...]:
        """Symbol universe derived from refs (empty symbols omitted)."""
        out: list[str] = []
        for ref in self.refs:
            sym = (ref.symbol or "").strip()
            if sym and sym not in out:
                out.append(sym)
        return tuple(out)

    @property
    def timeframes(self) -> tuple[str, ...]:
        out: list[str] = []
        for ref in self.refs:
            tf = (ref.timeframe or "").strip()
            if tf and tf not in out:
                out.append(tf)
        return tuple(out)

    def public_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "refs": [r.public_dict() for r in self.refs],
            "edge_scope": self.edge_scope,
            "primary_source_id": self.primary_source_id,
            "source_ids": list(self.source_ids),
            "universe": list(self.universe),
            "timeframes": list(self.timeframes),
            "metadata": dict(self.metadata),
            "truth": {
                "no_data_duplication": True,
                "point_in_time_safe": True,
                "missing_data_is_unmeasured": True,
            },
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "ResearchDatasetBundle":
        raw = dict(raw or {})
        refs_raw = raw.get("refs") or raw.get("datasets") or []
        refs = tuple(DatasetRef.from_dict(r) for r in refs_raw)
        return cls(
            bundle_id=str(raw.get("bundle_id") or raw.get("bundleId") or uuid.uuid4()),
            refs=refs,
            edge_scope=str(raw.get("edge_scope") or raw.get("edgeScope") or EdgeScope.ASSET_SPECIFIC_EDGE.value),
            primary_source_id=(
                str(raw["primary_source_id"])
                if raw.get("primary_source_id") is not None
                else (
                    str(raw["primarySourceId"])
                    if raw.get("primarySourceId") is not None
                    else None
                )
            ),
            metadata=dict(raw.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ResearchScope:
    """Optional research scope bound to a lab / learning objective."""

    edge_scope: str = EdgeScope.ASSET_SPECIFIC_EDGE.value
    dataset_bundle: ResearchDatasetBundle | None = None
    regimes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_scope", validate_edge_scope(self.edge_scope))

    def public_dict(self) -> dict[str, Any]:
        return {
            "edge_scope": self.edge_scope,
            "dataset_bundle": self.dataset_bundle.public_dict() if self.dataset_bundle else None,
            "regimes": list(self.regimes),
            "metadata": dict(self.metadata),
            "truth": {
                "optional_single_source_compatible": True,
                "missing_data_is_unmeasured": True,
            },
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "ResearchScope":
        raw = dict(raw or {})
        bundle_raw = raw.get("dataset_bundle") or raw.get("datasetBundle")
        bundle = ResearchDatasetBundle.from_dict(bundle_raw) if bundle_raw else None
        regimes = raw.get("regimes") or raw.get("regime_scope") or ()
        edge = (
            raw.get("edge_scope")
            or raw.get("edgeScope")
            or (bundle.edge_scope if bundle else EdgeScope.ASSET_SPECIFIC_EDGE.value)
        )
        return cls(
            edge_scope=str(edge),
            dataset_bundle=bundle,
            regimes=tuple(str(r) for r in regimes),
            metadata=dict(raw.get("metadata") or {}),
        )


@dataclass(frozen=True)
class EpisodeScheduleItem:
    """One scheduled evaluation episode for a single source ref."""

    episode_id: str
    source_id: str
    dataset_id: str | None
    dataset_version: int | str | None
    symbol: str | None
    timeframe: str | None
    edge_scope: str
    measurement_status: str = MeasurementStatus.UNMEASURED.value
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "source_id": self.source_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "edge_scope": self.edge_scope,
            "measurement_status": self.measurement_status,
            "metadata": dict(self.metadata),
        }


def schedule_episodes_per_source(
    bundle: ResearchDatasetBundle,
    *,
    available_source_ids: Iterable[str] | None = None,
) -> list[EpisodeScheduleItem]:
    """Schedule a separate episode per dataset ref.

    Sources absent from ``available_source_ids`` (when provided) remain
    scheduled but marked UNMEASURED — never fabricate bars.
    """
    available = {str(s) for s in available_source_ids} if available_source_ids is not None else None
    out: list[EpisodeScheduleItem] = []
    for i, ref in enumerate(bundle.refs):
        present = available is None or ref.source_id in available
        status = MeasurementStatus.MEASURED.value if present else MeasurementStatus.UNMEASURED.value
        out.append(
            EpisodeScheduleItem(
                episode_id=f"{bundle.bundle_id}:{i}:{ref.source_id}",
                source_id=ref.source_id,
                dataset_id=ref.dataset_id,
                dataset_version=ref.dataset_version,
                symbol=ref.symbol,
                timeframe=ref.timeframe,
                edge_scope=bundle.edge_scope,
                measurement_status=status,
                metadata={
                    "ref_index": i,
                    "source_present": present,
                    **dict(ref.metadata),
                },
            )
        )
    return out


def resolve_ref_measurement(
    ref: DatasetRef,
    *,
    source_exists: bool,
    bars_available: bool | None = None,
) -> dict[str, Any]:
    """Point-in-time safe measurement status for one ref — missing → UNMEASURED."""
    if not source_exists:
        return {
            "status": MeasurementStatus.UNMEASURED.value,
            "reason": "source_missing",
            "source_id": ref.source_id,
            "truth": {"missing_is_not_zero": True},
        }
    if bars_available is False:
        return {
            "status": MeasurementStatus.UNMEASURED.value,
            "reason": "bars_unavailable",
            "source_id": ref.source_id,
            "truth": {"missing_is_not_zero": True},
        }
    if bars_available is None:
        return {
            "status": MeasurementStatus.UNMEASURED.value,
            "reason": "bars_not_probed",
            "source_id": ref.source_id,
            "truth": {"missing_is_not_zero": True},
        }
    return {
        "status": MeasurementStatus.MEASURED.value,
        "reason": "source_and_bars_present",
        "source_id": ref.source_id,
    }


def parse_research_scope(
    *,
    research_scope: Mapping[str, Any] | ResearchScope | None = None,
    dataset_bundle: Mapping[str, Any] | ResearchDatasetBundle | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ResearchScope | None:
    """Parse optional research_scope / dataset_bundle from create_agent_lab inputs.

    Returns None when neither is provided (single-source path unchanged).
    """
    if isinstance(research_scope, ResearchScope):
        return research_scope
    if isinstance(dataset_bundle, ResearchDatasetBundle):
        return ResearchScope(
            edge_scope=dataset_bundle.edge_scope,
            dataset_bundle=dataset_bundle,
        )
    meta = dict(metadata or {})
    scope_raw = research_scope or meta.get("research_scope") or meta.get("researchScope")
    bundle_raw = dataset_bundle or meta.get("dataset_bundle") or meta.get("datasetBundle")
    if not scope_raw and not bundle_raw:
        return None
    if scope_raw and not isinstance(scope_raw, Mapping):
        raise ValueError("research_scope must be a mapping")
    if bundle_raw and not isinstance(bundle_raw, Mapping):
        raise ValueError("dataset_bundle must be a mapping")
    if scope_raw:
        scope = ResearchScope.from_dict(scope_raw)
        if bundle_raw and scope.dataset_bundle is None:
            return ResearchScope(
                edge_scope=scope.edge_scope,
                dataset_bundle=ResearchDatasetBundle.from_dict(bundle_raw),
                regimes=scope.regimes,
                metadata=scope.metadata,
            )
        return scope
    return ResearchScope(
        edge_scope=str(
            (bundle_raw or {}).get("edge_scope")
            or (bundle_raw or {}).get("edgeScope")
            or EdgeScope.ASSET_SPECIFIC_EDGE.value
        ),
        dataset_bundle=ResearchDatasetBundle.from_dict(bundle_raw),
    )


def bundle_from_single_source(
    source_id: str,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    dataset_id: str | None = None,
    dataset_version: int | str | None = None,
    edge_scope: str = EdgeScope.ASSET_SPECIFIC_EDGE.value,
) -> ResearchDatasetBundle:
    """Convenience: wrap the classic single-source path as a one-ref bundle."""
    return ResearchDatasetBundle(
        bundle_id=str(uuid.uuid4()),
        refs=(
            DatasetRef(
                source_id=source_id,
                symbol=symbol,
                timeframe=timeframe,
                dataset_id=dataset_id,
                dataset_version=dataset_version,
            ),
        ),
        edge_scope=edge_scope,
        primary_source_id=source_id,
    )


def objective_universe_from_scope(scope: ResearchScope | None, *, fallback: Sequence[str] = ()) -> tuple[str, ...]:
    if scope and scope.dataset_bundle and scope.dataset_bundle.universe:
        return scope.dataset_bundle.universe
    return tuple(fallback)


__all__ = [
    "DatasetRef",
    "EdgeScope",
    "EpisodeScheduleItem",
    "ResearchDatasetBundle",
    "ResearchScope",
    "bundle_from_single_source",
    "objective_universe_from_scope",
    "parse_research_scope",
    "resolve_ref_measurement",
    "schedule_episodes_per_source",
    "validate_edge_scope",
]
