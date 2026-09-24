"""Commit-then-reveal protocol — agents decide blind before the next market event."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from .execution import OrderIntent, make_intent
from .strategy_eval import evaluate_strategy
from .types import DeliberationMessage, OrderSide


def freeze_info_version(*, run_id: str, bar_index: int, closes: list[float], ts: str) -> str:
    payload = {
        "run_id": run_id,
        "bar_index": bar_index,
        "ts": ts,
        "closes_tail": closes[-64:],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]


@dataclass
class SealedDecision:
    agent_id: str
    role: str
    intent: OrderIntent
    sealed_at: str
    info_version: str
    revealed: bool = False
    rationale: str = ""
    strategy_id: str | None = None
    strategy_version: int | None = None
    retrieved_memories: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "intent": self.intent.public_dict(),
            "sealed_at": self.sealed_at,
            "info_version": self.info_version,
            "revealed": self.revealed,
            "rationale": self.rationale,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "retrieved_memories": self.retrieved_memories,
        }


@dataclass
class CommitRevealRound:
    round_id: str
    run_id: str
    bar_index: int
    clock_ts: str
    info_version: str
    phase: str  # discuss | commit | sealed | reveal | filled
    decisions: dict[str, SealedDecision] = field(default_factory=dict)
    discussion_before_deadline: list[dict[str, Any]] = field(default_factory=list)
    discussion_after_deadline: list[dict[str, Any]] = field(default_factory=list)
    sealed_at: str | None = None
    revealed_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "run_id": self.run_id,
            "bar_index": self.bar_index,
            "clock_ts": self.clock_ts,
            "info_version": self.info_version,
            "phase": self.phase,
            "decisions": [d.public_dict() for d in self.decisions.values()],
            "discussion_before_deadline": self.discussion_before_deadline,
            "discussion_after_deadline": self.discussion_after_deadline,
            "sealed_at": self.sealed_at,
            "revealed_at": self.revealed_at,
            "truth": {
                "commit_then_reveal": True,
                "no_post_commit_revision": True,
                "no_future_bar_leak": True,
            },
        }


class CommitRevealProtocol:
    """Per decision bar: freeze info → agents commit → seal → reveal next bar → fill."""

    def __init__(self, *, allow_pre_commit_discussion: bool = True) -> None:
        self.allow_pre_commit_discussion = allow_pre_commit_discussion
        self._open: CommitRevealRound | None = None

    @property
    def open_round(self) -> CommitRevealRound | None:
        return self._open

    def begin_round(
        self,
        *,
        run_id: str,
        bar_index: int,
        clock_ts: str,
        closes: list[float],
        now: str,
    ) -> CommitRevealRound:
        info_version = freeze_info_version(
            run_id=run_id, bar_index=bar_index, closes=closes, ts=clock_ts
        )
        rnd = CommitRevealRound(
            round_id=str(uuid.uuid4()),
            run_id=run_id,
            bar_index=bar_index,
            clock_ts=clock_ts,
            info_version=info_version,
            phase="commit",
        )
        self._open = rnd
        return rnd

    def add_discussion(
        self,
        message: dict[str, Any],
        *,
        before_deadline: bool,
    ) -> None:
        if self._open is None:
            raise RuntimeError("no open commit-reveal round")
        if before_deadline:
            if not self.allow_pre_commit_discussion:
                return
            self._open.discussion_before_deadline.append(message)
        else:
            self._open.discussion_after_deadline.append(message)

    def commit_decision(
        self,
        *,
        agent_id: str,
        role: str,
        side: str,
        qty: float | None,
        wallet_id: str,
        sealed_at: str,
        rationale: str = "",
        confidence: float = 0.0,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
        decision_scope: str = "individual",
        retrieved_memories: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SealedDecision:
        if self._open is None:
            raise RuntimeError("no open round")
        if self._open.phase not in {"commit", "discuss"}:
            raise RuntimeError(f"round sealed; cannot alter decisions (phase={self._open.phase})")
        if agent_id in self._open.decisions:
            raise RuntimeError("decision already committed; post-commit revision forbidden")

        intent = make_intent(
            run_id=self._open.run_id,
            agent_id=agent_id,
            wallet_id=wallet_id,
            side=side,
            qty=qty,
            decision_bar_index=self._open.bar_index,
            decision_ts=self._open.clock_ts,
            info_version=self._open.info_version,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            rationale=rationale,
            confidence=confidence,
            decision_scope=decision_scope,
            metadata=metadata,
        )
        decision = SealedDecision(
            agent_id=agent_id,
            role=role,
            intent=intent,
            sealed_at=sealed_at,
            info_version=self._open.info_version,
            rationale=rationale,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            retrieved_memories=list(retrieved_memories or []),
        )
        self._open.decisions[agent_id] = decision
        return decision

    def seal(self, *, sealed_at: str) -> CommitRevealRound:
        if self._open is None:
            raise RuntimeError("no open round")
        self._open.phase = "sealed"
        self._open.sealed_at = sealed_at
        return self._open

    def reveal(self, *, revealed_at: str) -> list[SealedDecision]:
        if self._open is None:
            raise RuntimeError("no open round")
        if self._open.phase != "sealed":
            raise RuntimeError("must seal before reveal")
        self._open.phase = "reveal"
        self._open.revealed_at = revealed_at
        out = []
        for d in self._open.decisions.values():
            d.revealed = True
            out.append(d)
        return out

    def close(self) -> CommitRevealRound | None:
        rnd = self._open
        if rnd:
            rnd.phase = "filled"
        self._open = None
        return rnd

    def collect_agent_commits(
        self,
        *,
        agents: list[dict[str, Any]],
        clock: Any,
        wallets: dict[str, str],
        strategy_params: dict[str, Any],
        entry_rules: dict[str, Any],
        exit_rules: dict[str, Any],
        agent_positions: dict[str, float],
        now: str,
        strategy_id: str | None = None,
        strategy_version: int | None = None,
        memory_lookup: Any | None = None,
    ) -> tuple[CommitRevealRound, list[DeliberationMessage]]:
        """Deterministic DSL commits for each agent against frozen causal window."""
        bar = clock.current_bar
        assert bar is not None
        closes = clock.closes(min(500, clock.index + 1))
        rnd = self.begin_round(
            run_id=agents[0].get("run_id", "") if agents else "",
            bar_index=clock.index,
            clock_ts=bar.ts,
            closes=closes,
            now=now,
        )
        # Fix run_id if passed via agents metadata
        run_id = str(agents[0].get("run_id") or "")
        if run_id:
            rnd.run_id = run_id

        messages: list[DeliberationMessage] = []
        for agent in agents:
            agent_id = str(agent.get("agent_id") or agent.get("role"))
            role = str(agent.get("role") or "trend")
            wallet_id = wallets.get(agent_id, f"wal-{agent_id}")
            pos = float(agent_positions.get(agent_id, 0.0))
            params = dict(strategy_params)
            params.update(dict(agent.get("parameters") or {}))
            role_bias = None
            if role in {"trend", "market_analyst", "strategy_researcher"}:
                role_bias = "trend"
            elif role in {"mean_reversion"}:
                role_bias = "mean_reversion"

            memories: list[dict[str, Any]] = []
            if memory_lookup is not None:
                try:
                    memories = list(memory_lookup(agent_id, role, bar.ts) or [])
                except Exception:  # noqa: BLE001
                    memories = []

            signal = evaluate_strategy(
                clock,
                parameters=params,
                entry_rules=entry_rules,
                exit_rules=exit_rules,
                position_qty=pos,
                role_bias=role_bias,
            )

            # Risk officer / critic: may commit HOLD/veto but never mutate others' wallets
            side = signal.side
            rationale = signal.rationale
            if role in {"risk_officer", "risk_agent", "critic"}:
                if signal.side == OrderSide.BUY.value and signal.confidence < 0.55:
                    side = OrderSide.HOLD.value
                    rationale = f"risk veto: low-confidence entry ({signal.confidence:.2f})"

            decision = self.commit_decision(
                agent_id=agent_id,
                role=role,
                side=side,
                qty=signal.qty,
                wallet_id=wallet_id,
                sealed_at=now,
                rationale=rationale,
                confidence=signal.confidence,
                strategy_id=str(agent.get("strategy_id") or strategy_id or "") or None,
                strategy_version=agent.get("strategy_version", strategy_version),
                decision_scope="individual",
                retrieved_memories=memories,
                metadata={"parameters_used": signal.parameters_used},
            )
            # Patch intent run_id
            decision.intent.run_id = rnd.run_id

            messages.append(
                DeliberationMessage(
                    message_id=str(uuid.uuid4()),
                    run_id=rnd.run_id,
                    bar_index=clock.index,
                    ts=bar.ts,
                    agent_id=agent_id,
                    role=role,
                    kind="commit",
                    content=rationale,
                    proposal=decision.intent.public_dict(),
                    confidence=signal.confidence,
                    brain_refs=memories,
                    created_at=now,
                )
            )

        self.seal(sealed_at=now)
        return rnd, messages
