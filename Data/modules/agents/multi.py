"""DAG multi-agent executor with dependencies, parallel branches, joins (U143)."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable

from .blackboard import AgentBlackboard
from .runtime import AgentRuntime
from .types import AgentKind, AgentResult


@dataclass(frozen=True)
class DagNode:
    node_id: str
    kind: AgentKind
    depends_on: tuple[str, ...] = ()
    request_override: str | None = None
    budget: dict[str, Any] = field(default_factory=dict)
    capability_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "depends_on": list(self.depends_on),
            "request_override": self.request_override,
            "budget": dict(self.budget),
            "capability_overrides": dict(self.capability_overrides),
        }


@dataclass
class MultiAgentResult:
    status: str
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    blackboard: dict[str, Any] | None = None
    parallel: bool = False
    cancelled: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "results": self.results,
            "error": self.error,
            "blackboard": self.blackboard,
            "parallel": self.parallel,
            "cancelled": self.cancelled,
            "truth": {
                "multi_agent_still_uses_shared_gateway": True,
                "no_private_agent_execution": True,
                "dag_supports_parallel_joins": True,
            },
        }


class DagCycleError(ValueError):
    pass


class MultiAgentCoordinator:
    """DAG executor over shared AgentRuntime — not a second job system."""

    def __init__(self, agents: AgentRuntime, *, signal_fabric: Any = None) -> None:
        self.agents = agents
        self.signal_fabric = signal_fabric

    def bind_signal_fabric(self, fabric: Any) -> None:
        self.signal_fabric = fabric

    def run(
        self,
        request: str,
        *,
        kinds: list[AgentKind] | tuple[AgentKind, ...] | None = None,
        capability_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> MultiAgentResult:
        """Backward-compatible sequential path (linear DAG). """
        sequence = list(kinds or (AgentKind.RESEARCH, AgentKind.GENERIC))
        nodes = [
            DagNode(
                node_id=f"n{i}",
                kind=kind,
                depends_on=() if i == 0 else (f"n{i - 1}",),
                capability_overrides=dict(capability_overrides or {}),
            )
            for i, kind in enumerate(sequence)
        ]
        return self.run_dag(request, nodes=nodes, max_parallel=1)

    def run_dag(
        self,
        request: str,
        *,
        nodes: list[DagNode] | tuple[DagNode, ...],
        max_parallel: int = 2,
        cancel_check: Callable[[], bool] | None = None,
        run_id: str | None = None,
        blackboard: AgentBlackboard | None = None,
    ) -> MultiAgentResult:
        if not self.agents.agents_enabled:
            return MultiAgentResult(
                status="DISABLED",
                error="Agents feature flag is OFF",
            )
        graph = list(nodes)
        if not graph:
            return MultiAgentResult(status="FAILED", error="empty DAG")
        cycle = self.detect_cycle(graph)
        if cycle:
            raise DagCycleError(f"DAG cycle detected: {' -> '.join(cycle)}")

        board = blackboard or AgentBlackboard(run_id=run_id)
        if self.signal_fabric is not None and run_id:
            try:
                self.signal_fabric.register_blackboard(run_id, board)
            except Exception:  # noqa: BLE001
                pass
        board.post(
            kind="open_question",
            content=request,
            author="orchestrator",
            confidence=1.0,
            provenance={"run_id": run_id},
        )

        by_id = {n.node_id: n for n in graph}
        pending = set(by_id)
        completed: dict[str, AgentResult] = {}
        failed: dict[str, AgentResult] = {}
        results: list[dict[str, Any]] = []
        parallel_used = False
        workers = max(1, int(max_parallel))

        while pending:
            if cancel_check and cancel_check():
                return MultiAgentResult(
                    status="CANCELLED",
                    results=results,
                    error="cancelled",
                    blackboard=board.public_dict(),
                    parallel=parallel_used,
                    cancelled=True,
                )
            ready = [
                nid
                for nid in sorted(pending)
                if all(
                    dep in completed or dep in failed
                    for dep in by_id[nid].depends_on
                )
                and all(dep not in failed for dep in by_id[nid].depends_on)
            ]
            # Soft-fail policy: if a dependency failed, skip dependents as blocked.
            blocked = [
                nid
                for nid in sorted(pending)
                if any(dep in failed for dep in by_id[nid].depends_on)
            ]
            for nid in blocked:
                pending.discard(nid)
                node = by_id[nid]
                blocked_result = AgentResult(
                    agent_kind=node.kind,
                    run_id=run_id,
                    status="BLOCKED",
                    error=f"dependency failed: {list(node.depends_on)}",
                )
                results.append(
                    {
                        **blocked_result.public_dict(),
                        "node_id": nid,
                        "depends_on": list(node.depends_on),
                    }
                )
                board.post(
                    kind="decision",
                    content=f"node {nid} blocked by failed dependency",
                    author="orchestrator",
                    confidence=1.0,
                )

            if not ready and pending:
                # Deadlock: remaining nodes wait on unfinished/nonexistent deps.
                return MultiAgentResult(
                    status="DEADLOCK",
                    results=results,
                    error=f"no-progress / deadlock pending={sorted(pending)}",
                    blackboard=board.public_dict(),
                    parallel=parallel_used,
                )
            if not ready:
                break

            batch = ready[:workers]
            if len(batch) > 1:
                parallel_used = True

            def _execute(node_id: str) -> tuple[str, AgentResult]:
                node = by_id[node_id]
                req = node.request_override or request
                outcome = self.agents.execute(
                    req,
                    kind=node.kind,
                    run_id=run_id,
                    capability_overrides=node.capability_overrides or None,
                )
                return node_id, outcome

            if workers == 1 or len(batch) == 1:
                executed = [_execute(batch[0])]
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = [pool.submit(_execute, nid) for nid in batch]
                    executed = [f.result() for f in concurrent.futures.as_completed(futs)]

            for node_id, outcome in executed:
                pending.discard(node_id)
                record = {
                    **outcome.public_dict(),
                    "node_id": node_id,
                    "depends_on": list(by_id[node_id].depends_on),
                }
                results.append(record)
                board.post(
                    kind="finding",
                    content=outcome.output or outcome.status,
                    author=f"agent:{outcome.agent_kind.value}",
                    confidence=0.7 if outcome.status == "COMPLETED" else 0.3,
                    provenance={"node_id": node_id, "status": outcome.status},
                )
                if outcome.status in {"FAILED", "DISABLED", "UNVERIFIED"}:
                    failed[node_id] = outcome
                else:
                    completed[node_id] = outcome

        if failed and not completed:
            status = next(iter(failed.values())).status
            return MultiAgentResult(
                status=status,
                results=results,
                error=next(iter(failed.values())).error,
                blackboard=board.public_dict(),
                parallel=parallel_used,
            )
        if failed:
            return MultiAgentResult(
                status="PARTIAL",
                results=results,
                error="one or more DAG nodes failed",
                blackboard=board.public_dict(),
                parallel=parallel_used,
            )
        return MultiAgentResult(
            status="COMPLETED",
            results=results,
            blackboard=board.public_dict(),
            parallel=parallel_used,
        )

    @staticmethod
    def detect_cycle(nodes: list[DagNode] | tuple[DagNode, ...]) -> list[str] | None:
        """Return a cycle path if depends_on edges form a cycle; else None."""
        graph = {n.node_id: [d for d in n.depends_on if d] for n in nodes}
        color: dict[str, int] = {n: 0 for n in graph}  # 0=white 1=gray 2=black
        path: list[str] = []

        def walk(node: str) -> list[str] | None:
            color[node] = 1
            path.append(node)
            for dep in graph.get(node, []):
                if dep not in color:
                    continue
                if color[dep] == 1:
                    return path[path.index(dep) :] + [dep]
                if color[dep] == 0:
                    found = walk(dep)
                    if found:
                        return found
            color[node] = 2
            path.pop()
            return None

        for nid in graph:
            if color[nid] == 0:
                found = walk(nid)
                if found:
                    return found
        return None
