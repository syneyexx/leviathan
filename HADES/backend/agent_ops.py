"""Operational agent console: registry + live task/work/usage snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reasoning.specialists import SPECIALISTS, get_specialist


# Reserved for future agents that are seeded but not yet runnable.
# Implemented specialists must NOT appear here; SpecialistContract.planned_only is authoritative.
PLANNED_AGENT_IDS: frozenset[str] = frozenset()

STATUS_LABELS = {
    "idle": "Idle",
    "running": "Bezig",
    "busy": "Bezig",
    "error": "Fout",
    "disabled": "Uitgeschakeld",
    "unavailable": "Niet beschikbaar",
}

HEALTH_LABELS = {
    "healthy": "Healthy",
    "degraded": "Degraded",
    "error": "Error",
    "offline": "Offline",
}


def extract_usage(response: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize OpenAI-compatible usage blocks. Missing metrics stay null (never fake 0)."""
    if not isinstance(response, dict):
        return None
    raw = response.get("usage")
    if not isinstance(raw, dict) or not raw:
        return None

    def _int_or_none(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    prompt_details = raw.get("prompt_tokens_details") if isinstance(raw.get("prompt_tokens_details"), dict) else {}
    completion_details = raw.get("completion_tokens_details") if isinstance(raw.get("completion_tokens_details"), dict) else {}
    input_tokens = _int_or_none(raw.get("prompt_tokens") if "prompt_tokens" in raw else raw.get("input_tokens"))
    output_tokens = _int_or_none(raw.get("completion_tokens") if "completion_tokens" in raw else raw.get("output_tokens"))
    total_tokens = _int_or_none(raw.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    cached_tokens = _int_or_none(prompt_details.get("cached_tokens") if prompt_details else raw.get("cached_tokens"))
    reasoning_tokens = _int_or_none(
        completion_details.get("reasoning_tokens") if completion_details else raw.get("reasoning_tokens")
    )
    if all(value is None for value in (input_tokens, output_tokens, total_tokens, cached_tokens, reasoning_tokens)):
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cost": None,  # Local LM Studio does not provide billing; never invent costs.
    }


def _parse_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _duration_seconds(started: str | None, finished: str | None) -> float | None:
    start = _parse_ts(started)
    end = _parse_ts(finished)
    if start is None or end is None or end < start:
        return None
    return end - start


def is_planned_agent(agent_id: str, name: str = "", contract: Any | None = None) -> bool:
    """Contract.planned_only wins when a specialist exists; (*) is legacy UI marker only."""
    resolved = contract if contract is not None else get_specialist(agent_id)
    if resolved is not None:
        return bool(getattr(resolved, "planned_only", False))
    if agent_id in PLANNED_AGENT_IDS:
        return True
    if agent_id in SPECIALISTS:
        return bool(SPECIALISTS[agent_id].planned_only)
    return "(*)" in (name or "")


def display_name(name: str, planned: bool) -> str:
    cleaned = (name or "").strip()
    if planned and "(*)" not in cleaned:
        return f"{cleaned} (*)" if cleaned else "(*)"
    return cleaned


def empty_usage() -> dict[str, Any]:
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cached_tokens": None,
        "reasoning_tokens": None,
        "requests": 0,
        "cost": None,
        "known": False,
    }


def build_agent_console(
    *,
    agents: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    work_steps: list[dict[str, Any]],
    usage_by_agent: dict[str, dict[str, Any]],
    recent_events: list[dict[str, Any]],
    provider_connected: bool,
    active_profile: dict[str, Any] | None,
    provider_name: str = "LM Studio",
) -> dict[str, Any]:
    """Aggregate one batch snapshot for the Agents operations page."""
    profile = active_profile or {}
    active_model = profile.get("model_id") or None
    temperature = profile.get("temperature")
    top_p = profile.get("top_p")
    max_tokens = profile.get("max_tokens")

    tasks_by_id = {item["id"]: item for item in tasks}
    steps_by_agent: dict[str, list[dict[str, Any]]] = {}
    for step in work_steps:
        steps_by_agent.setdefault(str(step.get("agent_id") or ""), []).append(step)

    # Hierarchy from real work-step delegation (executor coordinates specialists).
    delegated_children: set[str] = set()
    for step in work_steps:
        agent_id = str(step.get("agent_id") or "")
        if agent_id and agent_id != "executor":
            delegated_children.add(agent_id)

    items: list[dict[str, Any]] = []
    activity: list[dict[str, Any]] = []

    for row in agents:
        agent_id = str(row["id"])
        contract = get_specialist(agent_id)
        planned = is_planned_agent(agent_id, str(row.get("name") or ""), contract)
        enabled = bool(row.get("enabled")) and not planned
        # Planned agents stay disabled in the console even if a DB row was flipped.
        if planned:
            enabled = False

        related_tasks = [task for task in tasks if str(task.get("agent") or "") == agent_id]
        related_steps = steps_by_agent.get(agent_id, [])

        running_steps = [step for step in related_steps if step.get("status") == "running"]
        running_tasks = [task for task in related_tasks if task.get("status") == "running"]
        # Also treat parent task as active when this agent has a running step.
        for step in running_steps:
            task = tasks_by_id.get(step.get("task_id"))
            if task and task not in running_tasks:
                running_tasks.append(task)

        queued_tasks = [task for task in related_tasks if task.get("status") == "queued"]
        queued_steps = [step for step in related_steps if step.get("status") == "queued"]
        failed_steps = [step for step in related_steps if step.get("status") == "failed"]
        failed_tasks = [task for task in related_tasks if task.get("status") == "failed"]
        completed_steps = [step for step in related_steps if step.get("status") == "completed"]
        completed_tasks = [task for task in related_tasks if task.get("status") == "completed"]

        primary_runs = related_tasks  # task-level ownership
        step_runs = related_steps
        successful_runs = len(completed_tasks) + len(completed_steps)
        failed_runs = len(failed_tasks) + len(failed_steps)
        total_runs = len(primary_runs) + len(step_runs)

        durations: list[float] = []
        for task in related_tasks:
            duration = _duration_seconds(task.get("started_at"), task.get("finished_at"))
            if duration is not None:
                durations.append(duration)
        for step in related_steps:
            # work_steps only have created/updated; use that when completed/failed.
            if step.get("status") in {"completed", "failed", "cancelled"}:
                duration = _duration_seconds(step.get("created_at"), step.get("updated_at"))
                if duration is not None:
                    durations.append(duration)
        avg_execution_seconds = (sum(durations) / len(durations)) if durations else None

        current_task = None
        current_step = None
        if running_steps:
            current_step = max(running_steps, key=lambda item: str(item.get("updated_at") or ""))
            current_task = tasks_by_id.get(current_step.get("task_id"))
        elif running_tasks:
            current_task = max(running_tasks, key=lambda item: str(item.get("updated_at") or ""))

        last_task = None
        finished_tasks = [task for task in related_tasks if task.get("finished_at")]
        if finished_tasks:
            last_task = max(finished_tasks, key=lambda item: str(item.get("finished_at") or ""))
        elif related_tasks:
            last_task = max(related_tasks, key=lambda item: str(item.get("updated_at") or ""))

        last_step = None
        if related_steps:
            last_step = max(related_steps, key=lambda item: str(item.get("updated_at") or ""))

        last_error = None
        error_candidates: list[tuple[str, str]] = []
        for task in failed_tasks:
            if task.get("error"):
                error_candidates.append((str(task.get("updated_at") or ""), str(task["error"])))
        for step in failed_steps:
            if step.get("error"):
                error_candidates.append((str(step.get("updated_at") or ""), str(step["error"])))
        if error_candidates:
            last_error = max(error_candidates, key=lambda item: item[0])[1]

        last_activity_at = None
        for candidate in (
            current_task.get("updated_at") if current_task else None,
            current_step.get("updated_at") if current_step else None,
            last_task.get("updated_at") if last_task else None,
            last_step.get("updated_at") if last_step else None,
            row.get("updated_at"),
        ):
            if candidate and (last_activity_at is None or str(candidate) > str(last_activity_at)):
                last_activity_at = candidate

        if planned:
            status = "unavailable"
            health = "offline"
        elif not enabled:
            status = "disabled"
            health = "offline"
        elif running_steps or running_tasks:
            status = "running" if len(running_steps) + len(running_tasks) == 1 else "busy"
            health = "healthy" if provider_connected or (contract and contract.deterministic) else "degraded"
        elif last_error and (failed_tasks or failed_steps) and not (completed_tasks or completed_steps):
            status = "error"
            health = "error"
        elif last_error and (
            (last_task and last_task.get("status") == "failed")
            or (last_step and last_step.get("status") == "failed")
        ):
            # Most recent finished activity failed.
            newest_fail = max(
                [str(item.get("updated_at") or "") for item in failed_tasks + failed_steps],
                default="",
            )
            newest_ok = max(
                [str(item.get("updated_at") or "") for item in completed_tasks + completed_steps],
                default="",
            )
            if newest_fail and newest_fail >= newest_ok:
                status = "error"
                health = "error"
            else:
                status = "idle"
                health = "healthy" if provider_connected or (contract and contract.deterministic) else "degraded"
        else:
            status = "idle"
            if contract and contract.deterministic:
                health = "healthy"
            elif not provider_connected:
                health = "degraded"
            else:
                health = "healthy"

        usage_row = usage_by_agent.get(agent_id) or empty_usage()
        usage = {
            **empty_usage(),
            **usage_row,
            "known": bool(usage_row.get("known")),
        }

        deterministic = bool(contract.deterministic) if contract else False
        provider = "local/deterministic" if deterministic else provider_name
        model = None if deterministic or planned else active_model

        capabilities = list(contract.capabilities) if contract else []
        tools = list(contract.allowed_tools) if contract else list(row.get("allowed_tools") or [])
        if tools == ["none"]:
            tools = []

        parent_id = "executor" if agent_id in delegated_children else None
        child_ids = sorted(delegated_children) if agent_id == "executor" else []

        current_payload = None
        if current_task or current_step:
            current_payload = {
                "task_id": current_task.get("id") if current_task else (current_step.get("task_id") if current_step else None),
                "task_title": current_task.get("title") if current_task else None,
                "step_id": current_step.get("id") if current_step else None,
                "step_title": current_step.get("title") if current_step else None,
                "step_index": current_step.get("step_index") if current_step else None,
                "started_at": (current_task or {}).get("started_at") or (current_step or {}).get("created_at"),
                "progress": current_task.get("progress") if current_task and current_task.get("status") == "running" else None,
                "parent_agent": "executor" if current_step and current_step.get("agent_id") != "executor" else None,
                "agent_id": agent_id,
            }

        last_payload = None
        if last_task or last_step:
            source = last_task or {}
            last_payload = {
                "task_id": source.get("id") if last_task else (last_step.get("task_id") if last_step else None),
                "task_title": source.get("title") if last_task else (last_step.get("title") if last_step else None),
                "status": (last_task or {}).get("status") or (last_step or {}).get("status"),
                "finished_at": (last_task or {}).get("finished_at") or (last_step or {}).get("updated_at"),
                "error": (last_task or {}).get("error") or (last_step or {}).get("error"),
            }

        controls = {
            "can_enable": (not planned) and (not enabled) and contract is not None,
            "can_disable": (not planned) and enabled and contract is not None,
            "can_cancel_current": bool(running_tasks or running_steps) and not planned,
            "can_refresh": True,
            "can_view_runs": total_runs > 0,
            "can_view_logs": total_runs > 0,
        }

        item = {
            "id": agent_id,
            "name": display_name(str(row.get("name") or agent_id), planned),
            "name_raw": row.get("name"),
            "role": row.get("role") or (contract.capabilities[0] if contract and contract.capabilities else "agent"),
            "type": row.get("role") or "agent",
            "description": row.get("description") or (contract.responsibility if contract else ""),
            "reasoning_profile": row.get("reasoning_profile") or (contract.model_profile if contract else None),
            "enabled": enabled,
            "planned": planned,
            "implemented": contract is not None and not planned,
            "available": enabled and not planned,
            "status": status,
            "status_label": STATUS_LABELS.get(status, status),
            "health": health,
            "health_label": HEALTH_LABELS.get(health, health),
            "provider": provider,
            "model": model,
            "model_settings": {
                "temperature": temperature if model else None,
                "top_p": top_p if model else None,
                "max_tokens": max_tokens if model else None,
                "context_window": None,
            },
            "capabilities": capabilities,
            "tools": tools,
            "allowed_tools": list(row.get("allowed_tools") or []),
            "max_subtasks": row.get("max_subtasks"),
            "permissions": {
                "tools_policy": "none" if tools == [] and contract and contract.allowed_tools == ["none"] else "shortlist",
                "deterministic": deterministic,
            },
            "current_task": current_payload,
            "last_task": last_payload,
            "last_activity_at": last_activity_at,
            "last_error": last_error,
            "queue": {
                "tasks": len(queued_tasks),
                "steps": len(queued_steps),
                "pending": len(queued_tasks) + len(queued_steps),
            },
            "metrics": {
                "requests": usage.get("requests") or 0,
                "runs": total_runs,
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "success_rate": (successful_runs / (successful_runs + failed_runs)) if (successful_runs + failed_runs) else None,
                "avg_execution_seconds": avg_execution_seconds,
            },
            "usage": usage,
            "hierarchy": {
                "parent_id": parent_id,
                "child_ids": child_ids,
            },
            "contract": contract.to_dict() if contract else None,
            "controls": controls,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "heartbeat_at": last_activity_at,
        }
        items.append(item)

    # Recent activity from durable task events + live step/task transitions.
    for event in recent_events[:40]:
        activity.append(
            {
                "at": event.get("created_at"),
                "agent_id": event.get("agent") or event.get("agent_id"),
                "task_id": event.get("task_id"),
                "level": event.get("level") or "info",
                "message": event.get("message") or "",
                "source": "task_event",
            }
        )
    for step in sorted(work_steps, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[:20]:
        task = tasks_by_id.get(step.get("task_id"))
        activity.append(
            {
                "at": step.get("updated_at"),
                "agent_id": step.get("agent_id"),
                "task_id": step.get("task_id"),
                "level": "error" if step.get("status") == "failed" else ("success" if step.get("status") == "completed" else "info"),
                "message": f"Stap '{step.get('title')}' · {step.get('status')}"
                + (f" · {task.get('title')}" if task else ""),
                "source": "work_step",
            }
        )
    activity.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    activity = activity[:50]

    enabled_count = sum(1 for item in items if item["enabled"])
    running_count = sum(1 for item in items if item["status"] in {"running", "busy"})
    planned_count = sum(1 for item in items if item["planned"])
    error_count = sum(1 for item in items if item["status"] == "error" or item["health"] == "error")
    known_usage_items = [item for item in items if item["usage"].get("known")]
    total_tokens = None
    total_cost = None
    if known_usage_items:
        token_values = [item["usage"].get("total_tokens") for item in known_usage_items if item["usage"].get("total_tokens") is not None]
        total_tokens = sum(token_values) if token_values else None
        cost_values = [item["usage"].get("cost") for item in known_usage_items if item["usage"].get("cost") is not None]
        total_cost = sum(cost_values) if cost_values else None

    open_queue = sum(item["queue"]["pending"] for item in items)
    success_rates = [item["metrics"]["success_rate"] for item in items if item["metrics"]["success_rate"] is not None]
    avg_success = (sum(success_rates) / len(success_rates)) if success_rates else None

    return {
        "items": items,
        "summary": {
            "total": len(items),
            "enabled": enabled_count,
            "running": running_count,
            "planned": planned_count,
            "errors": error_count,
            "open_queue": open_queue,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "avg_success_rate": avg_success,
            "provider_connected": provider_connected,
            "active_model": active_model,
            "provider": provider_name,
        },
        "activity": activity,
        "router": "specialist contracts + Work Runtime + task queue",
    }


def build_agent_detail(
    snapshot_item: dict[str, Any],
    *,
    tasks: list[dict[str, Any]],
    work_steps: list[dict[str, Any]],
    events: list[dict[str, Any]],
    usage_events: list[dict[str, Any]],
) -> dict[str, Any]:
    agent_id = snapshot_item["id"]
    related_tasks = [task for task in tasks if str(task.get("agent") or "") == agent_id][:30]
    related_steps = [step for step in work_steps if str(step.get("agent_id") or "") == agent_id][:40]
    recent_errors = []
    for task in related_tasks:
        if task.get("status") == "failed" and task.get("error"):
            recent_errors.append(
                {
                    "at": task.get("updated_at"),
                    "source": "task",
                    "id": task.get("id"),
                    "message": task.get("error"),
                }
            )
    for step in related_steps:
        if step.get("status") == "failed" and step.get("error"):
            recent_errors.append(
                {
                    "at": step.get("updated_at"),
                    "source": "work_step",
                    "id": step.get("id"),
                    "message": step.get("error"),
                }
            )
    recent_errors.sort(key=lambda item: str(item.get("at") or ""), reverse=True)

    runs = []
    for task in related_tasks:
        runs.append(
            {
                "id": task.get("id"),
                "kind": "task",
                "title": task.get("title"),
                "status": task.get("status"),
                "model_id": task.get("model_id"),
                "started_at": task.get("started_at"),
                "finished_at": task.get("finished_at"),
                "updated_at": task.get("updated_at"),
                "error": task.get("error"),
                "progress": task.get("progress"),
            }
        )
    for step in related_steps:
        runs.append(
            {
                "id": step.get("id"),
                "kind": "work_step",
                "title": step.get("title"),
                "status": step.get("status"),
                "task_id": step.get("task_id"),
                "started_at": step.get("created_at"),
                "finished_at": step.get("updated_at") if step.get("status") in {"completed", "failed", "cancelled"} else None,
                "updated_at": step.get("updated_at"),
                "error": step.get("error"),
                "progress": None,
            }
        )
    runs.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    return {
        **snapshot_item,
        "recent_runs": runs[:40],
        "recent_errors": recent_errors[:20],
        "recent_logs": events[:100],
        "usage_events": usage_events[:50],
        "configuration": {
            "reasoning_profile": snapshot_item.get("reasoning_profile"),
            "max_subtasks": snapshot_item.get("max_subtasks"),
            "allowed_tools": snapshot_item.get("allowed_tools"),
            "model": snapshot_item.get("model"),
            "provider": snapshot_item.get("provider"),
            "model_settings": snapshot_item.get("model_settings"),
            "enabled": snapshot_item.get("enabled"),
            "planned": snapshot_item.get("planned"),
        },
    }
