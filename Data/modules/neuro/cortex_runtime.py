"""Cortex runtime — named functional circuits with bounded K + early-exit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .critic import ProcessCritic
from .residual import (
    ResidualForwardRequest,
    ResidualHookPoint,
    ResidualInjectRequest,
    ResidualReadRequest,
    ResidualStreamPort,
)

# Named cortex circuits (advisory functional blocks — not a second model).
NAMED_CORTEX_BLOCKS: tuple[str, ...] = (
    "planning",
    "verification",
    "tool_selection",
    "memory_projection",
    "self_critique",
)


@dataclass(frozen=True)
class CortexBlockSpec:
    block_id: str
    layer_index: int
    rank: int = 8
    enabled: bool = True
    circuit: str = "generic"  # planning | verification | tool_selection | ...

    def public_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "layer_index": self.layer_index,
            "rank": self.rank,
            "enabled": self.enabled,
            "circuit": self.circuit,
        }


@dataclass(frozen=True)
class CortexRunReport:
    engaged: bool
    depth: int
    blocks: tuple[CortexBlockSpec, ...]
    critic_scores: tuple[dict[str, Any], ...]
    residual_reads: tuple[dict[str, Any], ...]
    inject_receipts: tuple[dict[str, Any], ...]
    forward: dict[str, Any] | None
    degraded: bool
    detail: str
    path: str = "lean"
    residual_replay_layers: tuple[int, ...] = ()
    mid_forward_interventions: int = 0
    early_exit: bool = False
    early_exit_reason: str = ""
    k_used: int = 0
    max_k: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "engaged": self.engaged,
            "depth": self.depth,
            "path": self.path,
            "blocks": [item.public_dict() for item in self.blocks],
            "critic_scores": list(self.critic_scores),
            "residual_reads": list(self.residual_reads),
            "inject_receipts": list(self.inject_receipts),
            "forward": self.forward,
            "degraded": self.degraded,
            "detail": self.detail,
            "residual_replay_layers": list(self.residual_replay_layers),
            "mid_forward_interventions": self.mid_forward_interventions,
            "early_exit": self.early_exit,
            "early_exit_reason": self.early_exit_reason,
            "k_used": self.k_used,
            "max_k": self.max_k,
            "truth": {
                "cortex_run_is_not_completion_authority": True,
                "neural_signal_is_not_authority": True,
                "depth_is_not_authority": True,
            },
        }


class CortexRuntime:
    """Execute named cortex blocks against a ResidualStreamPort with bounded critic loops.

    Mid-forward ProcessCritic may re-steer residual injects up to K rounds when
    consistency / grounding scores fall below thresholds. Early-exit when scores
    clear floors. Advisory only.
    """

    def __init__(
        self,
        *,
        residual_port: ResidualStreamPort,
        critic: ProcessCritic | None = None,
        max_depth: int = 2,
        max_critic_rounds: int = 2,
        max_k: int | None = None,
        consistency_floor: float = 0.45,
        grounding_floor: float = 0.35,
        named_blocks_enabled: bool = False,
        early_exit_enabled: bool = True,
    ) -> None:
        self.residual_port = residual_port
        self.critic = critic or ProcessCritic(enabled=True)
        self.max_depth = max(0, max_depth)
        self.max_critic_rounds = max(0, max_critic_rounds)
        self.max_k = max(0, int(max_k if max_k is not None else max_critic_rounds))
        self.consistency_floor = consistency_floor
        self.grounding_floor = grounding_floor
        self.named_blocks_enabled = named_blocks_enabled
        self.early_exit_enabled = early_exit_enabled

    def build_blocks(self, depth: int) -> tuple[CortexBlockSpec, ...]:
        hooks = list(self.residual_port.list_hook_points())
        if not hooks:
            return ()
        depth = max(1, min(depth, self.max_depth, len(NAMED_CORTEX_BLOCKS)))
        selected = hooks[len(hooks) // 3 : len(hooks) // 3 + depth]
        if not selected:
            selected = hooks[:depth]
        blocks: list[CortexBlockSpec] = []
        for i, h in enumerate(selected):
            circuit = (
                NAMED_CORTEX_BLOCKS[i % len(NAMED_CORTEX_BLOCKS)]
                if self.named_blocks_enabled
                else "generic"
            )
            block_id = f"cortex_{circuit}_{h.layer_index}" if self.named_blocks_enabled else f"cortex_{h.layer_index}"
            blocks.append(
                CortexBlockSpec(
                    block_id=block_id,
                    layer_index=h.layer_index,
                    rank=8,
                    circuit=circuit,
                )
            )
        return tuple(blocks)

    def run(
        self,
        *,
        messages: list[dict[str, str]],
        depth: int,
        critic_rounds: int,
        inject: Sequence[ResidualInjectRequest] = (),
        plan_steps: Sequence[str] | None = None,
        knowledge_ids: Sequence[str] | None = None,
        evidence_ids: Sequence[str] | None = None,
    ) -> CortexRunReport:
        if not self.residual_port.supports_residuals():
            return CortexRunReport(
                engaged=False,
                depth=0,
                blocks=(),
                critic_scores=(),
                residual_reads=(),
                inject_receipts=(),
                forward=None,
                degraded=True,
                detail="Residual port unsupported — cortex degraded",
                path="lean",
                max_k=self.max_k,
            )

        depth = min(max(0, depth), self.max_depth)
        # K budget: critic_rounds capped by max_k (LEVIATHAN_NEURO_CORTEX_MAX_K).
        k_cap = self.max_k if self.max_k > 0 else self.max_critic_rounds
        critic_rounds = min(max(0, critic_rounds), self.max_critic_rounds, k_cap)
        blocks = self.build_blocks(depth) if depth > 0 else ()
        reads: list[dict[str, Any]] = []
        scores: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        inject_list = list(inject)
        interventions = 0
        replay_layers: list[int] = []
        early_exit = False
        early_exit_reason = ""
        k_used = 0

        for block in blocks:
            if not block.enabled:
                continue
            hook = ResidualHookPoint(layer_index=block.layer_index, name=block.block_id, site="block_out")
            tensor = self.residual_port.read(ResidualReadRequest(hook=hook))
            reads.append(tensor.public_dict())
            score = self.critic.score_residual(
                tensor,
                plan_steps=plan_steps,
                knowledge_ids=knowledge_ids,
                evidence_ids=evidence_ids,
            )
            scores.append(score.public_dict())
            replay_layers.append(block.layer_index)

        # Bounded mid-forward critic loop — re-steer residual path when scores are weak.
        for round_idx in range(critic_rounds):
            k_used = round_idx + 1
            probe_text = ""
            if reads:
                probe_text = str(reads[-1].get("note") or "")
            if not probe_text and messages:
                probe_text = str(messages[-1].get("content") or "")
            score = self.critic.score(
                probe_text,
                plan_steps=plan_steps,
                knowledge_ids=knowledge_ids,
                evidence_ids=evidence_ids,
            )
            scores.append(score.public_dict())
            passes_floors = (
                score.consistency >= self.consistency_floor
                and score.factual_grounding >= self.grounding_floor
            )
            if self.early_exit_enabled and passes_floors:
                early_exit = True
                early_exit_reason = (
                    f"early_exit at k={k_used}: consistency={score.consistency:.3f} "
                    f"grounding={score.factual_grounding:.3f}"
                )
                break
            needs_steer = (
                score.consistency < self.consistency_floor
                or score.factual_grounding < self.grounding_floor
            )
            if needs_steer and blocks:
                target = blocks[min(round_idx, len(blocks) - 1)]
                hook = ResidualHookPoint(
                    layer_index=target.layer_index,
                    name=f"{target.block_id}_resteer",
                    site="block_out",
                )
                payload = None
                if evidence_ids:
                    payload = str(evidence_ids[0])
                elif knowledge_ids:
                    payload = str(knowledge_ids[0])
                scale = 0.15 + 0.05 * (round_idx + 1)
                mode = "GATED" if score.factual_grounding < self.grounding_floor else "ADDITIVE"
                req = ResidualInjectRequest(
                    hook=hook,
                    mode=mode,
                    scale=scale,
                    source=f"neuro.cortex.mid_forward_critic.{target.circuit}",
                    payload_ref=payload,
                )
                receipt = self.residual_port.inject(req)
                receipts.append(receipt.public_dict())
                inject_list.append(req)
                interventions += 1
                replay = self.residual_port.read(ResidualReadRequest(hook=hook))
                reads.append(replay.public_dict())
                if target.layer_index not in replay_layers:
                    replay_layers.append(target.layer_index)

        forward = self.residual_port.run_forward(
            ResidualForwardRequest(
                messages=messages,
                engage_cortex=depth > 0,
                critic_rounds=critic_rounds,
                inject=tuple(inject_list),
            )
        )
        for receipt in forward.receipts:
            receipts.append(receipt.public_dict())

        detail = "Cortex runtime completed against residual port"
        if early_exit:
            detail = f"{detail}; {early_exit_reason}"

        return CortexRunReport(
            engaged=depth > 0,
            depth=depth,
            blocks=blocks,
            critic_scores=tuple(scores),
            residual_reads=tuple(reads),
            inject_receipts=tuple(receipts),
            forward=forward.public_dict(),
            degraded=forward.degraded_to_chat_completions,
            detail=detail,
            path="complex" if depth > 0 else "lean",
            residual_replay_layers=tuple(replay_layers),
            mid_forward_interventions=interventions,
            early_exit=early_exit,
            early_exit_reason=early_exit_reason,
            k_used=k_used,
            max_k=k_cap,
        )
