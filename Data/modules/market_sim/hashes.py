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


# Public aliases matching the Master Program names
RunInputFingerprint = run_input_fingerprint
CheckpointStateHash = checkpoint_state_hash
TrajectoryHash = trajectory_hash
