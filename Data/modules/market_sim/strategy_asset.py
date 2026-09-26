"""Canonical StrategyAsset registry — governed reusable strategy assets (W14).

Extends existing StrategyRecord / StrategyVersion rather than inventing PortfolioV2
or a parallel registry. Promotion requires evidence; live_compatible is always false.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .features import FEATURE_PIPELINE_VERSION
from .types import MarketSimError, StrategyRecord, StrategyStatus, StrategyVersion


ASSET_STATUSES = frozenset(
    {
        StrategyStatus.DRAFT.value,
        StrategyStatus.RESEARCH.value,
        StrategyStatus.VALIDATED.value,
        StrategyStatus.CHAMPION.value,
        StrategyStatus.ACTIVE.value,
        StrategyStatus.RETIRED.value,
        StrategyStatus.ARCHIVED.value,
    }
)

PROMOTION_ORDER = (
    StrategyStatus.DRAFT.value,
    StrategyStatus.RESEARCH.value,
    StrategyStatus.VALIDATED.value,
    StrategyStatus.CHAMPION.value,
)


class CompatibilitySurface(str, Enum):
    HISTORICAL = "historical"
    PAPER = "paper"
    LIVE = "live"


@dataclass
class ExecutionCompatibilityManifest:
    """Per-version execution compatibility — parsing JSON is not enough to deploy."""

    required_feature_pipeline_version: str = FEATURE_PIPELINE_VERSION
    required_features: list[str] = field(default_factory=list)
    required_timeframes: list[str] = field(default_factory=list)
    supported_instrument_families: list[str] = field(default_factory=lambda: ["equity", "crypto_spot"])
    required_data_fields: list[str] = field(default_factory=lambda: ["open", "high", "low", "close", "volume"])
    regime_detector_version: str | None = None
    risk_model_version: str | None = None
    sizing_model_version: str | None = None
    cost_model_assumptions: dict[str, Any] = field(default_factory=dict)
    minimum_runtime_schema_version: str = "market_sim-1"
    model_dependencies: list[str] = field(default_factory=list)
    historical_compatible: bool = True
    paper_compatible: bool = True
    live_compatible: bool = False  # HARD: always false until A5 exists (it never will)

    def __post_init__(self) -> None:
        self.live_compatible = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "required_feature_pipeline_version": self.required_feature_pipeline_version,
            "required_features": list(self.required_features),
            "required_timeframes": list(self.required_timeframes),
            "supported_instrument_families": list(self.supported_instrument_families),
            "required_data_fields": list(self.required_data_fields),
            "regime_detector_version": self.regime_detector_version,
            "risk_model_version": self.risk_model_version,
            "sizing_model_version": self.sizing_model_version,
            "cost_model_assumptions": dict(self.cost_model_assumptions),
            "minimum_runtime_schema_version": self.minimum_runtime_schema_version,
            "model_dependencies": list(self.model_dependencies),
            "historical_compatible": self.historical_compatible,
            "paper_compatible": self.paper_compatible,
            "live_compatible": False,
            "truth": {
                "json_parse_is_not_deploy_authority": True,
                "live_compatible_always_false": True,
                "promotion_requires_evidence": True,
            },
        }

    def validate_against_runtime(
        self,
        *,
        feature_pipeline_version: str,
        available_features: set[str] | None = None,
        surface: CompatibilitySurface = CompatibilitySurface.HISTORICAL,
        available_timeframes: set[str] | None = None,
        runtime_schema_version: str | None = None,
        available_models: set[str] | None = None,
        instrument_family: str | None = None,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        if feature_pipeline_version != self.required_feature_pipeline_version:
            reasons.append(
                f"feature_pipeline_mismatch want={self.required_feature_pipeline_version} "
                f"have={feature_pipeline_version}"
            )
        # Missing available_features is not permission to skip a required check.
        if self.required_features:
            if available_features is None:
                reasons.append(
                    "available_features_unmeasured — cannot skip required feature compatibility check"
                )
            else:
                missing = [f for f in self.required_features if f not in available_features]
                if missing:
                    reasons.append(f"missing_features:{','.join(missing)}")
        if self.required_timeframes:
            if available_timeframes is None:
                reasons.append("available_timeframes_unmeasured")
            else:
                missing_tf = [t for t in self.required_timeframes if t not in available_timeframes]
                if missing_tf:
                    reasons.append(f"missing_timeframes:{','.join(missing_tf)}")
        if self.model_dependencies:
            if available_models is None:
                reasons.append("model_dependencies_unmeasured")
            else:
                missing_m = [m for m in self.model_dependencies if m not in available_models]
                if missing_m:
                    reasons.append(f"missing_models:{','.join(missing_m)}")
        if instrument_family and instrument_family not in self.supported_instrument_families:
            reasons.append(f"unsupported_instrument_family:{instrument_family}")
        if runtime_schema_version is not None and runtime_schema_version < self.minimum_runtime_schema_version:
            reasons.append(
                f"runtime_schema_too_old want>={self.minimum_runtime_schema_version} have={runtime_schema_version}"
            )
        if surface == CompatibilitySurface.LIVE or self.live_compatible:
            reasons.append("live_compatible_blocked")
        if surface == CompatibilitySurface.PAPER and not self.paper_compatible:
            reasons.append("not_paper_compatible")
        if surface == CompatibilitySurface.HISTORICAL and not self.historical_compatible:
            reasons.append("not_historical_compatible")
        ok = not reasons
        return {
            "ok": ok,
            "surface": surface.value,
            "reasons": reasons,
            "measurement": "MEASURED",
            "truth": {
                "reject_incompatible_deployment": True,
                "missing_available_features_is_not_skip": True,
            },
        }


@dataclass
class StrategyAsset:
    """Governed strategy asset — wraps StrategyRecord fields + registry metadata."""

    asset_id: str
    name: str
    version: int
    status: str = StrategyStatus.DRAFT.value
    parent_asset_id: str | None = None
    parent_version: int | None = None
    content_hash: str = ""
    author: str = ""
    created_at: str = ""
    tags: list[str] = field(default_factory=list)
    universe_constraints: list[str] = field(default_factory=list)
    timeframe_requirements: list[str] = field(default_factory=list)
    regime_affinity: list[str] = field(default_factory=list)
    evaluation_refs: list[str] = field(default_factory=list)
    sealed_refs: list[str] = field(default_factory=list)
    lessons_refs: list[str] = field(default_factory=list)
    compatibility: ExecutionCompatibilityManifest = field(default_factory=ExecutionCompatibilityManifest)
    immutable_spec: dict[str, Any] = field(default_factory=dict)
    promotion_evidence: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "parent_asset_id": self.parent_asset_id,
            "parent_version": self.parent_version,
            "content_hash": self.content_hash,
            "author": self.author,
            "created_at": self.created_at,
            "tags": list(self.tags),
            "universe_constraints": list(self.universe_constraints),
            "timeframe_requirements": list(self.timeframe_requirements),
            "regime_affinity": list(self.regime_affinity),
            "evaluation_refs": list(self.evaluation_refs),
            "sealed_refs": list(self.sealed_refs),
            "lessons_refs": list(self.lessons_refs),
            "compatibility": self.compatibility.public_dict(),
            "immutable_spec": dict(self.immutable_spec),
            "promotion_evidence": dict(self.promotion_evidence),
            "metadata": dict(self.metadata),
            "truth": {
                "promotion_requires_evidence": True,
                "live_compatible": False,
                "extends_strategy_record": True,
            },
        }

    def to_strategy_record(self) -> StrategyRecord:
        return StrategyRecord(
            strategy_id=self.asset_id,
            name=self.name,
            description=str(self.metadata.get("description") or ""),
            status=self.status,
            tags=list(self.tags),
            current_version=self.version,
            content_hash=self.content_hash,
            created_at=self.created_at,
            updated_at=self.created_at,
            metadata={
                **dict(self.metadata),
                "strategy_asset": True,
                "universe_constraints": list(self.universe_constraints),
                "regime_affinity": list(self.regime_affinity),
                "compatibility": self.compatibility.public_dict(),
                "promotion_evidence": dict(self.promotion_evidence),
            },
        )


def content_hash_for_spec(spec: dict[str, Any]) -> str:
    blob = json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def from_strategy_record(record: StrategyRecord, *, version: StrategyVersion | None = None) -> StrategyAsset:
    meta = dict(record.metadata or {})
    compat_raw = meta.get("compatibility") or {}
    compat = ExecutionCompatibilityManifest(
        required_feature_pipeline_version=str(
            compat_raw.get("required_feature_pipeline_version") or FEATURE_PIPELINE_VERSION
        ),
        required_features=list(compat_raw.get("required_features") or []),
        required_timeframes=list(
            compat_raw.get("required_timeframes")
            or (version.required_timeframes if version else [])
            or []
        ),
        supported_instrument_families=list(
            compat_raw.get("supported_instrument_families") or ["equity", "crypto_spot"]
        ),
        required_data_fields=list(
            compat_raw.get("required_data_fields") or ["open", "high", "low", "close", "volume"]
        ),
        regime_detector_version=compat_raw.get("regime_detector_version"),
        risk_model_version=compat_raw.get("risk_model_version"),
        sizing_model_version=compat_raw.get("sizing_model_version"),
        cost_model_assumptions=dict(compat_raw.get("cost_model_assumptions") or {}),
        minimum_runtime_schema_version=str(
            compat_raw.get("minimum_runtime_schema_version") or "market_sim-1"
        ),
        model_dependencies=list(compat_raw.get("model_dependencies") or []),
        historical_compatible=bool(compat_raw.get("historical_compatible", True)),
        paper_compatible=bool(compat_raw.get("paper_compatible", True)),
        live_compatible=False,
    )
    immutable: dict[str, Any] = {}
    if version is not None:
        immutable = {
            "parameters": dict(version.parameters),
            "entry_rules": dict(version.entry_rules),
            "exit_rules": dict(version.exit_rules),
            "risk_rules": dict(version.risk_rules),
        }
    return StrategyAsset(
        asset_id=record.strategy_id,
        name=record.name,
        version=record.current_version,
        status=record.status,
        content_hash=record.content_hash,
        created_at=record.created_at,
        tags=list(record.tags),
        universe_constraints=list(meta.get("universe_constraints") or []),
        timeframe_requirements=list(compat.required_timeframes),
        regime_affinity=list(meta.get("regime_affinity") or []),
        evaluation_refs=list(meta.get("evaluation_refs") or []),
        sealed_refs=list(meta.get("sealed_refs") or []),
        lessons_refs=list(meta.get("lessons_refs") or []),
        compatibility=compat,
        immutable_spec=immutable,
        promotion_evidence=dict(meta.get("promotion_evidence") or {}),
        metadata=meta,
        parent_asset_id=meta.get("parent_asset_id"),
        parent_version=meta.get("parent_version"),
        author=str(meta.get("author") or ""),
    )


def promote_asset(
    asset: StrategyAsset,
    *,
    target_status: str,
    evidence: dict[str, Any],
) -> StrategyAsset:
    """Promote only with server-resolvable evidence. Caller booleans are not proof."""
    target = str(target_status).upper()
    if target not in ASSET_STATUSES:
        raise MarketSimError("STRATEGY_STATUS_INVALID", f"unknown status {target}")
    ev = dict(evidence or {})
    # Reject bare accepted=True / acceptance={"passed": True} without refs or metrics.
    acceptance = ev.get("acceptance")
    bare_bool = ev.get("accepted") is True and not (
        ev.get("evaluation_refs") or ev.get("trial_ids") or isinstance(acceptance, dict)
    )
    bare_acceptance = (
        isinstance(acceptance, dict)
        and acceptance.get("passed") is True
        and not (
            acceptance.get("run_id")
            or acceptance.get("criteria_id")
            or acceptance.get("metrics")
            or ev.get("evaluation_refs")
        )
    )
    if bare_bool or bare_acceptance:
        raise MarketSimError(
            "PROMOTION_EVIDENCE_INSUFFICIENT",
            "caller-supplied accepted/passed boolean is not authoritative proof",
            http_status=409,
        )
    if target in {StrategyStatus.VALIDATED.value, StrategyStatus.CHAMPION.value, StrategyStatus.RESEARCH.value}:
        if not ev:
            raise MarketSimError(
                "PROMOTION_EVIDENCE_REQUIRED",
                "promotion requires evidence refs (evals/trials/acceptance)",
                http_status=409,
            )
    if target == StrategyStatus.CHAMPION.value:
        if asset.status not in {StrategyStatus.VALIDATED.value, StrategyStatus.CHAMPION.value}:
            raise MarketSimError(
                "PROMOTION_ORDER",
                "CHAMPION requires VALIDATED status first",
                http_status=409,
            )
        if not (ev.get("evaluation_refs") or asset.evaluation_refs):
            raise MarketSimError(
                "PROMOTION_EVIDENCE_REQUIRED",
                "CHAMPION requires evaluation_refs",
                http_status=409,
            )
    if target == StrategyStatus.VALIDATED.value and not (
        (
            isinstance(acceptance, dict)
            and acceptance.get("passed") is True
            and (acceptance.get("run_id") or acceptance.get("metrics") or acceptance.get("criteria_id"))
        )
        or ev.get("evaluation_refs")
    ):
        raise MarketSimError(
            "PROMOTION_EVIDENCE_REQUIRED",
            "VALIDATED requires resolved acceptance (run/metrics/criteria) or evaluation_refs",
            http_status=409,
        )
    asset.status = target
    asset.promotion_evidence = {
        **dict(asset.promotion_evidence),
        **ev,
        "promoted_to": target,
    }
    if ev.get("evaluation_refs"):
        asset.evaluation_refs = list(
            dict.fromkeys([*asset.evaluation_refs, *list(ev["evaluation_refs"])])
        )
    return asset
