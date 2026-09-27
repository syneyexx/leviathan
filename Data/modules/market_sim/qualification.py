"""Canonical scientific qualification authority for institutional market research.

Orchestrates evidence from existing MarketSim owners — does NOT compute fills,
PnL, or risk itself. Live-money trading remains BLOCKED.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

from .institutional_core.status import MeasurementState


QualificationRunState = Literal[
    "CREATED",
    "QUEUED",
    "RUNNING",
    "BLOCKED",
    "QUALIFIED",
    "REJECTED",
    "FAILED",
    "CANCELLED",
]

GATE_ORDER: tuple[str, ...] = (
    "Q01_DATA_CERTIFICATION",
    "Q02_REPRODUCIBILITY",
    "Q03_BASELINE_ACCEPTANCE",
    "Q04_WALK_FORWARD",
    "Q05_STATISTICAL_MULTIPLICITY",
    "Q06_REGIME_MATRIX",
    "Q07_ADVERSARIAL_ROBUSTNESS",
    "Q08_EXECUTION_VALIDITY",
    "Q09_CAPACITY",
    "Q10_SEALED_HOLDOUT",
    "Q11_PORTFOLIO_COMPATIBILITY",
)

# Short aliases used in evidence / API.
GATE_ALIASES: dict[str, str] = {
    "Q01": "Q01_DATA_CERTIFICATION",
    "Q02": "Q02_REPRODUCIBILITY",
    "Q03": "Q03_BASELINE_ACCEPTANCE",
    "Q04": "Q04_WALK_FORWARD",
    "Q05": "Q05_STATISTICAL_MULTIPLICITY",
    "Q06": "Q06_REGIME_MATRIX",
    "Q07": "Q07_ADVERSARIAL_ROBUSTNESS",
    "Q08": "Q08_EXECUTION_VALIDITY",
    "Q09": "Q09_CAPACITY",
    "Q10": "Q10_SEALED_HOLDOUT",
    "Q11": "Q11_PORTFOLIO_COMPATIBILITY",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(payload: str | bytes) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class QualificationPolicy:
    policy_id: str
    version: int
    name: str
    require_data_certification: bool = True
    require_reproducibility: bool = True
    require_wfa: bool = True
    require_statistical_multiplicity: bool = True
    require_regime_matrix: bool = True
    require_robustness: bool = True
    require_execution_validity: bool = True
    require_capacity: bool = True
    require_sealed: bool = True
    require_portfolio_compatibility: bool = True
    min_trades: int = 30
    min_observations: int = 100
    max_drawdown_pct: float | None = 25.0
    min_wfa_folds: int = 3
    min_wfa_pass_ratio: float = 0.6
    max_pbo: float | None = 0.4
    fdr_q: float | None = 0.1
    min_robustness_pass_ratio: float = 0.7
    operating_envelope: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    diagnostic_continuation: bool = False

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)

    def policy_hash(self) -> str:
        return hash_policy(self)


def hash_policy(policy: QualificationPolicy | Mapping[str, Any]) -> str:
    data = policy.public_dict() if isinstance(policy, QualificationPolicy) else dict(policy)
    # Exclude volatile identity fields from content hash identity of thresholds.
    body = {k: v for k, v in data.items() if k not in {"policy_id"}}
    return sha256_hex(_canonical_json(body))


def default_institutional_policy(
    *,
    policy_id: str | None = None,
    version: int = 1,
    name: str = "institutional_default_v1",
) -> QualificationPolicy:
    return QualificationPolicy(
        policy_id=policy_id or f"qp_{uuid.uuid4().hex[:12]}",
        version=version,
        name=name,
        operating_envelope={
            "live_trading": "BLOCKED",
            "data_level": "BAR",
            "supported_strategy_kinds": ["dsl"],
        },
    )


@dataclass
class QualificationGateResult:
    gate_id: str
    state: str
    passed: bool
    methodology: str
    evidence: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    input_hash: str = ""
    output_hash: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "state": self.state,
            "passed": self.passed,
            "methodology": self.methodology,
            "evidence": dict(self.evidence),
            "metrics": dict(self.metrics),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
        }


@dataclass
class QualificationContext:
    qualification_id: str
    strategy_id: str
    strategy_version: int
    strategy_hash: str
    source_id: str
    dataset_hash: str
    git_sha: str
    code_version: str
    seed: int
    trial_family_id: str
    experiment_id: str | None = None
    learning_run_id: str | None = None
    candidate_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    sealed_attempt_id: str | None = None
    feature_pipeline_hash: str = ""
    execution_model_hash: str = ""
    cost_model_hash: str = ""
    risk_model_hash: str = ""
    sizing_model_hash: str = ""
    split_manifest_hash: str = ""
    dirty: bool = False
    diff_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def hash_provenance(context: QualificationContext | Mapping[str, Any], policy_hash: str) -> str:
    data = context.public_dict() if isinstance(context, QualificationContext) else dict(context)
    pack = {
        "context": data,
        "policy_hash": policy_hash,
    }
    return sha256_hex(_canonical_json(pack))


@dataclass
class QualificationDecision:
    qualification_id: str
    state: str
    qualified: bool
    gate_results: list[QualificationGateResult] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance_hash: str = ""
    policy_hash: str = ""
    policy_id: str = ""
    created_at: str = ""
    finished_at: str | None = None
    current_gate: str | None = None
    truth: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "qualification_id": self.qualification_id,
            "state": self.state,
            "qualified": self.qualified,
            "gate_results": [g.public_dict() for g in self.gate_results],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "provenance_hash": self.provenance_hash,
            "policy_hash": self.policy_hash,
            "policy_id": self.policy_id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "current_gate": self.current_gate,
            "truth": {
                "live_trading": "BLOCKED",
                "caller_passed_boolean_not_authority": True,
                "train_only_cannot_qualify": True,
                **dict(self.truth),
            },
        }


def _normalize_gate_id(gate_id: str) -> str:
    raw = str(gate_id or "").strip().upper()
    if raw in GATE_ORDER:
        return raw
    if raw in GATE_ALIASES:
        return GATE_ALIASES[raw]
    # Allow Q01_DATA_CERTIFICATION style already full
    for full in GATE_ORDER:
        if full.startswith(raw) or raw.startswith(full.split("_")[0]):
            if raw == full.split("_")[0] or raw == full:
                return full
    return raw


def _gate_required(policy: QualificationPolicy, gate_id: str) -> bool:
    mapping = {
        "Q01_DATA_CERTIFICATION": policy.require_data_certification,
        "Q02_REPRODUCIBILITY": policy.require_reproducibility,
        "Q03_BASELINE_ACCEPTANCE": True,  # always required for institutional path
        "Q04_WALK_FORWARD": policy.require_wfa,
        "Q05_STATISTICAL_MULTIPLICITY": policy.require_statistical_multiplicity,
        "Q06_REGIME_MATRIX": policy.require_regime_matrix,
        "Q07_ADVERSARIAL_ROBUSTNESS": policy.require_robustness,
        "Q08_EXECUTION_VALIDITY": policy.require_execution_validity,
        "Q09_CAPACITY": policy.require_capacity,
        "Q10_SEALED_HOLDOUT": policy.require_sealed,
        "Q11_PORTFOLIO_COMPATIBILITY": policy.require_portfolio_compatibility,
    }
    return bool(mapping.get(gate_id, True))


def _result(
    gate_id: str,
    *,
    state: str,
    passed: bool,
    methodology: str,
    evidence: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
    warnings: list[str] | None = None,
    input_payload: Any = None,
) -> QualificationGateResult:
    evidence = dict(evidence or {})
    metrics = dict(metrics or {})
    blockers = list(blockers or [])
    warnings = list(warnings or [])
    input_hash = sha256_hex(_canonical_json(input_payload if input_payload is not None else evidence))
    output_hash = sha256_hex(
        _canonical_json(
            {
                "state": state,
                "passed": passed,
                "metrics": metrics,
                "blockers": blockers,
            }
        )
    )
    return QualificationGateResult(
        gate_id=gate_id,
        state=state,
        passed=passed,
        methodology=methodology,
        evidence=evidence,
        metrics=metrics,
        blockers=blockers,
        warnings=warnings,
        input_hash=input_hash,
        output_hash=output_hash,
    )


class QualificationAuthority:
    """Single canonical scientific qualification authority."""

    def __init__(self, plane: Any = None, store: Any = None, **_: Any) -> None:
        self.plane = plane
        self.store = store if store is not None else getattr(plane, "store", None)

    # --- persistence helpers -------------------------------------------------

    def _require_store(self) -> Any:
        if self.store is None:
            raise RuntimeError("QualificationAuthority requires a MarketSimStore")
        return self.store

    def _load_run(self, qualification_id: str) -> dict[str, Any]:
        store = self._require_store()
        row = store.get_qualification_run(qualification_id)
        if row is None:
            raise KeyError(f"QUALIFICATION_NOT_FOUND:{qualification_id}")
        return row

    def _policy_from_run(self, run: Mapping[str, Any]) -> QualificationPolicy:
        store = self._require_store()
        pol = store.get_qualification_policy(str(run["policy_id"]))
        if pol is None:
            raise KeyError(f"POLICY_NOT_FOUND:{run.get('policy_id')}")
        body = pol.get("policy_json") if isinstance(pol.get("policy_json"), dict) else pol
        # Rebuild frozen policy from persisted JSON
        fields = {f.name for f in QualificationPolicy.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {k: body[k] for k in fields if k in body}
        kwargs.setdefault("policy_id", pol.get("policy_id") or body.get("policy_id"))
        kwargs.setdefault("version", int(pol.get("version") or body.get("version") or 1))
        kwargs.setdefault("name", pol.get("name") or body.get("name") or "unnamed")
        return QualificationPolicy(**kwargs)  # type: ignore[arg-type]

    def _context_from_run(self, run: Mapping[str, Any]) -> QualificationContext:
        meta = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
        extra = dict(meta.get("extra") or {})
        # Model hashes may be supplied via create-time extra until a metadata column exists.
        return QualificationContext(
            qualification_id=str(run["qualification_id"]),
            experiment_id=run.get("experiment_id"),
            learning_run_id=run.get("learning_run_id"),
            candidate_id=run.get("candidate_id"),
            strategy_id=str(run["strategy_id"]),
            strategy_version=int(run["strategy_version"]),
            strategy_hash=str(run["strategy_hash"]),
            source_id=str(run["source_id"]),
            dataset_id=run.get("dataset_id"),
            dataset_version_id=run.get("dataset_version_id"),
            dataset_hash=str(run["dataset_hash"]),
            git_sha=str(run["git_sha"]),
            code_version=str(run["code_version"]),
            seed=int(run["seed"]),
            sealed_attempt_id=run.get("sealed_attempt_id"),
            trial_family_id=str(run["trial_family_id"]),
            feature_pipeline_hash=str(meta.get("feature_pipeline_hash") or extra.get("feature_pipeline_hash") or ""),
            execution_model_hash=str(meta.get("execution_model_hash") or extra.get("execution_model_hash") or ""),
            cost_model_hash=str(meta.get("cost_model_hash") or extra.get("cost_model_hash") or ""),
            risk_model_hash=str(meta.get("risk_model_hash") or extra.get("risk_model_hash") or ""),
            sizing_model_hash=str(meta.get("sizing_model_hash") or extra.get("sizing_model_hash") or ""),
            split_manifest_hash=str(meta.get("split_manifest_hash") or extra.get("split_manifest_hash") or ""),
            dirty=bool(meta.get("dirty") or extra.get("dirty")),
            diff_hash=str(meta.get("diff_hash") or extra.get("diff_hash") or ""),
            extra=extra,
        )

    def _decision_from_run(self, run: Mapping[str, Any]) -> QualificationDecision:
        store = self._require_store()
        gates = []
        if hasattr(store, "list_qualification_gate_results"):
            for g in store.list_qualification_gate_results(str(run["qualification_id"])):
                gates.append(
                    QualificationGateResult(
                        gate_id=str(g["gate_id"]),
                        state=str(g["state"]),
                        passed=bool(g["passed"]),
                        methodology=str(g.get("methodology") or ""),
                        evidence=dict(g.get("evidence") or {}),
                        metrics=dict(g.get("metrics") or {}),
                        blockers=list(g.get("blockers") or []),
                        warnings=list(g.get("warnings") or []),
                        input_hash=str(g.get("input_hash") or ""),
                        output_hash=str(g.get("output_hash") or ""),
                    )
                )
        policy_hash = str(run.get("policy_hash") or "")
        if not policy_hash and run.get("policy_id"):
            pol = store.get_qualification_policy(str(run["policy_id"]))
            if pol:
                policy_hash = str(pol.get("policy_hash") or "")
        return QualificationDecision(
            qualification_id=str(run["qualification_id"]),
            state=str(run.get("status") or "CREATED"),
            qualified=str(run.get("decision") or "").upper() == "QUALIFIED"
            or bool(run.get("qualified")),
            gate_results=gates,
            blockers=list(run.get("blockers") or []),
            warnings=list(run.get("warnings") or []),
            provenance_hash=str(run.get("provenance_hash") or ""),
            policy_hash=policy_hash,
            policy_id=str(run.get("policy_id") or ""),
            created_at=str(run.get("created_at") or ""),
            finished_at=run.get("finished_at"),
            current_gate=run.get("current_gate"),
        )

    # --- public API ----------------------------------------------------------

    def create_run(
        self,
        context: QualificationContext,
        policy: QualificationPolicy,
        *,
        created_by: str = "qualification_authority",
        idempotency_key: str | None = None,
    ) -> QualificationDecision:
        store = self._require_store()
        ph = hash_policy(policy)
        # Persist immutable policy snapshot
        if hasattr(store, "save_qualification_policy"):
            store.save_qualification_policy(
                {
                    "policy_id": policy.policy_id,
                    "version": policy.version,
                    "name": policy.name,
                    "policy_hash": ph,
                    "policy_json": policy.public_dict(),
                    "created_at": utc_now(),
                    "created_by": created_by,
                    "active": 1,
                }
            )
        provenance = hash_provenance(context, ph)
        qid = context.qualification_id or f"qual_{uuid.uuid4().hex[:16]}"
        idem = idempotency_key or f"qualification:{qid}"
        now = utc_now()
        run = {
            "qualification_id": qid,
            "policy_id": policy.policy_id,
            "policy_hash": ph,
            "experiment_id": context.experiment_id,
            "learning_run_id": context.learning_run_id,
            "candidate_id": context.candidate_id,
            "trial_family_id": context.trial_family_id,
            "strategy_id": context.strategy_id,
            "strategy_version": context.strategy_version,
            "strategy_hash": context.strategy_hash,
            "source_id": context.source_id,
            "dataset_id": context.dataset_id,
            "dataset_version_id": context.dataset_version_id,
            "dataset_hash": context.dataset_hash,
            "git_sha": context.git_sha,
            "code_version": context.code_version,
            "seed": context.seed,
            "status": "CREATED",
            "current_gate": None,
            "decision": None,
            "blockers": [],
            "warnings": [],
            "provenance_hash": provenance,
            "sealed_attempt_id": context.sealed_attempt_id,
            "idempotency_key": idem,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "updated_at": now,
            "metadata": {
                "feature_pipeline_hash": context.feature_pipeline_hash,
                "execution_model_hash": context.execution_model_hash,
                "cost_model_hash": context.cost_model_hash,
                "risk_model_hash": context.risk_model_hash,
                "sizing_model_hash": context.sizing_model_hash,
                "split_manifest_hash": context.split_manifest_hash,
                "dirty": context.dirty,
                "diff_hash": context.diff_hash,
                "extra": context.extra,
            },
        }
        if hasattr(store, "create_qualification_run"):
            existing = None
            if hasattr(store, "get_qualification_run_by_idempotency"):
                existing = store.get_qualification_run_by_idempotency(idem)
            if existing is None:
                store.create_qualification_run(run)
            refreshed = store.get_qualification_run(qid)
            if refreshed is not None:
                # Attach policy_hash for decision surface (not a DB column).
                refreshed = dict(refreshed)
                refreshed["policy_hash"] = ph
                return self._decision_from_run(refreshed)
            if existing is not None:
                existing = dict(existing)
                existing["policy_hash"] = ph
                return self._decision_from_run(existing)
        run["policy_hash"] = ph
        return self._decision_from_run(run)

    def get(self, qualification_id: str) -> QualificationDecision | None:
        store = self._require_store()
        if not hasattr(store, "get_qualification_run"):
            return None
        row = store.get_qualification_run(qualification_id)
        if row is None:
            return None
        return self._decision_from_run(row)

    def cancel(self, qualification_id: str) -> QualificationDecision:
        store = self._require_store()
        run = self._load_run(qualification_id)
        if str(run.get("status") or "") in {"QUALIFIED", "REJECTED", "FAILED", "CANCELLED"}:
            return self._decision_from_run(run)
        finished = utc_now()
        store.update_qualification_run(
            qualification_id,
            {
                "status": "CANCELLED",
                "decision": "CANCELLED",
                "finished_at": finished,
                "updated_at": finished,
            },
        )
        return self._decision_from_run(self._load_run(qualification_id))

    def resume(self, qualification_id: str) -> QualificationDecision:
        return self.evaluate(qualification_id)

    def evaluate_gate(self, qualification_id: str, gate_id: str) -> QualificationGateResult:
        run = self._load_run(qualification_id)
        policy = self._policy_from_run(run)
        context = self._context_from_run(run)
        gid = _normalize_gate_id(gate_id)
        result = self._eval_one_gate(gid, context=context, policy=policy, run=run)
        self._persist_gate(qualification_id, result)
        return result

    def evaluate(self, qualification_id: str) -> QualificationDecision:
        store = self._require_store()
        run = self._load_run(qualification_id)
        if str(run.get("status") or "") in {"QUALIFIED", "REJECTED", "FAILED", "CANCELLED"}:
            return self._decision_from_run(run)
        policy = self._policy_from_run(run)
        context = self._context_from_run(run)
        now = utc_now()
        store.update_qualification_run(
            qualification_id,
            {
                "status": "RUNNING",
                "started_at": run.get("started_at") or now,
                "updated_at": now,
            },
        )
        run = self._load_run(qualification_id)

        gate_results: list[QualificationGateResult] = []
        blockers: list[str] = []
        warnings: list[str] = []
        hard_failed = False

        for gid in GATE_ORDER:
            store.update_qualification_run(
                qualification_id,
                {"current_gate": gid, "updated_at": utc_now()},
            )

            if hard_failed and not policy.diagnostic_continuation:
                blocked = _result(
                    gid,
                    state=MeasurementState.BLOCKED.value,
                    passed=False,
                    methodology="blocked_by_prior_gate",
                    blockers=["PRIOR_GATE_FAILED"],
                    evidence={"skipped": True},
                )
                gate_results.append(blocked)
                self._persist_gate(qualification_id, blocked)
                continue

            result = self._eval_one_gate(gid, context=context, policy=policy, run=run)
            gate_results.append(result)
            self._persist_gate(qualification_id, result)
            warnings.extend(result.warnings)
            required = _gate_required(policy, gid)
            if required and not result.passed:
                blockers.extend(result.blockers or [f"{gid}_FAILED"])
                hard_failed = True

        qualified = (not hard_failed) and all(
            (not _gate_required(policy, g.gate_id)) or g.passed for g in gate_results
        )
        if qualified and policy.require_sealed:
            sealed = next((g for g in gate_results if g.gate_id == "Q10_SEALED_HOLDOUT"), None)
            if sealed is None or not sealed.passed:
                qualified = False
                blockers.append("SEALED_REQUIRED")

        finished = utc_now()
        store.update_qualification_run(
            qualification_id,
            {
                "status": "QUALIFIED" if qualified else ("BLOCKED" if blockers else "REJECTED"),
                "decision": "QUALIFIED" if qualified else "REJECTED",
                "blockers": blockers,
                "warnings": warnings,
                "finished_at": finished,
                "updated_at": finished,
                "current_gate": None,
            },
        )
        return self._decision_from_run(self._load_run(qualification_id))

    def _persist_gate(self, qualification_id: str, result: QualificationGateResult) -> None:
        store = self._require_store()
        if not hasattr(store, "upsert_qualification_gate_result"):
            return
        store.upsert_qualification_gate_result(
            {
                "gate_result_id": f"gr_{qualification_id}_{result.gate_id}",
                "qualification_id": qualification_id,
                "gate_id": result.gate_id,
                "state": result.state,
                "passed": int(bool(result.passed)),
                "methodology": result.methodology,
                "evidence": result.evidence,
                "metrics": result.metrics,
                "blockers": result.blockers,
                "warnings": result.warnings,
                "input_hash": result.input_hash,
                "output_hash": result.output_hash,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        )

    # --- gate evaluators (fail-closed) ---------------------------------------

    def _eval_one_gate(
        self,
        gate_id: str,
        *,
        context: QualificationContext,
        policy: QualificationPolicy,
        run: Mapping[str, Any],
    ) -> QualificationGateResult:
        required = _gate_required(policy, gate_id)
        dispatch = {
            "Q01_DATA_CERTIFICATION": self._gate_data_certification,
            "Q02_REPRODUCIBILITY": self._gate_reproducibility,
            "Q03_BASELINE_ACCEPTANCE": self._gate_baseline_acceptance,
            "Q04_WALK_FORWARD": self._gate_walk_forward,
            "Q05_STATISTICAL_MULTIPLICITY": self._gate_statistical_multiplicity,
            "Q06_REGIME_MATRIX": self._gate_regime_matrix,
            "Q07_ADVERSARIAL_ROBUSTNESS": self._gate_robustness,
            "Q08_EXECUTION_VALIDITY": self._gate_execution_validity,
            "Q09_CAPACITY": self._gate_capacity,
            "Q10_SEALED_HOLDOUT": self._gate_sealed,
            "Q11_PORTFOLIO_COMPATIBILITY": self._gate_portfolio,
        }
        fn = dispatch.get(gate_id)
        if fn is None:
            return _result(
                gate_id,
                state=MeasurementState.NOT_IMPLEMENTED.value,
                passed=False,
                methodology="unknown_gate",
                blockers=["UNKNOWN_GATE"],
            )
        result = fn(context=context, policy=policy, run=run)
        if not required and not result.passed:
            # Optional gate: keep honest non-green but do not force blocker list
            # into hard-fail unless already set; evaluate() uses _gate_required.
            pass
        # Reject any caller-injected pass boolean in extra evidence
        if context.extra.get("acceptance", {}).get("passed") is True:
            result.warnings.append("CALLER_PASSED_BOOLEAN_IGNORED")
            if result.passed and gate_id == "Q03_BASELINE_ACCEPTANCE":
                # Still allow only if real metrics path passed — never solely from caller.
                if not result.evidence.get("acceptance_from_run"):
                    result.passed = False
                    result.state = MeasurementState.FAIL.value
                    result.blockers.append("CALLER_BOOLEAN_NOT_AUTHORITY")
        return result

    def _gate_data_certification(self, *, context, policy, run) -> QualificationGateResult:
        store = self._require_store()
        cert = None
        if hasattr(store, "get_dataset_certification") and context.dataset_version_id:
            cert = store.get_dataset_certification(
                dataset_id=context.dataset_id or "",
                dataset_version_id=context.dataset_version_id,
                dataset_hash=context.dataset_hash,
            )
        if cert is None:
            state = MeasurementState.UNMEASURED.value
            passed = False
            blockers = ["DATA_PIT_NOT_CERTIFIED"] if policy.require_data_certification else []
            return _result(
                "Q01_DATA_CERTIFICATION",
                state=state,
                passed=passed and not policy.require_data_certification,
                methodology="dataset_certification_lookup",
                blockers=blockers if policy.require_data_certification else [],
                evidence={"certification": None},
                warnings=[] if policy.require_data_certification else ["CERTIFICATION_OPTIONAL_MISSING"],
            )
        cert_state = str(cert.get("certification_state") or "").upper()
        pit_state = str(cert.get("pit_state") or "").upper()
        ok = cert_state in {MeasurementState.PASS.value, MeasurementState.MEASURED.value} and pit_state in {
            MeasurementState.PASS.value,
            MeasurementState.MEASURED.value,
            MeasurementState.OBSERVED.value,
        }
        return _result(
            "Q01_DATA_CERTIFICATION",
            state=MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
            passed=ok,
            methodology="dataset_certification_lookup",
            evidence={"certification": cert},
            blockers=[] if ok else ["DATA_PIT_NOT_CERTIFIED"],
            input_payload={"dataset_hash": context.dataset_hash, "cert": cert.get("certification_hash")},
        )

    def _gate_reproducibility(self, *, context, policy, run) -> QualificationGateResult:
        required_fields = {
            "git_sha": context.git_sha,
            "code_version": context.code_version,
            "strategy_id": context.strategy_id,
            "strategy_version": str(context.strategy_version),
            "strategy_hash": context.strategy_hash,
            "dataset_hash": context.dataset_hash,
            "seed": str(context.seed),
            "trial_family_id": context.trial_family_id,
            "policy_hash": str(run.get("policy_hash") or ""),
            "provenance_hash": str(run.get("provenance_hash") or ""),
        }
        missing = [k for k, v in required_fields.items() if not str(v or "").strip()]
        # dataset_version_id required when policy asks for certification path
        if policy.require_data_certification and not context.dataset_version_id:
            missing.append("dataset_version_id")
        for label, val in (
            ("feature_pipeline_hash", context.feature_pipeline_hash),
            ("execution_model_hash", context.execution_model_hash),
            ("cost_model_hash", context.cost_model_hash),
            ("risk_model_hash", context.risk_model_hash),
            ("sizing_model_hash", context.sizing_model_hash),
            ("split_manifest_hash", context.split_manifest_hash),
        ):
            if not str(val or "").strip():
                missing.append(label)
        if context.dirty and not context.diff_hash:
            missing.append("diff_hash")
        if missing:
            return _result(
                "Q02_REPRODUCIBILITY",
                state=MeasurementState.FAIL.value,
                passed=False,
                methodology="provenance_completeness",
                blockers=["REPRODUCIBILITY_INCOMPLETE"],
                evidence={"missing": missing, "dirty": context.dirty},
                input_payload=required_fields,
            )
        return _result(
            "Q02_REPRODUCIBILITY",
            state=MeasurementState.PASS.value,
            passed=True,
            methodology="provenance_completeness",
            evidence={"fields": required_fields, "dirty": context.dirty},
            input_payload=required_fields,
        )

    def _gate_baseline_acceptance(self, *, context, policy, run) -> QualificationGateResult:
        # Diagnostic only from experiment/run metrics — never from caller boolean.
        metrics = dict((context.extra or {}).get("metrics") or {})
        criteria = dict((context.extra or {}).get("acceptance_criteria") or {})
        if not metrics:
            return _result(
                "Q03_BASELINE_ACCEPTANCE",
                state=MeasurementState.UNMEASURED.value,
                passed=False,
                methodology="evaluate_acceptance_from_run",
                blockers=["BASELINE_METRICS_MISSING"],
                evidence={"acceptance_from_run": False},
            )
        try:
            from .wfa import evaluate_acceptance_from_run

            payload = {
                "run_id": context.experiment_id or context.qualification_id,
                "metrics": metrics,
                "metadata": {},
            }
            result = evaluate_acceptance_from_run(payload, criteria=criteria or {
                "min_trades": policy.min_trades,
                "max_drawdown_pct": policy.max_drawdown_pct,
            })
            passed = bool(getattr(result, "passed", False))
            # TRAIN-only flag in extras blocks qualification-grade acceptance
            if str((context.extra or {}).get("split_role") or "").upper() == "TRAIN":
                return _result(
                    "Q03_BASELINE_ACCEPTANCE",
                    state=MeasurementState.FAIL.value,
                    passed=False,
                    methodology="evaluate_acceptance_from_run",
                    blockers=["TRAIN_ONLY_CANNOT_QUALIFY"],
                    evidence={"acceptance_from_run": True, "split_role": "TRAIN"},
                    metrics=metrics,
                )
            return _result(
                "Q03_BASELINE_ACCEPTANCE",
                state=MeasurementState.PASS.value if passed else MeasurementState.FAIL.value,
                passed=passed,
                methodology="evaluate_acceptance_from_run",
                evidence={
                    "acceptance_from_run": True,
                    "acceptance": result.public_dict() if hasattr(result, "public_dict") else dict(result),
                },
                metrics=metrics,
                blockers=[] if passed else ["BASELINE_ACCEPTANCE_FAILED"],
            )
        except Exception as exc:  # noqa: BLE001
            return _result(
                "Q03_BASELINE_ACCEPTANCE",
                state=MeasurementState.UNMEASURED.value,
                passed=False,
                methodology="evaluate_acceptance_from_run",
                blockers=["BASELINE_EVAL_ERROR"],
                evidence={"error": str(exc), "acceptance_from_run": False},
            )

    def _gate_walk_forward(self, *, context, policy, run) -> QualificationGateResult:
        store = self._require_store()
        folds: list[dict[str, Any]] = []
        if hasattr(store, "list_wfa_folds"):
            folds = list(store.list_wfa_folds(context.qualification_id))
        fold_count = len(folds)
        if fold_count < policy.min_wfa_folds:
            return _result(
                "Q04_WALK_FORWARD",
                state=MeasurementState.INSUFFICIENT_HISTORY.value,
                passed=False,
                methodology="persisted_wfa_folds",
                blockers=["WFA_INSUFFICIENT"],
                metrics={"fold_count": fold_count, "min_wfa_folds": policy.min_wfa_folds},
                evidence={"folds": folds},
            )
        passed_folds = [f for f in folds if bool(f.get("passed") or str(f.get("state") or "").upper() == "PASS")]
        # Prefer explicit passed; else state PASS/MEASURED with test_run_id present
        if not passed_folds:
            passed_folds = [
                f
                for f in folds
                if f.get("test_run_id")
                and str(f.get("state") or "").upper()
                in {MeasurementState.PASS.value, MeasurementState.MEASURED.value, "PASS"}
            ]
        ratio = (len(passed_folds) / fold_count) if fold_count else 0.0
        ok = ratio >= policy.min_wfa_pass_ratio and all(f.get("test_run_id") for f in folds)
        return _result(
            "Q04_WALK_FORWARD",
            state=MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
            passed=ok,
            methodology="persisted_wfa_folds",
            metrics={
                "fold_count": fold_count,
                "pass_count": len(passed_folds),
                "pass_ratio": ratio,
            },
            evidence={"folds": folds},
            blockers=[] if ok else ["WFA_INSUFFICIENT"],
        )

    def _gate_statistical_multiplicity(self, *, context, policy, run) -> QualificationGateResult:
        store = self._require_store()
        family_id = context.trial_family_id
        if not family_id or family_id.startswith("LEGACY"):
            return _result(
                "Q05_STATISTICAL_MULTIPLICITY",
                state=MeasurementState.UNMEASURED.value,
                passed=False,
                methodology="trial_family_cscv_pbo",
                blockers=["STATISTICAL_EVIDENCE_INSUFFICIENT", "LEGACY_EVIDENCE_INCOMPLETE"],
                evidence={"trial_family_id": family_id},
            )
        trials: list[dict[str, Any]] = []
        if hasattr(store, "list_trials_for_family"):
            trials = list(store.list_trials_for_family(family_id))
        trial_count = len(trials)
        candidate_count = (
            store.distinct_candidate_count_for_family(family_id)
            if hasattr(store, "distinct_candidate_count_for_family")
            else len({t.get("candidate_id") or t.get("strategy_id") for t in trials})
        )
        # Build performance matrix from trial metrics when available
        matrix = (context.extra or {}).get("performance_matrix")
        cscv_state = MeasurementState.UNMEASURED.value
        cscv_pbo = None
        fdr_state = MeasurementState.UNMEASURED.value
        dsr_authority = False
        blockers: list[str] = []
        metrics: dict[str, Any] = {
            "trial_count": trial_count,
            "candidate_count": candidate_count,
            "effective_sample_size": trial_count,
            "block_bootstrap_state": MeasurementState.UNMEASURED.value,
            "cscv_pbo_state": cscv_state,
            "cscv_pbo": cscv_pbo,
            "fdr_state": fdr_state,
            "fdr_q": policy.fdr_q,
            "dsr_qualification_authority": dsr_authority,
        }
        if matrix is not None:
            try:
                from .stats_inferential import probability_of_backtest_overfitting_cscv

                cscv = probability_of_backtest_overfitting_cscv(matrix)
                cscv_state = str(cscv.get("measurement") or MeasurementState.UNMEASURED.value)
                cscv_pbo = cscv.get("pbo")
                metrics["cscv_pbo_state"] = cscv_state
                metrics["cscv_pbo"] = cscv_pbo
                metrics["cscv"] = cscv
            except Exception as exc:  # noqa: BLE001
                blockers.append("CSCV_ERROR")
                metrics["cscv_error"] = str(exc)
        else:
            blockers.append("PERFORMANCE_MATRIX_MISSING")

        pvals = (context.extra or {}).get("family_p_values")
        if isinstance(pvals, list) and pvals:
            try:
                from .stats_inferential import benjamini_hochberg

                fdr = benjamini_hochberg(pvals, q=policy.fdr_q or 0.1)
                fdr_state = str(fdr.get("measurement") or MeasurementState.MEASURED.value)
                metrics["fdr_state"] = fdr_state
                metrics["fdr"] = fdr
                metrics["fdr_rejected_or_accepted"] = fdr.get("rejected")
            except Exception as exc:  # noqa: BLE001
                metrics["fdr_error"] = str(exc)
        else:
            metrics["fdr_state"] = MeasurementState.UNMEASURED.value

        # Approximate DSR must never be qualification authority
        if (context.extra or {}).get("dsr") is not None:
            metrics["dsr"] = (context.extra or {}).get("dsr")
            metrics["dsr_qualification_authority"] = False

        ok = (
            trial_count > 0
            and candidate_count > 0
            and cscv_state == MeasurementState.MEASURED.value
            and cscv_pbo is not None
            and (policy.max_pbo is None or float(cscv_pbo) <= float(policy.max_pbo))
        )
        if not ok and policy.require_statistical_multiplicity:
            if "STATISTICAL_EVIDENCE_INSUFFICIENT" not in blockers:
                blockers.append("STATISTICAL_EVIDENCE_INSUFFICIENT")
        return _result(
            "Q05_STATISTICAL_MULTIPLICITY",
            state=MeasurementState.PASS.value if ok else MeasurementState.UNMEASURED.value,
            passed=ok,
            methodology="trial_family_cscv_pbo_fdr",
            metrics=metrics,
            evidence={"trial_family_id": family_id},
            blockers=blockers if not ok else [],
        )

    def _gate_regime_matrix(self, *, context, policy, run) -> QualificationGateResult:
        regimes = (context.extra or {}).get("regime_results")
        if not regimes:
            return _result(
                "Q06_REGIME_MATRIX",
                state=MeasurementState.UNMEASURED.value,
                passed=not policy.require_regime_matrix,
                methodology="regime_matrix",
                blockers=["REGIME_MATRIX_UNMEASURED"] if policy.require_regime_matrix else [],
                warnings=[] if policy.require_regime_matrix else ["REGIME_OPTIONAL_MISSING"],
            )
        # Must be measured results, not strategy metadata claims
        if (context.extra or {}).get("applicable_regimes_declared_only"):
            return _result(
                "Q06_REGIME_MATRIX",
                state=MeasurementState.FAIL.value,
                passed=False,
                methodology="regime_matrix",
                blockers=["REGIME_DECLARED_NOT_TESTED"],
            )
        passed_n = sum(1 for r in regimes if r.get("passed"))
        total = len(regimes)
        ratio = passed_n / total if total else 0.0
        ok = total > 0 and ratio >= 0.5
        return _result(
            "Q06_REGIME_MATRIX",
            state=MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
            passed=ok,
            methodology="regime_matrix",
            metrics={"regime_count": total, "pass_count": passed_n, "pass_ratio": ratio},
            evidence={"regimes": regimes},
            blockers=[] if ok else ["REGIME_MATRIX_FAILED"],
        )

    def _gate_robustness(self, *, context, policy, run) -> QualificationGateResult:
        scenarios = (context.extra or {}).get("robustness_scenarios")
        if not scenarios:
            return _result(
                "Q07_ADVERSARIAL_ROBUSTNESS",
                state=MeasurementState.UNMEASURED.value,
                passed=not policy.require_robustness,
                methodology="adversarial_reruns",
                blockers=["ROBUSTNESS_UNMEASURED"] if policy.require_robustness else [],
            )
        # Require real rerun IDs — metric rescore alone is insufficient
        measured = [
            s
            for s in scenarios
            if s.get("perturbed_run_id") and str(s.get("state") or "").upper()
            not in {MeasurementState.NOT_IMPLEMENTED.value, MeasurementState.UNMEASURED.value}
        ]
        if not measured:
            return _result(
                "Q07_ADVERSARIAL_ROBUSTNESS",
                state=MeasurementState.UNMEASURED.value,
                passed=False,
                methodology="adversarial_reruns",
                blockers=["ROBUSTNESS_NO_RERUNS"],
                evidence={"scenarios": scenarios},
            )
        passed_n = sum(1 for s in measured if s.get("passed"))
        ratio = passed_n / len(measured)
        ok = ratio >= policy.min_robustness_pass_ratio
        return _result(
            "Q07_ADVERSARIAL_ROBUSTNESS",
            state=MeasurementState.PASS.value if ok else MeasurementState.FAIL.value,
            passed=ok,
            methodology="adversarial_reruns",
            metrics={"scenario_count": len(measured), "pass_count": passed_n, "pass_ratio": ratio},
            evidence={"scenarios": measured},
            blockers=[] if ok else ["ROBUSTNESS_FAILED"],
        )

    def _gate_execution_validity(self, *, context, policy, run) -> QualificationGateResult:
        envelope = (context.extra or {}).get("execution_envelope") or policy.operating_envelope or {}
        data_level = str(envelope.get("data_level") or "BAR").upper()
        strategy_needs = str((context.extra or {}).get("required_data_level") or "BAR").upper()
        rank = {"BAR": 1, "QUOTE": 2, "ORDERBOOK": 3}
        if rank.get(strategy_needs, 99) > rank.get(data_level, 0):
            return _result(
                "Q08_EXECUTION_VALIDITY",
                state=MeasurementState.FAIL.value,
                passed=False,
                methodology="execution_model_envelope",
                blockers=["OUT_OF_MODEL_DOMAIN"],
                evidence={"data_level": data_level, "required": strategy_needs},
            )
        if not context.execution_model_hash:
            return _result(
                "Q08_EXECUTION_VALIDITY",
                state=MeasurementState.UNMEASURED.value,
                passed=False,
                methodology="execution_model_envelope",
                blockers=["EXECUTION_MODEL_UNMEASURED"],
            )
        return _result(
            "Q08_EXECUTION_VALIDITY",
            state=MeasurementState.PASS.value,
            passed=True,
            methodology="execution_model_envelope",
            evidence={"data_level": data_level, "execution_model_hash": context.execution_model_hash},
        )

    def _gate_capacity(self, *, context, policy, run) -> QualificationGateResult:
        cap = (context.extra or {}).get("capacity")
        if not cap:
            # Optional auto-estimate when capital+adv supplied in extra
            raw = (context.extra or {}).get("capacity_inputs")
            if isinstance(raw, dict):
                try:
                    from .capacity_qualification import estimate_bar_capacity

                    ev = estimate_bar_capacity(
                        capital=float(raw.get("capital") or 0),
                        avg_daily_volume=raw.get("avg_daily_volume") or raw.get("adv"),
                        price=raw.get("price"),
                        turnover=raw.get("turnover"),
                        max_participation_pct=float(
                            raw.get("max_participation_pct")
                            or policy.config.get("max_participation_pct")
                            or 10.0
                        ),
                    )
                    cap = ev.public_dict()
                except Exception:  # noqa: BLE001
                    cap = None
        if not cap:
            return _result(
                "Q09_CAPACITY",
                state=MeasurementState.UNMEASURED.value,
                passed=not policy.require_capacity,
                methodology="capacity_liquidity",
                blockers=["CAPACITY_UNMEASURED"] if policy.require_capacity else [],
            )
        state = str(cap.get("state") or MeasurementState.UNMEASURED.value).upper()
        blockers = [str(b) for b in (cap.get("blockers") or [])]
        if cap.get("exceeded") or "CAPACITY_EXCEEDED" in blockers:
            return _result(
                "Q09_CAPACITY",
                state=MeasurementState.FAIL.value,
                passed=False,
                methodology="capacity_liquidity",
                blockers=["CAPACITY_EXCEEDED"],
                metrics=dict(cap),
            )
        if "CAPACITY_UNMEASURED" in blockers:
            return _result(
                "Q09_CAPACITY",
                state=MeasurementState.UNMEASURED.value,
                passed=not policy.require_capacity,
                methodology="capacity_liquidity",
                blockers=["CAPACITY_UNMEASURED"] if policy.require_capacity else [],
                metrics=dict(cap),
            )
        ok = state in {
            MeasurementState.PASS.value,
            MeasurementState.MEASURED.value,
            MeasurementState.ESTIMATED.value,
            MeasurementState.OBSERVED.value,
        }
        return _result(
            "Q09_CAPACITY",
            state=state if ok else MeasurementState.UNMEASURED.value,
            passed=ok if policy.require_capacity else True,
            methodology="capacity_liquidity",
            metrics=dict(cap),
            blockers=[] if ok else (["CAPACITY_UNMEASURED"] if policy.require_capacity else []),
        )

    def _gate_sealed(self, *, context, policy, run) -> QualificationGateResult:
        store = self._require_store()
        if not context.sealed_attempt_id:
            return _result(
                "Q10_SEALED_HOLDOUT",
                state=MeasurementState.UNMEASURED.value,
                passed=False,
                methodology="sealed_attempt_receipt",
                blockers=["SEALED_MISSING"],
            )
        # Caller boolean alone is never enough
        if (context.extra or {}).get("sealed_pass") is True and not context.sealed_attempt_id:
            return _result(
                "Q10_SEALED_HOLDOUT",
                state=MeasurementState.FAIL.value,
                passed=False,
                methodology="sealed_attempt_receipt",
                blockers=["SEALED_CALLER_BOOLEAN_REJECTED"],
            )
        attempt = None
        if hasattr(store, "get_sealed_attempt"):
            attempt = store.get_sealed_attempt(context.sealed_attempt_id)
        elif hasattr(store, "get_sealed_attempts"):
            attempt = store.get_sealed_attempts(context.sealed_attempt_id)
        if attempt is None:
            return _result(
                "Q10_SEALED_HOLDOUT",
                state=MeasurementState.UNMEASURED.value,
                passed=False,
                methodology="sealed_attempt_receipt",
                blockers=["SEALED_RECEIPT_NOT_FOUND"],
            )
        status = str(attempt.get("status") or attempt.get("state") or "").upper()
        consumed = bool(attempt.get("consumed") or status == "COMPLETED")
        if status == "COMPLETED" and consumed:
            # Bind lineage
            ok_lineage = True
            blockers = []
            if attempt.get("strategy_id") and attempt["strategy_id"] != context.strategy_id:
                ok_lineage = False
                blockers.append("SEALED_STRATEGY_MISMATCH")
            return _result(
                "Q10_SEALED_HOLDOUT",
                state=MeasurementState.PASS.value if ok_lineage else MeasurementState.FAIL.value,
                passed=ok_lineage,
                methodology="sealed_attempt_receipt",
                evidence={"sealed_attempt": attempt},
                blockers=blockers,
            )
        if status in {"CONSUMED", "COMPLETED"}:
            return _result(
                "Q10_SEALED_HOLDOUT",
                state=MeasurementState.FAIL.value,
                passed=False,
                methodology="sealed_attempt_receipt",
                blockers=["SEALED_ALREADY_CONSUMED"],
                evidence={"sealed_attempt": attempt},
            )
        return _result(
            "Q10_SEALED_HOLDOUT",
            state=MeasurementState.UNMEASURED.value,
            passed=False,
            methodology="sealed_attempt_receipt",
            blockers=["SEALED_NOT_COMPLETED"],
            evidence={"sealed_attempt": attempt},
        )

    def _gate_portfolio(self, *, context, policy, run) -> QualificationGateResult:
        compat = (context.extra or {}).get("portfolio_compatibility")
        if not compat:
            return _result(
                "Q11_PORTFOLIO_COMPATIBILITY",
                state=MeasurementState.UNMEASURED.value,
                passed=not policy.require_portfolio_compatibility,
                methodology="portfolio_risk_compatibility",
                blockers=["COVARIANCE_UNMEASURED"] if policy.require_portfolio_compatibility else [],
            )
        reason = str(compat.get("blocker") or "")
        if reason in {
            "PORTFOLIO_REDUNDANT",
            "CORRELATION_LIMIT",
            "RISK_CONTRIBUTION_LIMIT",
            "CAPACITY_CONFLICT",
        }:
            return _result(
                "Q11_PORTFOLIO_COMPATIBILITY",
                state=MeasurementState.FAIL.value,
                passed=False,
                methodology="portfolio_risk_compatibility",
                blockers=[reason],
                evidence=dict(compat),
            )
        ok = bool(compat.get("compatible", False))
        return _result(
            "Q11_PORTFOLIO_COMPATIBILITY",
            state=MeasurementState.PASS.value if ok else MeasurementState.UNMEASURED.value,
            passed=ok,
            methodology="portfolio_risk_compatibility",
            evidence=dict(compat),
            blockers=[] if ok else ["PORTFOLIO_COMPATIBILITY_UNMEASURED"],
        )
