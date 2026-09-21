from __future__ import annotations

import re
import uuid

from .types import NeuroAssessment, NeuroSignal


class NeuroAdvisor:
    """Heuristic advisory signals. Feature-flagged; never gates execution."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        associative_memory: bool = False,
        process_critic: bool = False,
        residual_injection: bool = False,
    ) -> None:
        self.enabled = enabled
        self.associative_memory = associative_memory
        self.process_critic = process_critic
        self.residual_injection = residual_injection

    def assess(self, text: str) -> NeuroAssessment:
        if not self.enabled:
            return NeuroAssessment(
                enabled=False,
                signals=(),
                notes=("Neuro feature flag OFF — no signals emitted",),
            )
        signals: list[NeuroSignal] = []
        lowered = text.lower()
        words = re.findall(r"[a-z0-9]{3,}", lowered)
        uniqueness = len(set(words)) / max(len(words), 1)

        if self.associative_memory:
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
            risk = 0.2
            if any(token in lowered for token in ("delete", "rm -rf", "overwrite", "force")):
                risk = 0.8
            signals.append(
                NeuroSignal(
                    signal_id=str(uuid.uuid4()),
                    kind="process_critic",
                    strength=risk,
                    summary="Heuristic process-risk hint only — not a policy decision",
                    provenance={"method": "keyword_risk"},
                )
            )
        if self.residual_injection:
            signals.append(
                NeuroSignal(
                    signal_id=str(uuid.uuid4()),
                    kind="residual_injection",
                    strength=0.0,
                    summary="Residual injection interface reserved; no model stream wired",
                    provenance={"implemented": False, "honest": True},
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
        return NeuroAssessment(
            enabled=True,
            signals=tuple(signals),
            notes=(
                "Signals are advisory and must not authorize capabilities, approvals, or completion",
            ),
        )
