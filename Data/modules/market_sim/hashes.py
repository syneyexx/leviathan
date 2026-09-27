"""Three distinct run identity hashes — never conflate input / checkpoint / trajectory."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_input_fingerprint(
    *,
    dataset_content_hash: str,
    strategy_content_hash: str | None,
    seed: int,
    fee_bps: float,
    slippage_bps: float,
    execution_assumptions: Sequence[str] | None = None,
    intrabar_path_policy: str | None = None,
    feature_pipeline_version: str | None = None,
    risk_config: dict[str, Any] | None = None,
    sizing_config: dict[str, Any] | None = None,
    instrument_spec_version: str | None = None,
    code_version: str | None = None,
    reward_spec: dict[str, Any] | None = None,
) -> str:
    """IMMUTABLE — same experiment inputs?"""
    payload = {
        "dataset_content_hash": dataset_content_hash,
        "strategy_content_hash": strategy_content_hash or "",
        "seed": int(seed),
        "fee_bps": float(fee_bps),
        "slippage_bps": float(slippage_bps),
        "execution_assumptions": list(execution_assumptions or []),
        "intrabar_path_policy": intrabar_path_policy or "",
        "feature_pipeline_version": feature_pipeline_version or "",
        "risk_config": risk_config or {},
        "sizing_config": sizing_config or {},
        "instrument_spec_version": instrument_spec_version or "",
        "code_version": code_version or "",
        "reward_spec": reward_spec or {},
    }
    return _sha(_canon(payload))


def checkpoint_state_hash(
    *,
    run_id: str,
    bar_index: int,
    wallet_snapshot: dict[str, Any],
    positions: dict[str, Any] | None = None,
    pending_intents: Sequence[dict[str, Any]] | None = None,
    reserved_cash: Any = None,
    rng_state: Any = None,
    metrics_state: dict[str, Any] | None = None,
    active_decision_refs: Sequence[str] | None = None,
) -> str:
    """MUTABLE per checkpoint — exact this checkpoint state?"""
    payload = {
        "run_id": run_id,
        "bar_index": int(bar_index),
        "wallet_snapshot": wallet_snapshot,
        "positions": positions or {},
        "pending_intents": list(pending_intents or []),
        "reserved_cash": str(reserved_cash) if reserved_cash is not None else "0",
        "rng_state": rng_state,
        "metrics_state": metrics_state or {},
        "active_decision_refs": list(active_decision_refs or []),
    }
    return _sha(_canon(payload))


def trajectory_hash(events: Sequence[dict[str, Any]]) -> str:
    """Final / append-compatible — same trajectory?"""
    return _sha(_canon(list(events)))


def full_provenance_fingerprint(
    *,
    run_input_fp: str,
    dataset_content_hash: str,
    dataset_version: str | None = None,
    split_manifest_hash: str | None = None,
    objective_hash: str | None = None,
    strategy_version: str | None = None,
    feature_pipeline_version: str | None = None,
    execution_model_version: str | None = None,
    cost_model_version: str | None = None,
    risk_config_hash: str | None = None,
    code_version: str | None = None,
    git_sha: str | None = None,
    trial_ledger_refs: Sequence[str] | None = None,
    sealed_attempt_id: str | None = None,
    acceptance_criteria_hash: str | None = None,
) -> dict[str, Any]:
    """Canonical full provenance pack for qualification / audit reconstruction.

    Composes existing input fingerprint with dataset/split/objective/strategy
    lineage and trial references. Missing optional fields stay explicit empty
    strings — never silently defaulted to fabricated values.
    """
    payload = {
        "run_input_fingerprint": run_input_fp,
        "dataset_content_hash": dataset_content_hash,
        "dataset_version": dataset_version or "",
        "split_manifest_hash": split_manifest_hash or "",
        "objective_hash": objective_hash or "",
        "strategy_version": strategy_version or "",
        "feature_pipeline_version": feature_pipeline_version or "",
        "execution_model_version": execution_model_version or "",
        "cost_model_version": cost_model_version or "",
        "risk_config_hash": risk_config_hash or "",
        "code_version": code_version or "",
        "git_sha": git_sha or "",
        "trial_ledger_refs": list(trial_ledger_refs or []),
        "sealed_attempt_id": sealed_attempt_id or "",
        "acceptance_criteria_hash": acceptance_criteria_hash or "",
    }
    digest = _sha(_canon(payload))
    return {
        "fingerprint": digest,
        "components": payload,
        "truth": {
            "reconstructable_qualification_evidence": True,
            "missing_fields_are_explicit_empty": True,
            "not_a_profitability_claim": True,
        },
    }


# Public aliases matching the Master Program names
RunInputFingerprint = run_input_fingerprint
CheckpointStateHash = checkpoint_state_hash
TrajectoryHash = trajectory_hash
FullProvenanceFingerprint = full_provenance_fingerprint
