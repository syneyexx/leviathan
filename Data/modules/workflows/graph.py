"""Workflow graph helpers — linear↔graph conversion, validation, hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .types import (
    WorkflowEdgeDef,
    WorkflowGraph,
    WorkflowLayoutNode,
    WorkflowNodeDef,
    WorkflowNodeKind,
    WorkflowStepDef,
    WorkflowVariableDef,
)


def steps_to_graph(steps: list[WorkflowStepDef]) -> WorkflowGraph:
    """Convert legacy ordered steps into an equivalent sequential graph."""
    if not steps:
        trigger = WorkflowNodeDef(
            node_id="trigger-manual",
            kind=WorkflowNodeKind.TRIGGER,
            label="Manual",
            config={"trigger_kind": "MANUAL"},
        )
        return WorkflowGraph(nodes=[trigger], edges=[])

    nodes: list[WorkflowNodeDef] = [
        WorkflowNodeDef(
            node_id="trigger-manual",
            kind=WorkflowNodeKind.TRIGGER,
            label="Manual",
            config={"trigger_kind": "MANUAL"},
        )
    ]
    edges: list[WorkflowEdgeDef] = []
    prev = "trigger-manual"
    for step in steps:
        nodes.append(
            WorkflowNodeDef(
                node_id=step.step_id,
                kind=WorkflowNodeKind.CAPABILITY,
                label=step.capability_id,
                config={
                    "capability_id": step.capability_id,
                    "arguments": dict(step.arguments or {}),
                    "approval_id": step.approval_id,
                },
            )
        )
        edges.append(
            WorkflowEdgeDef(
                edge_id=f"{prev}->{step.step_id}",
                source=prev,
                target=step.step_id,
            )
        )
        prev = step.step_id
    return WorkflowGraph(nodes=nodes, edges=edges)


def default_layout_for_graph(graph: WorkflowGraph) -> list[WorkflowLayoutNode]:
    layout: list[WorkflowLayoutNode] = []
    x, y = 40.0, 80.0
    for idx, node in enumerate(graph.nodes):
        layout.append(WorkflowLayoutNode(node_id=node.node_id, x=x + (idx % 4) * 180, y=y + (idx // 4) * 120))
    return layout


def content_hash(
    *,
    graph: WorkflowGraph,
    variables: list[WorkflowVariableDef],
    config: dict[str, Any],
) -> str:
    payload = {
        "graph": graph.public_dict(),
        "variables": [v.public_dict() for v in variables],
        "config": config or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_graph(
    graph: WorkflowGraph,
    *,
    variables: list[WorkflowVariableDef] | None = None,
    capability_ids: set[str] | None = None,
    allow_draft_warnings: bool = True,
) -> dict[str, Any]:
    """Return structured validation diagnostics.

    ``ok`` is False when the graph is not safely executable.
    Warnings may remain when ``allow_draft_warnings`` is True.
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    node_ids = [n.node_id for n in graph.nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append({"code": "WORKFLOW_INVALID", "message": "Node IDs must be unique"})
    by_id = {n.node_id: n for n in graph.nodes if n.node_id}

    for edge in graph.edges:
        if edge.source not in by_id:
            errors.append(
                {
                    "code": "WORKFLOW_INVALID",
                    "message": f"Edge {edge.edge_id} references missing source {edge.source}",
                }
            )
        if edge.target not in by_id:
            errors.append(
                {
                    "code": "WORKFLOW_INVALID",
                    "message": f"Edge {edge.edge_id} references missing target {edge.target}",
                }
            )

    triggers = [n for n in graph.nodes if n.kind_value == WorkflowNodeKind.TRIGGER.value]
    if not triggers:
        warnings.append({"code": "TRIGGER_INVALID", "message": "No trigger node present"})
    elif len(triggers) > 1:
        warnings.append({"code": "TRIGGER_INVALID", "message": "Multiple trigger nodes present"})

    for node in graph.nodes:
        kind = node.kind_value
        cfg = dict(node.config or {})
        if kind in {WorkflowNodeKind.CAPABILITY.value, WorkflowNodeKind.AGENT.value}:
            cap = str(cfg.get("capability_id") or "").strip()
            if not cap:
                errors.append(
                    {
                        "code": "WORKFLOW_INVALID",
                        "message": f"Node {node.node_id} missing capability_id",
                        "node_id": node.node_id,
                    }
                )
            elif capability_ids is not None and cap not in capability_ids:
                errors.append(
                    {
                        "code": "CAPABILITY_UNAVAILABLE",
                        "message": f"Capability {cap} is not registered",
                        "node_id": node.node_id,
                        "capability_id": cap,
                    }
                )
        elif kind == WorkflowNodeKind.CONDITION.value:
            pred = cfg.get("predicate") or cfg.get("op")
            if not pred:
                errors.append(
                    {
                        "code": "WORKFLOW_INVALID",
                        "message": f"Condition node {node.node_id} missing predicate",
                        "node_id": node.node_id,
                    }
                )
            outs = {e.source_handle for e in graph.edges if e.source == node.node_id}
            if "true" not in outs and "false" not in outs:
                warnings.append(
                    {
                        "code": "WORKFLOW_INVALID",
                        "message": f"Condition {node.node_id} has no true/false edges",
                        "node_id": node.node_id,
                    }
                )
        elif kind == WorkflowNodeKind.LOOP.value:
            max_iter = cfg.get("max_iterations")
            try:
                max_i = int(max_iter) if max_iter is not None else 0
            except (TypeError, ValueError):
                max_i = 0
            if max_i < 1:
                errors.append(
                    {
                        "code": "LOOP_LIMIT_EXCEEDED",
                        "message": f"Loop node {node.node_id} requires max_iterations >= 1",
                        "node_id": node.node_id,
                    }
                )
        elif kind == WorkflowNodeKind.DELAY.value:
            seconds = cfg.get("delay_seconds")
            try:
                delay = float(seconds) if seconds is not None else -1
            except (TypeError, ValueError):
                delay = -1
            if delay < 0:
                errors.append(
                    {
                        "code": "WORKFLOW_INVALID",
                        "message": f"Delay node {node.node_id} requires delay_seconds >= 0",
                        "node_id": node.node_id,
                    }
                )

    # Cycle detection: reject arbitrary cycles unless via explicit LOOP nodes.
    adj: dict[str, list[str]] = {n.node_id: [] for n in graph.nodes}
    for edge in graph.edges:
        if edge.source in adj:
            adj[edge.source].append(edge.target)
    loop_nodes = {n.node_id for n in graph.nodes if n.kind_value == WorkflowNodeKind.LOOP.value}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(nid: str, path: list[str]) -> None:
        if nid in visiting:
            # Cycle — allowed only if a LOOP node is on the cycle path.
            cycle = path[path.index(nid) :] + [nid]
            if not any(c in loop_nodes for c in cycle):
                errors.append(
                    {
                        "code": "WORKFLOW_INVALID",
                        "message": f"Illegal unbounded cycle involving {nid}",
                        "cycle": cycle,
                    }
                )
            return
        if nid in visited:
            return
        visiting.add(nid)
        for nxt in adj.get(nid, []):
            dfs(nxt, path + [nid])
        visiting.discard(nid)
        visited.add(nid)

    for nid in adj:
        dfs(nid, [])

    # Reachability from triggers
    if triggers:
        reachable: set[str] = set()
        stack = [t.node_id for t in triggers]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            stack.extend(adj.get(cur, []))
        for node in graph.nodes:
            if node.node_id not in reachable:
                warnings.append(
                    {
                        "code": "WORKFLOW_INVALID",
                        "message": f"Unreachable node {node.node_id}",
                        "node_id": node.node_id,
                    }
                )

    if variables:
        for var in variables:
            if var.secret and var.default not in (None, "", {}):
                # Defaults for secrets must be references, not plaintext blobs.
                default_s = str(var.default)
                if not default_s.startswith("secret:") and not default_s.startswith("{{"):
                    errors.append(
                        {
                            "code": "VARIABLE_VALIDATION_FAILED",
                            "message": f"Secret variable {var.name} must not store plaintext defaults",
                            "variable": var.name,
                        }
                    )

    ok = len(errors) == 0
    if not allow_draft_warnings:
        ok = ok and not any(w.get("code") == "CAPABILITY_UNAVAILABLE" for w in warnings)
    return {"ok": ok, "errors": errors, "warnings": warnings}
