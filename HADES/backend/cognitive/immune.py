"""Pillar 5 — Cognitive Immune System.

Trust/evidence classification + quarantine for cognitive artifacts.
Repeated retrieval does not increase truth. Reuses secret redaction and
Neural eligibility gates; does not grant permissions.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .contracts import AdaptiveDecision, TRUST_CATEGORIES
from .modes import CognitiveMode


_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)sk-[a-z0-9]{20,}"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
)

_INJECTION_PATTERNS = (
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions"),
    re.compile(r"(?i)system\s*:\s*you\s+are"),
    re.compile(r"(?i)exfiltrate|send\s+secrets|disable\s+safety"),
    re.compile(r"(?i)<\|?(system|assistant)\|?>"),
)


def content_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def classify_trust(
    *,
    source: str = "",
    verified: bool = False,
    model_generated: bool = False,
    tool_generated: bool = False,
    user_provided: bool = False,
    external: bool = False,
    provenance: dict[str, Any] | None = None,
) -> str:
    """Assign a trust category. Categories are hints — provenance is authoritative."""
    provenance = provenance or {}
    if provenance.get("quarantined") or source == "quarantined":
        return "quarantined"
    if verified and not external:
        return "verified_local"
    if verified and external:
        return "verified_external"
    if user_provided:
        return "user_provided"
    if model_generated:
        return "model_generated"
    if tool_generated:
        return "tool_generated"
    if provenance.get("trusted"):
        return "trusted_source"
    if external or source in {"web", "mcp", "untrusted", "plugin"}:
        return "untrusted_source"
    if provenance.get("derived"):
        return "derived_inference"
    return "untrusted_source"


def scan_artifact(
    *,
    text: str,
    artifact_kind: str = "memory",
    trust_category: str = "untrusted_source",
    provenance: dict[str, Any] | None = None,
    allow_training: bool = False,
    allow_memory: bool = False,
    allow_neural_slow: bool = False,
    allow_skill_promotion: bool = False,
) -> dict[str, Any]:
    """Inspect incoming cognitive material. Fail closed on poison/secrets/injection."""
    provenance = dict(provenance or {})
    reasons: list[str] = []
    category = trust_category if trust_category in TRUST_CATEGORIES else "untrusted_source"

    # False provenance: claimed verified without evidence refs
    if provenance.get("claimed_verified") and not provenance.get("evidence_refs"):
        reasons.append("false_provenance")
        category = "quarantined"

    # Secret material
    for pat in _SECRET_PATTERNS:
        if pat.search(text or ""):
            reasons.append("secret_material")
            category = "quarantined"
            break

    # Prompt injection in retrieved/untrusted text
    if category in {"untrusted_source", "tool_generated", "model_generated", "quarantined"} or artifact_kind in {
        "retrieval",
        "web",
        "tool_output",
        "memory",
    }:
        for pat in _INJECTION_PATTERNS:
            if pat.search(text or ""):
                reasons.append("prompt_injection")
                category = "quarantined"
                break

    # Unverified model claims cannot become durable trusted intelligence
    if category == "model_generated" and not provenance.get("verified"):
        reasons.append("unverified_model_claim")
        allow_memory = False
        allow_training = False
        allow_neural_slow = False
        allow_skill_promotion = False

    # Corrupt checkpoint marker
    if artifact_kind == "neural_checkpoint":
        if provenance.get("corrupt") or provenance.get("compatible") is False:
            reasons.append("corrupt_checkpoint")
            category = "quarantined"

    # Malicious skill candidate
    if artifact_kind == "skill_candidate":
        if provenance.get("malicious") or provenance.get("permission_escalation"):
            reasons.append("malicious_skill")
            category = "quarantined"

    quarantined = category == "quarantined" or bool(reasons)
    if quarantined:
        category = "quarantined"
        allow_memory = False
        allow_training = False
        allow_neural_slow = False
        allow_skill_promotion = False

    # Critical rule: retrieval frequency must not inflate trust
    retrieval_count = int(provenance.get("retrieval_count") or 0)
    if retrieval_count > 1 and not provenance.get("verified"):
        # Explicitly preserve untrusted status
        if category != "quarantined":
            category = category if category != "verified_local" else "untrusted_source"
        reasons.append("retrieval_count_ignored_for_truth")

    decision = AdaptiveDecision(
        controller="cognitive.immune",
        decision="quarantine" if quarantined else "admit_bounded",
        reason_code=reasons[0].upper() if reasons else "TRUST_ADMIT",
        mode=CognitiveMode.ACTIVE.value,
        input_refs=[str(provenance.get("source_ref") or artifact_kind)],
        verification_result="rejected" if quarantined else "admitted_bounded",
    )

    return {
        "trust_category": category,
        "quarantined": quarantined,
        "reasons": reasons,
        "content_hash": content_hash(text),
        "provenance": provenance,
        "permissions": {
            "affect_action": not quarantined,  # still subject to tool policy
            "become_memory": bool(allow_memory) and not quarantined and category in {
                "verified_local",
                "verified_external",
                "user_provided",
                "trusted_source",
            },
            "become_training": bool(allow_training) and not quarantined and category in {
                "verified_local",
                "verified_external",
            },
            "become_neural_slow": bool(allow_neural_slow) and not quarantined and category in {
                "verified_local",
                "verified_external",
            },
            "become_promoted_skill": bool(allow_skill_promotion) and not quarantined and category in {
                "verified_local",
            },
        },
        "decision": decision.to_dict(),
        # Authority reminder: immune system never grants tool/MCP/filesystem authority
        "authority": "recommend_only_policy_remains_deterministic",
    }


def admit_or_quarantine(
    store: Any,
    *,
    text: str,
    artifact_kind: str = "memory",
    trust_category: str = "untrusted_source",
    provenance: dict[str, Any] | None = None,
    allow_training: bool = False,
    allow_memory: bool = False,
    allow_neural_slow: bool = False,
    allow_skill_promotion: bool = False,
) -> dict[str, Any]:
    result = scan_artifact(
        text=text,
        artifact_kind=artifact_kind,
        trust_category=trust_category,
        provenance=provenance,
        allow_training=allow_training,
        allow_memory=allow_memory,
        allow_neural_slow=allow_neural_slow,
        allow_skill_promotion=allow_skill_promotion,
    )
    if result["quarantined"] and store is not None:
        q = store.quarantine(
            artifact_kind=artifact_kind,
            trust_category="quarantined",
            reason_code=(result["reasons"][0] if result["reasons"] else "quarantined"),
            content_hash=result["content_hash"],
            provenance=result["provenance"],
            payload={"text_preview": str(text)[:240], "reasons": result["reasons"]},
        )
        result["quarantine_record"] = q
    return result
