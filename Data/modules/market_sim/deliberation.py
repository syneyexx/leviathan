"""Multi-agent deliberation protocol for market simulation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .brain_hooks import BrainFacade, BrainRetrieval
from .causality import SimulationClock
from .strategy_eval import StrategySignal, evaluate_strategy
from .types import AgentRole, DeliberationMessage, OrderSide


@dataclass
class AgentProposal:
    agent_id: str
    role: str
    signal: StrategySignal
    brain: BrainRetrieval
    veto: bool = False
    veto_reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "signal": self.signal.public_dict(),
            "brain": self.brain.public_dict(),
            "veto": self.veto,
            "veto_reason": self.veto_reason,
        }


@dataclass
class DeliberationResult:
    final_side: str
    final_qty: float | None
    rationale: str
    proposals: list[AgentProposal] = field(default_factory=list)
    messages: list[DeliberationMessage] = field(default_factory=list)
    agreement_rate: float = 0.0
    veto_applied: bool = False
    brain_hits: int = 0
    brain_misses: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "final_side": self.final_side,
            "final_qty": self.final_qty,
            "rationale": self.rationale,
            "proposals": [p.public_dict() for p in self.proposals],
            "agreement_rate": self.agreement_rate,
            "veto_applied": self.veto_applied,
            "brain_hits": self.brain_hits,
            "brain_misses": self.brain_misses,
        }


class DeliberationRuntime:
    """N agents propose → critic/risk may veto → allocator/vote decides."""

    def __init__(self, brain: BrainFacade | None = None) -> None:
        self.brain = brain or BrainFacade()

    def run_round(
        self,
        *,
        run_id: str,
        clock: SimulationClock,
        agents: list[dict[str, Any]],
        strategy_params: dict[str, Any],
        entry_rules: dict[str, Any],
        exit_rules: dict[str, Any],
        position_qty: float,
        brain_dependencies: list[str] | None = None,
    ) -> DeliberationResult:
        bar = clock.current_bar
        assert bar is not None
        proposals: list[AgentProposal] = []
        messages: list[DeliberationMessage] = []
        brain_hits = 0
        brain_misses = 0

        for agent in agents:
            agent_id = str(agent.get("agent_id") or agent.get("role"))
            role = str(agent.get("role") or AgentRole.TREND.value)
            query = (
                f"market regime {role} price={bar.close} ts={bar.ts} "
                f"position={position_qty}"
            )
            brain = self.brain.retrieve(
                query,
                dependencies=brain_dependencies,
                as_of=bar.ts,
            )
            if brain.miss:
                brain_misses += 1
            else:
                brain_hits += 1

            role_bias = None
            if role in {AgentRole.TREND.value, "trend"}:
                role_bias = "trend"
            elif role in {AgentRole.MEAN_REVERSION.value, "mean_reversion"}:
                role_bias = "mean_reversion"

            agent_params = dict(strategy_params)
            agent_params.update(dict(agent.get("parameters") or {}))

            signal = evaluate_strategy(
                clock,
                parameters=agent_params,
                entry_rules=entry_rules,
                exit_rules=exit_rules,
                position_qty=position_qty,
                role_bias=role_bias,
            )

            # Risk officer / critic may veto aggressive buys under drawdown-like conditions
            veto = False
            veto_reason = ""
            if role in {AgentRole.RISK_OFFICER.value, AgentRole.CRITIC.value}:
                if signal.side == OrderSide.BUY.value and signal.confidence < 0.55:
                    veto = True
                    veto_reason = "low-confidence entry challenged"
                    signal = StrategySignal(
                        side=OrderSide.HOLD.value,
                        qty=None,
                        confidence=signal.confidence,
                        rationale=f"veto: {veto_reason}",
                        parameters_used=signal.parameters_used,
                    )

            proposal = AgentProposal(
                agent_id=agent_id,
                role=role,
                signal=signal,
                brain=brain,
                veto=veto,
                veto_reason=veto_reason,
            )
            proposals.append(proposal)

            msg = DeliberationMessage(
                message_id=str(uuid.uuid4()),
                run_id=run_id,
                bar_index=clock.index,
                ts=bar.ts,
                agent_id=agent_id,
                role=role,
                kind="proposal",
                content=signal.rationale,
                proposal=signal.public_dict(),
                confidence=signal.confidence,
                brain_refs=brain.hits[:5],
                created_at=bar.ts,
            )
            messages.append(msg)

            if brain.hits:
                messages.append(
                    DeliberationMessage(
                        message_id=str(uuid.uuid4()),
                        run_id=run_id,
                        bar_index=clock.index,
                        ts=bar.ts,
                        agent_id=agent_id,
                        role=role,
                        kind="brain",
                        content=f"brain retrieval hits={len(brain.hits)} miss={brain.miss}",
                        proposal={},
                        confidence=0.0,
                        brain_refs=brain.hits[:5],
                        created_at=bar.ts,
                    )
                )

        # Critic challenges
        for proposal in proposals:
            if proposal.role == AgentRole.CRITIC.value:
                messages.append(
                    DeliberationMessage(
                        message_id=str(uuid.uuid4()),
                        run_id=run_id,
                        bar_index=clock.index,
                        ts=bar.ts,
                        agent_id=proposal.agent_id,
                        role=proposal.role,
                        kind="challenge",
                        content=proposal.veto_reason or "critic reviewed proposals",
                        proposal=proposal.signal.public_dict(),
                        confidence=proposal.signal.confidence,
                        created_at=bar.ts,
                    )
                )

        # Voting among non-risk roles for BUY/SELL; risk veto overrides
        trade_proposals = [
            p
            for p in proposals
            if p.role
            not in {
                AgentRole.RISK_OFFICER.value,
                AgentRole.CRITIC.value,
                AgentRole.ALLOCATOR.value,
            }
            and p.signal.side != OrderSide.HOLD.value
        ]
        veto_applied = any(
            p.veto
            for p in proposals
            if p.role in {AgentRole.RISK_OFFICER.value, AgentRole.CRITIC.value}
        )

        final_side = OrderSide.HOLD.value
        final_qty = None
        rationale = "no consensus — hold"
        agreement_rate = 0.0

        if veto_applied and any(p.signal.side == OrderSide.BUY.value for p in proposals):
            # Soft veto: if risk officer vetoed buys, block buys this round
            risk_vetoes = [
                p
                for p in proposals
                if p.role == AgentRole.RISK_OFFICER.value and p.veto
            ]
            if risk_vetoes:
                final_side = OrderSide.HOLD.value
                rationale = f"risk veto: {risk_vetoes[0].veto_reason}"
                messages.append(
                    DeliberationMessage(
                        message_id=str(uuid.uuid4()),
                        run_id=run_id,
                        bar_index=clock.index,
                        ts=bar.ts,
                        agent_id=risk_vetoes[0].agent_id,
                        role=risk_vetoes[0].role,
                        kind="veto",
                        content=rationale,
                        created_at=bar.ts,
                    )
                )
            else:
                final_side, final_qty, rationale, agreement_rate = self._vote(trade_proposals)
        else:
            final_side, final_qty, rationale, agreement_rate = self._vote(
                trade_proposals or proposals
            )

        messages.append(
            DeliberationMessage(
                message_id=str(uuid.uuid4()),
                run_id=run_id,
                bar_index=clock.index,
                ts=bar.ts,
                agent_id="allocator",
                role=AgentRole.ALLOCATOR.value,
                kind="decision",
                content=rationale,
                proposal={"side": final_side, "qty": final_qty},
                confidence=agreement_rate,
                created_at=bar.ts,
            )
        )

        return DeliberationResult(
            final_side=final_side,
            final_qty=final_qty,
            rationale=rationale,
            proposals=proposals,
            messages=messages,
            agreement_rate=agreement_rate,
            veto_applied=veto_applied,
            brain_hits=brain_hits,
            brain_misses=brain_misses,
        )

    def _vote(
        self, proposals: list[AgentProposal]
    ) -> tuple[str, float | None, str, float]:
        if not proposals:
            return OrderSide.HOLD.value, None, "empty proposals", 0.0
        weights: dict[str, float] = {}
        for p in proposals:
            side = p.signal.side
            weights[side] = weights.get(side, 0.0) + max(0.05, p.signal.confidence)
        winner = max(weights.items(), key=lambda kv: kv[1])[0]
        total = sum(weights.values()) or 1.0
        agreement = weights.get(winner, 0.0) / total
        rationale = f"vote winner={winner} agreement={agreement:.2f} weights={weights}"
        return winner, None, rationale, agreement
