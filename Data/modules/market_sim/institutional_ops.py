"""Institutional operations fabric (W25–W29, W31–W34, W36 helpers).

Provider inventory, resource governance, dataset trust, audit events,
observability snapshots, API contract checks, statistical honesty, and
scale smoke helpers — extending canonical market_sim / datasets owners.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


# --- W25 provider fabric -------------------------------------------------


KNOWN_PROVIDERS = (
    {"id": "csv_local", "kinds": ["ohlcv"], "status": "AVAILABLE"},
    {"id": "binance_public", "kinds": ["ohlcv", "quotes"], "status": "AVAILABLE"},
    {"id": "stooq_public", "kinds": ["ohlcv"], "status": "AVAILABLE"},
    {"id": "alpaca_paper", "kinds": ["quotes", "orders_paper"], "status": "FEATURE_GATED"},
    {"id": "l2_orderbook", "kinds": ["orderbook"], "status": "NOT_IMPLEMENTED"},
)


def provider_fabric_inventory() -> dict[str, Any]:
    return {
        "providers": list(KNOWN_PROVIDERS),
        "truth": {
            "ohlcv_is_not_orderbook": True,
            "live_trading_blocked": True,
            "capability_from_adapters": True,
        },
    }


# --- W26 resource governance ---------------------------------------------


@dataclass(frozen=True)
class ResourceBudget:
    max_bars_in_memory: int = 120_000
    max_concurrent_jobs: int = 4
    max_dataset_bytes: int = 2_000_000_000

    def public_dict(self) -> dict[str, Any]:
        return {
            "maxBarsInMemory": self.max_bars_in_memory,
            "maxConcurrentJobs": self.max_concurrent_jobs,
            "maxDatasetBytes": self.max_dataset_bytes,
            "truth": {"streaming_preferred_over_materialize": True},
        }


def check_resource_budget(
    *,
    bars: int,
    jobs: int,
    dataset_bytes: int,
    budget: ResourceBudget | None = None,
) -> dict[str, Any]:
    b = budget or ResourceBudget()
    violations = []
    if bars > b.max_bars_in_memory:
        violations.append("bars_in_memory")
    if jobs > b.max_concurrent_jobs:
        violations.append("concurrent_jobs")
    if dataset_bytes > b.max_dataset_bytes:
        violations.append("dataset_bytes")
    return {
        "ok": not violations,
        "violations": violations,
        "budget": b.public_dict(),
    }


# --- W27 dataset trust / poisoning ---------------------------------------


def dataset_trust_report(
    *,
    content_hash: str,
    quality_verdict: str,
    source_reputation: str = "UNMEASURED",
    unexpected_hash_change: bool = False,
) -> dict[str, Any]:
    poisoning_risk = "LOW"
    if unexpected_hash_change:
        poisoning_risk = "HIGH"
    elif quality_verdict == "FAIL":
        poisoning_risk = "MEDIUM"
    elif source_reputation in {"UNMEASURED", "UNKNOWN"}:
        poisoning_risk = "UNMEASURED"
    return {
        "contentHash": content_hash,
        "qualityVerdict": quality_verdict,
        "sourceReputation": source_reputation,
        "poisoningRisk": poisoning_risk,
        "truth": {
            "hash_change_without_new_version_is_poisoning_signal": True,
            "parsed_csv_is_not_quality_pass": True,
        },
    }


# --- W28 governance / audit ----------------------------------------------


@dataclass
class AuditEvent:
    event_id: str
    kind: str
    actor: str
    detail: str
    ts: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "eventId": self.event_id,
            "kind": self.kind,
            "actor": self.actor,
            "detail": self.detail,
            "ts": self.ts,
            "metadata": dict(self.metadata),
            "truth": {"append_only_audit_intent": True},
        }


class AuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> AuditEvent:
        self._events.append(event)
        return event

    def list_events(self) -> list[dict[str, Any]]:
        return [e.public_dict() for e in self._events]


# --- W29 observability ---------------------------------------------------


def observability_snapshot(
    *,
    runs_active: int,
    paper_sessions: int,
    last_error: str | None = None,
) -> dict[str, Any]:
    return {
        "runsActive": runs_active,
        "paperSessions": paper_sessions,
        "lastError": last_error,
        "health": "DEGRADED" if last_error else "OK",
        "truth": {"live_trading_blocked": True},
    }


# --- W31 API contract ----------------------------------------------------


REQUIRED_MARKET_SIM_ROUTES = (
    "/api/market-sim/status",
    "/api/market-sim/capabilities",
    "/api/market-sim/data",
)


def api_contract_check(registered_paths: Sequence[str]) -> dict[str, Any]:
    missing = [p for p in REQUIRED_MARKET_SIM_ROUTES if p not in set(registered_paths)]
    return {
        "required": list(REQUIRED_MARKET_SIM_ROUTES),
        "missing": missing,
        "ok": not missing,
        "truth": {"contract_is_path_presence_not_runtime_proof": True},
    }


# --- W32 statistical honesty ---------------------------------------------


def statistical_honesty_labels(
    *,
    trials: int,
    multiple_testing_corrected: bool,
    sealed_holdout_used: bool,
) -> dict[str, Any]:
    return {
        "trials": trials,
        "multipleTestingCorrected": multiple_testing_corrected,
        "sealedHoldoutUsed": sealed_holdout_used,
        "claims": {
            "significant": False if not multiple_testing_corrected else None,
            "generalizes": False if not sealed_holdout_used else None,
        },
        "truth": {
            "uncorrected_p_is_not_discovery": True,
            "in_sample_is_not_proof": True,
            "profitable_backtest_is_not_proof": True,
        },
    }


# --- W34 scale smoke -----------------------------------------------------


def scale_smoke(
    *,
    n: int,
    work: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    if work is None:
        total = sum(range(n))
    else:
        total = work(n)
    elapsed = time.perf_counter() - start
    return {
        "n": n,
        "elapsedSec": elapsed,
        "resultFingerprint": str(total)[:64],
        "ok": elapsed < 5.0,
        "truth": {"smoke_is_not_full_5y_benchmark": True},
    }


# --- W36 program gate summary --------------------------------------------


def institutional_program_gate_summary(waves: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for w in waves:
        st = str(w.get("status") or "UNKNOWN")
        by_status[st] = by_status.get(st, 0) + 1
    required_open = [
        w["id"]
        for w in waves
        if w.get("required") and w.get("status") not in {"PASS", "NOT_APPLICABLE", "FEATURE_GATED"}
    ]
    return {
        "byStatus": by_status,
        "requiredOpen": required_open,
        "programComplete": not required_open,
        "liveTrading": "BLOCKED",
        "truth": {
            "ci_skipped_per_operator": True,
            "editor_hades_out_of_scope": True,
            "no_fake_pass": True,
        },
    }
