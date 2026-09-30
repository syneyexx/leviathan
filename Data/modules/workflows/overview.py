"""Server-side workflow overview projections — KPIs, charts, top, recent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .store import WorkflowStore
from .types import WorkflowDefinitionStatus, WorkflowExecutionState


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _delta_or_unmeasured(current: float | None, previous: float | None) -> dict[str, Any]:
    if current is None or previous is None:
        return {"value": None, "display": "—", "direction": "flat"}
    if previous == 0:
        if current == 0:
            return {"value": 0.0, "display": "—", "direction": "flat"}
        return {"value": None, "display": "—", "direction": "flat"}
    change = ((current - previous) / abs(previous)) * 100.0
    direction = "up" if change > 0.05 else "down" if change < -0.05 else "flat"
    sign = "+" if change > 0 else ""
    return {"value": round(change, 1), "display": f"{sign}{change:.1f}%", "direction": direction}


def build_workflows_overview(
    store: WorkflowStore,
    *,
    telemetry: dict[str, Any] | None = None,
    workers: dict[str, Any] | None = None,
    chart_hours: int = 24,
    top_days: int = 7,
) -> dict[str, Any]:
    now = _utc_now()
    period_end = now
    period_start = now - timedelta(hours=max(1, chart_hours))
    prev_start = period_start - (period_end - period_start)

    total = store.count_definitions(exclude_templates=True, exclude_archived=True)
    active = store.count_definitions(status=WorkflowDefinitionStatus.ACTIVE.value)
    inactive = store.count_definitions(status=WorkflowDefinitionStatus.INACTIVE.value)
    drafts = store.count_definitions(status=WorkflowDefinitionStatus.DRAFT.value)
    templates = store.count_definitions(status=WorkflowDefinitionStatus.TEMPLATE.value, exclude_templates=False)

    cur = store.aggregate_execution_stats(since=_iso(period_start), until=_iso(period_end))
    prev = store.aggregate_execution_stats(since=_iso(prev_start), until=_iso(period_start))
    all_time = store.aggregate_execution_stats()

    running = store.count_executions(
        states=[
            WorkflowExecutionState.QUEUED.value,
            WorkflowExecutionState.STARTING.value,
            WorkflowExecutionState.RUNNING.value,
            WorkflowExecutionState.WAITING.value,
            WorkflowExecutionState.WAITING_APPROVAL.value,
            WorkflowExecutionState.CANCELLING.value,
        ]
    )

    # Success rate: successful / (successful + failed); cancelled excluded from denominator.
    success_rate = all_time.get("success_rate")
    prev_success = prev.get("success_rate")
    # Period-over-period for success uses same window comparison.
    period_success = cur.get("success_rate")

    avg_ms = all_time.get("avg_duration_ms")
    prev_avg = prev.get("avg_duration_ms")
    avg_change = _delta_or_unmeasured(avg_ms, prev_avg)

    total_exec = all_time.get("total") or 0
    prev_total = prev.get("total") or 0
    # Compare last window totals for change indicator on total executions.
    cur_total = cur.get("total") or 0
    exec_change = _delta_or_unmeasured(float(cur_total), float(prev_total) if prev_total else None)

    buckets = store.execution_time_buckets(
        since=_iso(period_start),
        until=_iso(period_end),
        bucket_seconds=3600 if chart_hours <= 48 else 86400,
    )
    top_since = now - timedelta(days=max(1, top_days))
    top = store.top_workflows_by_executions(since=_iso(top_since), until=_iso(now), limit=5)
    max_top = max((t["execution_count"] for t in top), default=0) or 1
    for idx, item in enumerate(top, start=1):
        item["rank"] = idx
        item["relative"] = round(item["execution_count"] / max_top, 4)

    recent = [
        {
            **e.public_dict(),
            "name": e.name_snapshot or e.workflow_id,
        }
        for e in store.list_executions(limit=12)
    ]

    # Sparklines from buckets (succeeded series)
    spark_success = [int(b.get("succeeded") or 0) for b in buckets]
    spark_failed = [int(b.get("failed") or 0) for b in buckets]

    resources = _resource_projection(telemetry=telemetry, workers=workers)

    return {
        "generated_at": _iso(now),
        "counts": {
            "total_definitions": total,
            "active_definitions": active,
            "inactive_definitions": inactive,
            "draft_definitions": drafts,
            "templates": templates,
            "running_executions": running,
        },
        "kpis": [
            {
                "id": "total_workflows",
                "label": "Totale Workflows",
                "value": total,
                "secondary": None,
                "change": _delta_or_unmeasured(float(total), None),
                "sparkline": spark_success[-12:] if spark_success else [],
            },
            {
                "id": "active_workflows",
                "label": "Actieve Workflows",
                "value": active,
                "secondary": f"{running} running" if running else "0 running",
                "change": _delta_or_unmeasured(float(active), None),
                "sparkline": [],
            },
            {
                "id": "success_rate",
                "label": "Succes Rate",
                "value": round(success_rate * 100.0, 1) if success_rate is not None else None,
                "unit": "%",
                "secondary": all_time.get("success_rate_denominator"),
                "change": _delta_or_unmeasured(
                    (period_success * 100.0) if period_success is not None else None,
                    (prev_success * 100.0) if prev_success is not None else None,
                ),
                "sparkline": spark_success[-12:] if spark_success else [],
                "unmeasured": success_rate is None,
            },
            {
                "id": "avg_duration",
                "label": "Gem. Uitvoeringstijd",
                "value": round((avg_ms or 0) / 60000.0, 2) if avg_ms is not None else None,
                "unit": "min",
                "secondary": None,
                "change": avg_change,
                "sparkline": [],
                "unmeasured": avg_ms is None,
            },
            {
                "id": "total_executions",
                "label": "Totaal Executies",
                "value": total_exec,
                "secondary": None,
                "change": exec_change,
                "sparkline": [s + f for s, f in zip(spark_success, spark_failed)][-12:]
                if spark_success
                else [],
            },
        ],
        "chart": {
            "period": f"last_{chart_hours}h",
            "buckets": buckets,
            "series": {
                "succeeded": sum(int(b.get("succeeded") or 0) for b in buckets),
                "failed": sum(int(b.get("failed") or 0) for b in buckets),
                "cancelled": sum(int(b.get("cancelled") or 0) for b in buckets),
            },
        },
        "top_workflows": {
            "period": f"last_{top_days}d",
            "items": top,
        },
        "recent_executions": recent,
        "resources": resources,
    }


def _resource_projection(
    *,
    telemetry: dict[str, Any] | None,
    workers: dict[str, Any] | None,
) -> dict[str, Any]:
    cpu: dict[str, Any] = {"available": False, "utilization_pct": None, "display": "UNMEASURED"}
    memory: dict[str, Any] = {
        "available": False,
        "used_bytes": None,
        "total_bytes": None,
        "display": "UNMEASURED",
    }
    if telemetry:
        cpu_block = telemetry.get("cpu") or {}
        mem_block = telemetry.get("memory") or {}
        if cpu_block.get("available") and cpu_block.get("utilizationPct") is not None:
            pct = float(cpu_block["utilizationPct"])
            cpu = {"available": True, "utilization_pct": pct, "display": f"{pct:.0f}%"}
        if mem_block.get("available") and mem_block.get("usedBytes") is not None:
            used = int(mem_block["usedBytes"])
            total = int(mem_block.get("totalBytes") or 0) or None
            memory = {
                "available": True,
                "used_bytes": used,
                "total_bytes": total,
                "display": _fmt_bytes(used) + (f" van {_fmt_bytes(total)}" if total else ""),
            }

    worker_proj: dict[str, Any] = {
        "available": False,
        "busy": None,
        "capacity": None,
        "display": "UNMEASURED",
        "semantics": "BUSY workers / desired capacity for workflow pool (fallback: all pools)",
    }
    if workers:
        busy = workers.get("busy")
        capacity = workers.get("desired") or workers.get("capacity") or workers.get("ready")
        if busy is not None and capacity is not None:
            worker_proj = {
                "available": True,
                "busy": int(busy),
                "capacity": int(capacity),
                "display": f"{int(busy)} van {int(capacity)}",
                "semantics": workers.get("semantics")
                or "BUSY workers / desired capacity for workflow pool",
            }
    return {"cpu": cpu, "memory": memory, "workers": worker_proj}


def _fmt_bytes(num: int | None) -> str:
    if num is None:
        return "UNMEASURED"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num} B"


def definition_dependency_counts(definition: Any, *, catalog: Any | None = None) -> dict[str, int]:
    """Count tools / agents / MCP servers referenced by graph nodes."""
    tools: set[str] = set()
    agents: set[str] = set()
    mcp_servers: set[str] = set()
    graph = getattr(definition, "graph", None)
    nodes = getattr(graph, "nodes", []) if graph is not None else []
    for node in nodes:
        kind = node.kind_value if hasattr(node, "kind_value") else str(getattr(node, "kind", ""))
        cfg = dict(getattr(node, "config", None) or {})
        cap = str(cfg.get("capability_id") or "").strip()
        if not cap:
            continue
        if kind == "agent" or cap.startswith("agent.") or ".agent." in cap:
            agents.add(cap)
        else:
            tools.add(cap)
        meta = {}
        if catalog is not None:
            try:
                definition_cap = catalog.get(cap)
                meta = getattr(definition_cap, "metadata", None) or {}
            except Exception:  # noqa: BLE001
                meta = {}
        provider = str((meta or {}).get("mcp_server") or (meta or {}).get("mcpServer") or "")
        if provider or cap.startswith("mcp."):
            mcp_servers.add(provider or cap.split(".")[1] if cap.startswith("mcp.") else provider or cap)
    return {"tools": len(tools), "agents": len(agents), "mcp_servers": len(mcp_servers)}
