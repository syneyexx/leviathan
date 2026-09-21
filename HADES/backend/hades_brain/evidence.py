"""Shared evidence/verification concepts. Domain engines remain proof."""

from __future__ import annotations

from typing import Any

from capability_intel.orchestration import verification_result

from .contracts import Claim, Evidence, VerificationOutcome


DOMAIN_PROOF: dict[str, str] = {
    "coding": "tests/build/static_analysis",
    "trading": "deterministic_statistics/evaluation",
    "media": "artifact/render/platform_checks",
    "research": "source/citation_evidence",
    "chat": "retrieval_or_tool_observation",
    "work": "completion_gate",
}


def record_claim(claim_id: str, text: str, *, domain: str = "generic") -> Claim:
    return Claim(claim_id=claim_id, text=text, domain=domain, confidence="unverified")


def record_evidence(
    evidence_id: str,
    *,
    kind: str,
    provenance: str,
    ref: str = "",
    summary: str = "",
    status: str = "recorded",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        provenance=provenance,
        status=status,
        ref=ref,
        summary=summary[:400],
    )


def evaluate_verification(
    *,
    domain: str,
    execution_success: bool,
    evidence: dict[str, Any] | None = None,
    agent_claims: list[str] | None = None,
    risk_requires_critic: bool = False,
) -> VerificationOutcome:
    raw = verification_result(execution_success=execution_success, evidence=evidence, agent_claims=agent_claims)
    deterministic = bool(raw.get("deterministic_evidence"))
    verifier = bool(raw.get("verifier_model_called"))
    if deterministic and not risk_requires_critic:
        verifier = False
        raw["verifier_model_called"] = False
        raw["early_stop"] = True
        raw["reason"] = "deterministic_proof_sufficient"
    status = "verified" if raw.get("verified_task_success") else ("failed" if not execution_success else "incomplete")
    return VerificationOutcome(
        status=status,
        proof_kind=DOMAIN_PROOF.get(domain, "shared"),
        deterministic=deterministic,
        verifier_model_called=verifier,
        claims=list(agent_claims or []),
        evidence_refs=list((evidence or {}).get("refs") or []),
        reasons=[raw.get("reason") or ("deterministic" if deterministic else "insufficient_deterministic_proof")],
    )


def should_stop_reasoning(outcome: VerificationOutcome) -> bool:
    return bool(outcome.deterministic and outcome.status == "verified" and not outcome.verifier_model_called)
