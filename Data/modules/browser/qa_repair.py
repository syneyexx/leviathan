"""GI11 — optional operator-triggered crawler → coding repair bridge.

Finding → CodingCognitiveStrategy → patch proposal → tests → journey replay.
Never marks an issue fixed without replay/test evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from Data.modules.coding.cognition import CodingCognitiveStrategy


@dataclass
class RepairProposal:
    proposal_id: str
    finding: dict[str, Any]
    coding_plan: dict[str, Any]
    acceptance: list[str]
    status: str = "PROPOSED"  # PROPOSED | APPLIED_UNVERIFIED | VERIFIED | FAILED
    evidence: dict[str, Any] = field(default_factory=dict)
    truth: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "finding": dict(self.finding),
            "coding_plan": dict(self.coding_plan),
            "acceptance": list(self.acceptance),
            "status": self.status,
            "evidence": dict(self.evidence),
            "truth": {
                "operator_triggered_only": True,
                "no_fake_fixed_state": True,
                "requires_replay_or_tests": True,
                "write_approval_still_applies": True,
                **self.truth,
            },
        }


class QaRepairBridge:
    """Bridge crawler findings into CodingCognitiveStrategy without auto-write."""

    def __init__(
        self,
        *,
        crawler: Any | None = None,
        strategy: CodingCognitiveStrategy | None = None,
    ) -> None:
        self.crawler = crawler
        self.strategy = strategy or CodingCognitiveStrategy()
        self._proposals: dict[str, RepairProposal] = {}

    def propose_from_finding(self, finding: dict[str, Any] | Any) -> RepairProposal:
        raw = finding.public_dict() if hasattr(finding, "public_dict") else dict(finding or {})
        kind = str(raw.get("kind") or "unknown")
        message = str(raw.get("message") or "")
        url = str(raw.get("url") or "")
        goal = (
            f"Fix QA crawler finding [{kind}] at {url or 'unknown-url'}: {message}. "
            "Reproduce via crawler journey, apply minimal patch, run targeted tests, "
            "then replay the exact journey. Do not claim fixed without evidence."
        )
        understood = self.strategy.understand(text=goal)
        plan = None
        try:
            plan = self.strategy.plan(None, understood)
        except Exception:  # noqa: BLE001
            plan = None
        plan_dict: dict[str, Any]
        if plan is None:
            plan_dict = {
                "goal": goal,
                "task_type": getattr(understood, "task_type", "FIX"),
                "steps": list(getattr(understood, "acceptance_criteria", []) or []),
            }
        elif hasattr(plan, "public_dict"):
            plan_dict = plan.public_dict()
        else:
            plan_dict = {
                "goal": goal,
                "task_type": getattr(plan, "task_type", None)
                or getattr(understood, "task_type", "FIX"),
                "planned_changes": list(getattr(plan, "planned_changes", []) or []),
                "steps": list(getattr(plan, "steps", []) or []),
            }
        acceptance = list(getattr(understood, "acceptance_criteria", []) or [])
        if not acceptance:
            acceptance = [
                "failure understood or reproduction attempted",
                "minimal patch applied when fixing",
                "targeted verification executed when tooling available",
                "crawler journey replay passes without the original finding",
            ]
        proposal = RepairProposal(
            proposal_id=f"repair_{uuid.uuid4().hex[:10]}",
            finding=raw,
            coding_plan=plan_dict,
            acceptance=acceptance,
            status="PROPOSED",
            truth={"from_crawler_finding": True},
        )
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def mark_applied_unverified(
        self, proposal_id: str, *, evidence: dict[str, Any] | None = None
    ) -> RepairProposal:
        proposal = self._proposals[proposal_id]
        proposal.status = "APPLIED_UNVERIFIED"
        if evidence:
            proposal.evidence.update(evidence)
        return proposal

    def verify_with_replay(
        self,
        proposal_id: str,
        *,
        start_url: str | None = None,
        seed: int = 42,
        original_kind: str | None = None,
    ) -> RepairProposal:
        """Replay journey; VERIFIED only if original finding kind is absent."""
        proposal = self._proposals[proposal_id]
        if self.crawler is None:
            proposal.status = "FAILED"
            proposal.evidence["error"] = "No crawler bound for replay verification"
            return proposal
        url = start_url or str(proposal.finding.get("url") or "")
        if not url:
            proposal.status = "FAILED"
            proposal.evidence["error"] = "No start_url for replay"
            return proposal
        report = self.crawler.run(start_url=url, seed=seed)
        payload = report.public_dict() if hasattr(report, "public_dict") else dict(report)
        kind = original_kind or str(proposal.finding.get("kind") or "")
        remaining = [
            i
            for i in (payload.get("issues") or [])
            if str((i if isinstance(i, dict) else {}).get("kind") or "") == kind
        ]
        proposal.evidence["replay"] = {
            "status": payload.get("status"),
            "issues": len(payload.get("issues") or []),
            "matching_kind_remaining": len(remaining),
            "run_id": payload.get("run_id"),
        }
        if remaining:
            proposal.status = "FAILED"
            proposal.evidence["reason"] = "original finding kind still present after replay"
        else:
            proposal.status = "VERIFIED"
        return proposal

    def get(self, proposal_id: str) -> RepairProposal | None:
        return self._proposals.get(proposal_id)
