from __future__ import annotations

import re
import uuid
from typing import Any, Sequence

from Data.modules.reasoning import ReasoningPlan

from .cortex import CortexEngagement, CortexPlanner
from .critic import ProcessCritic
from .memory_tiers import NeuroMemoryBundle, NeuroMemoryFacade
from .residual import (
    ResidualForwardRequest,
    ResidualStreamPort,
    UnsupportedResidualRuntime,
)
from .types import NeuroAssessment, NeuroSignal


class NeuroAdvisor:
    """Heuristic + contract-backed advisory signals. Feature-flagged; never gates execution."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        associative_memory: bool = False,
        process_critic: bool = False,
        residual_injection: bool = False,
        cortex_enabled: bool = False,
        memory_tiers_enabled: bool = False,
        residual_port: ResidualStreamPort | None = None,
        memory_facade: NeuroMemoryFacade | None = None,
        cortex_planner: CortexPlanner | None = None,
        critic: ProcessCritic | None = None,
        token_budget: int = 6000,
        observability: Any | None = None,
    ) -> None:
        self.enabled = enabled
        self.associative_memory = associative_memory
        self.process_critic = process_critic
        self.residual_injection = residual_injection
        self.cortex_enabled = cortex_enabled
        self.memory_tiers_enabled = memory_tiers_enabled
        self.residual_orchestrator_enabled = False
        self.cortex_blocks_enabled = False
        self.residual_port = residual_port or UnsupportedResidualRuntime()
        self.memory_facade = memory_facade
        self.cortex_planner = cortex_planner or CortexPlanner(enabled=cortex_enabled)
        self.critic = critic or ProcessCritic(enabled=process_critic)
        self.token_budget = token_budget
        self.observability = observability

    def _emit(self, name: str, payload: dict[str, Any], *, level: str = "info") -> None:
        if self.observability is None:
            return
        try:
            self.observability.emit("neuro", name, payload=payload, level=level)
        except Exception:  # noqa: BLE001
            return

    def assess(
        self,
        text: str,
        *,
        plan: ReasoningPlan | None = None,
        knowledge_ids: Sequence[str] | None = None,
        evidence_ids: Sequence[str] | None = None,
        token_budget: int | None = None,
    ) -> NeuroAssessment:
        if not self.enabled:
            return NeuroAssessment(
                enabled=False,
                signals=(),
                notes=("Neuro feature flag OFF — no signals emitted",),
            )
        signals: list[NeuroSignal] = []
        notes: list[str] = [
            "Signals are advisory and must not authorize capabilities, approvals, or completion",
        ]
        lowered = text.lower()
        words = re.findall(r"[a-z0-9]{3,}", lowered)
        uniqueness = len(set(words)) / max(len(words), 1)
        budget = token_budget if token_budget is not None else self.token_budget

        # Probe memory early so cortex can use coverage / working-memory load.
        memory_bundle: NeuroMemoryBundle | None = None
        memory_coverage = 0.0
        memory_hit_quality = 0.0
        working_load = 0.0
        if self.memory_tiers_enabled and self.memory_facade is not None:
            working_load = float(self.memory_facade.working.load)
            # Lean pre-retrieve for planner inputs (Tier0 only to keep cost low).
            pre = self.memory_facade.retrieve(text, tiers=(0,), limit_per_tier=3, token_budget=min(256, budget))
            memory_coverage = pre.coverage
            memory_hit_quality = (
                sum(h.score for h in pre.hits) / max(len(pre.hits), 1) if pre.hits else 0.0
            )

        engagement: CortexEngagement | None = None
        if self.cortex_enabled and plan is not None:
            engagement = self.cortex_planner.plan(
                plan,
                residual_available=self.residual_port.supports_residuals(),
                memory_tiers_enabled=self.memory_tiers_enabled,
                process_critic_enabled=self.process_critic,
                token_budget=budget,
                memory_hit_quality=memory_hit_quality,
                memory_coverage=memory_coverage,
                working_memory_load=working_load,
            )
            signals.append(
                NeuroSignal(
                    signal_id=str(uuid.uuid4()),
                    kind="cortex_engagement",
                    strength=1.0 if engagement.engage else 0.0,
                    summary=engagement.reason,
                    provenance=engagement.public_dict(),
                )
            )
            self._emit(
                "cortex_engagement",
                {
                    "depth": engagement.depth,
                    "path": engagement.path,
                    "engage": engagement.engage,
                    "critic_rounds": engagement.critic_rounds,
                },
            )

        if self.memory_tiers_enabled and self.memory_facade is not None:
            tiers = engagement.use_memory_tiers if engagement is not None else (0, 1, 2)
            mem_budget = max(64, budget // 8)
            memory_bundle = self.memory_facade.retrieve(
                text,
                tiers=tiers or (0, 1, 2),
                token_budget=mem_budget,
            )
            signals.append(
                NeuroSignal(
                    signal_id=str(uuid.uuid4()),
                    kind="memory_tiers",
                    strength=min(1.0, 0.2 * len(memory_bundle.hits)),
                    summary=f"Memory tiers retrieved {len(memory_bundle.hits)} hits",
                    provenance=memory_bundle.public_dict(),
                )
            )
            self._emit(
                "memory_retrieve",
                {
                    "tiers": list(memory_bundle.tiers_queried),
                    "hits": len(memory_bundle.hits),
                    "coverage": memory_bundle.coverage,
                },
            )
        elif self.associative_memory:
            signals.append(
                NeuroSignal(
                    signal_id=str(uuid.uuid4()),
                    kind="associative_memory",
                    strength=round(min(1.0, uniqueness), 3),
                    summary="Lexical uniqueness heuristic (not embedding recall)",
                    provenance={"method": "token_uniqueness", "unmeasured_embeddings": True},
                )
            )

        if self.process_critic:
            score = self.critic.score(
                text,
                plan_steps=list(plan.steps) if plan is not None else None,
                knowledge_ids=knowledge_ids,
                evidence_ids=evidence_ids,
            )
            signals.append(self.critic.as_signal(score))
            self._emit("critic_score", score.public_dict())

        if self.residual_injection:
            implemented = self.residual_port.supports_residuals()
            inject_req = None
            if implemented and memory_bundle is not None and self.memory_facade is not None:
                inject_req = self.memory_facade.project_for_residual(memory_bundle)
            if inject_req is not None:
                receipt = self.residual_port.inject(inject_req)
                provenance: dict[str, Any] = receipt.public_dict()
                self._emit("residual_inject", provenance)
            else:
                forward = self.residual_port.run_forward(
                    ResidualForwardRequest(
                        messages=[{"role": "user", "content": text}],
                        engage_cortex=bool(engagement and engagement.engage),
                        critic_rounds=int(engagement.critic_rounds) if engagement else 0,
                    )
                )
                provenance = {
                    "implemented": implemented,
                    "applied": False,
                    "degraded_to_chat_completions": forward.degraded_to_chat_completions,
                    "reason": forward.reason or forward.detail,
                    "honest": True,
                    "forward": forward.public_dict(),
                }
                self._emit("residual_forward", provenance)
            signals.append(
                NeuroSignal(
                    signal_id=str(uuid.uuid4()),
                    kind="residual_injection",
                    strength=1.0 if implemented else 0.0,
                    summary=(
                        "Residual port active"
                        if implemented
                        else "Residual injection interface reserved; no residual-capable runtime wired"
                    ),
                    provenance=provenance,
                )
            )

        # Explicit depth metadata signal for complex assessments.
        if engagement is not None:
            signals.append(
                NeuroSignal(
                    signal_id=str(uuid.uuid4()),
                    kind="depth_metadata",
                    strength=min(1.0, engagement.depth / max(self.cortex_planner.max_depth, 1)),
                    summary=f"path={engagement.path} depth={engagement.depth}",
                    provenance={
                        "path": engagement.path,
                        "depth": engagement.depth,
                        "advisory_only": True,
                        "does_not_claim_thought_harder_as_authority": True,
                    },
                )
            )

        if not signals:
            signals.append(
                NeuroSignal(
                    signal_id=str(uuid.uuid4()),
                    kind="presence",
                    strength=0.1,
                    summary="Neuro enabled without child features — idle advisory",
                    provenance={"child_features": False},
                )
            )
        assessment = NeuroAssessment(
            enabled=True,
            signals=tuple(signals),
            notes=tuple(notes),
        )
        self._emit(
            "assess",
            {
                "signal_counts": len(signals),
                "kinds": [s.kind for s in signals],
            },
        )
        return assessment
