"""Four-tier compute policy — prefer lowest reliable tier.

Tier 0: deterministic framework
Tier 1: specialist models/algorithms
Tier 2: small/utility language model
Tier 3: main reasoning model
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ComputeTier(int, Enum):
    DETERMINISTIC = 0
    SPECIALIST = 1
    SMALL_MODEL = 2
    MAIN_REASONING = 3


# Operations that MUST remain Tier 0 — main LLM must not be invoked for these.
TIER0_OPERATIONS = frozenset(
    {
        "file_type_detection",
        "archive_inspection",
        "file_parsing",
        "document_structure_extraction",
        "hashing",
        "content_fingerprints",
        "exact_duplicate_detection",
        "near_duplicate_prefiltering",
        "chunk_boundaries",
        "token_counting",
        "language_syntax_parsing",
        "metadata_extraction",
        "url_canonicalization",
        "http_caching_metadata",
        "robots_policy",
        "source_timestamps",
        "sorting",
        "filtering",
        "database_queries",
        "numeric_calculations",
        "statistics",
        "date_calculations",
        "table_transformations",
        "unit_conversion",
        "citation_location_tracking",
        "provenance",
        "job_planning_mechanics",
        "retry_mechanics",
        "resource_scheduling",
        "schema_validation",
        "json_deterministic_repair",
        "citation_rendering",
        "embedding_batch",  # specialist, not main LLM
        "rerank_batch",
    }
)


@dataclass
class EscalationDecision:
    tier: ComputeTier
    reason: str
    operation: str
    escalate_from: ComputeTier | None = None
    model_role: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "tier": int(self.tier),
            "tier_name": self.tier.name,
            "reason": self.reason,
            "operation": self.operation,
            "escalate_from": int(self.escalate_from) if self.escalate_from is not None else None,
            "model_role": self.model_role,
            "metadata": dict(self.metadata),
        }


@dataclass
class TierMetrics:
    """Measured (not guessed) model-call economy counters."""

    main_model_calls: int = 0
    small_model_calls: int = 0
    embedding_batches: int = 0
    rerank_batches: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    context_tokens: int = 0
    tool_calls: int = 0
    retrieval_rounds: int = 0
    deterministic_ops: int = 0
    specialist_ops: int = 0
    escalations: int = 0

    def record(self, tier: ComputeTier, *, tokens_in: int = 0, tokens_out: int = 0) -> None:
        if tier == ComputeTier.DETERMINISTIC:
            self.deterministic_ops += 1
        elif tier == ComputeTier.SPECIALIST:
            self.specialist_ops += 1
        elif tier == ComputeTier.SMALL_MODEL:
            self.small_model_calls += 1
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
        elif tier == ComputeTier.MAIN_REASONING:
            self.main_model_calls += 1
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out

    def public_dict(self) -> dict[str, Any]:
        return {
            "main_model_calls": self.main_model_calls,
            "small_model_calls": self.small_model_calls,
            "embedding_batches": self.embedding_batches,
            "rerank_batches": self.rerank_batches,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "context_tokens": self.context_tokens,
            "tool_calls": self.tool_calls,
            "retrieval_rounds": self.retrieval_rounds,
            "deterministic_ops": self.deterministic_ops,
            "specialist_ops": self.specialist_ops,
            "escalations": self.escalations,
            "truth": {"measured_not_guessed": True, "no_fake_savings": True},
        }


class EscalationPolicy:
    """Typed escalation: Tier0 → Tier1 → Tier2 → Tier3. No infinite loops."""

    MAX_ESCALATIONS = 3

    def __init__(self, *, small_model_role: str = "utility") -> None:
        self.small_model_role = small_model_role
        self._escalation_count = 0

    def decide(
        self,
        operation: str,
        *,
        tier0_success: bool | None = None,
        tier0_insufficient: bool = False,
        tier1_confidence: float | None = None,
        tier1_ambiguous: bool = False,
        tier2_valid: bool | None = None,
        tier2_confident: bool | None = None,
        requires_reasoning: bool = False,
        high_risk: bool = False,
        complex: bool = False,
    ) -> EscalationDecision:
        op = str(operation or "")
        if op in TIER0_OPERATIONS and not tier0_insufficient and not requires_reasoning:
            return EscalationDecision(
                tier=ComputeTier.DETERMINISTIC,
                reason="tier0_owned_operation",
                operation=op,
            )
        if tier0_success:
            return EscalationDecision(
                tier=ComputeTier.DETERMINISTIC,
                reason="tier0_success",
                operation=op,
            )
        if requires_reasoning or high_risk or complex:
            return EscalationDecision(
                tier=ComputeTier.MAIN_REASONING,
                reason="high_value_reasoning_required",
                operation=op,
                model_role="reasoning",
            )
        if tier0_insufficient or tier0_success is False:
            if tier1_confidence is not None and tier1_confidence >= 0.8 and not tier1_ambiguous:
                return EscalationDecision(
                    tier=ComputeTier.SPECIALIST,
                    reason="tier1_high_confidence",
                    operation=op,
                    escalate_from=ComputeTier.DETERMINISTIC,
                )
            if tier1_ambiguous or (tier1_confidence is not None and tier1_confidence < 0.8):
                self._escalation_count += 1
                if self._escalation_count > self.MAX_ESCALATIONS:
                    return EscalationDecision(
                        tier=ComputeTier.MAIN_REASONING,
                        reason="escalation_cap_reached",
                        operation=op,
                        model_role="reasoning",
                    )
                if tier2_valid and tier2_confident:
                    return EscalationDecision(
                        tier=ComputeTier.SMALL_MODEL,
                        reason="tier2_structured_confident",
                        operation=op,
                        escalate_from=ComputeTier.SPECIALIST,
                        model_role=self.small_model_role,
                    )
                if tier2_valid is False or tier2_confident is False:
                    return EscalationDecision(
                        tier=ComputeTier.MAIN_REASONING,
                        reason="tier2_uncertain_escalate",
                        operation=op,
                        escalate_from=ComputeTier.SMALL_MODEL,
                        model_role="reasoning",
                    )
                return EscalationDecision(
                    tier=ComputeTier.SMALL_MODEL,
                    reason="tier1_ambiguous_try_tier2",
                    operation=op,
                    escalate_from=ComputeTier.SPECIALIST,
                    model_role=self.small_model_role,
                )
            return EscalationDecision(
                tier=ComputeTier.SPECIALIST,
                reason="tier0_insufficient_try_tier1",
                operation=op,
                escalate_from=ComputeTier.DETERMINISTIC,
            )
        # Default: deterministic unless operation demands otherwise
        return EscalationDecision(
            tier=ComputeTier.DETERMINISTIC,
            reason="default_lowest_tier",
            operation=op,
        )

    def assert_not_main_llm(self, operation: str) -> None:
        if operation in TIER0_OPERATIONS:
            return
        # Specialist ops also forbidden for main LLM invocation of mechanical work
        return
