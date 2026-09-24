"""Auto-Plan adapter — structured task proposals via Model Control Plane."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .types import TaskAutoPlanProposal, TaskError


ModelCaller = Callable[..., dict[str, Any]]

_SYSTEM_PROMPT = """You are LEVIATHAN Task Planner.
Return ONLY valid JSON matching this schema (no markdown fences):
{
  "tasks": [
    {
      "title": "string",
      "description": "string",
      "priority": "high|medium|low",
      "suggested_assignee_id": "string or null",
      "tags": ["string"],
      "due_at": "ISO-8601 datetime or null",
      "dependencies": [0]
    }
  ]
}
Rules:
- dependencies are zero-based indices into the same tasks array (earlier tasks only).
- suggested_assignee_id MUST be null or one of the provided agent ids.
- Do not invent agent ids.
- Produce 2-8 concrete tasks unless the brief clearly needs fewer.
"""


class TaskPlannerAdapter:
    """Calls the canonical model caller (MCP-backed) for Auto-Plan."""

    def __init__(self, model_caller: ModelCaller | None = None) -> None:
        self.model_caller = model_caller

    def preview(
        self,
        *,
        brief: str,
        target_date: str | None = None,
        project: str | None = None,
        priority: str | None = None,
        allowed_agent_ids: list[str] | None = None,
        allowed_agents: list[dict[str, str]] | None = None,
    ) -> list[TaskAutoPlanProposal]:
        if self.model_caller is None:
            raise TaskError(
                "MODEL_UNAVAILABLE",
                "No model caller is configured for Auto-Plan",
                http_status=503,
            )
        brief = (brief or "").strip()
        if not brief:
            raise TaskError("INVALID_BRIEF", "Auto-Plan brief is required", http_status=422)

        agent_ids = set(allowed_agent_ids or [])
        agents_blob = json.dumps(allowed_agents or [], ensure_ascii=False)
        user_payload = {
            "brief": brief,
            "target_date": target_date,
            "project": project,
            "priority": priority,
            "allowed_agents": allowed_agents or [],
        }
        try:
            result = self.model_caller(
                system_prompt=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Plan tasks for this brief. Allowed agents JSON:\n"
                            f"{agents_blob}\n\nRequest:\n{json.dumps(user_payload, ensure_ascii=False)}"
                        ),
                    }
                ],
                role="planner",
                domain="chat",
                max_tokens=2500,
                job_class="INTERACTIVE",
            )
        except TaskError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TaskError(
                "MODEL_UNAVAILABLE",
                f"Auto-Plan model call failed: {exc}",
                http_status=503,
            ) from exc

        text = ""
        if isinstance(result, dict):
            text = str(result.get("content") or result.get("text") or result.get("output") or "")
            if not text and isinstance(result.get("message"), dict):
                text = str(result["message"].get("content") or "")
        if not text.strip():
            raise TaskError(
                "PLANNER_EMPTY",
                "Model returned an empty Auto-Plan response",
                http_status=503,
            )

        raw = self._parse_json(text)
        return self.validate_proposals(raw, allowed_agent_ids=agent_ids)

    def validate_proposals(
        self,
        raw: Any,
        *,
        allowed_agent_ids: set[str] | None = None,
    ) -> list[TaskAutoPlanProposal]:
        if not isinstance(raw, dict):
            raise TaskError("PLANNER_SCHEMA", "Auto-Plan payload must be an object", http_status=422)
        items = raw.get("tasks")
        if not isinstance(items, list) or not items:
            raise TaskError("PLANNER_SCHEMA", "Auto-Plan must include a non-empty tasks array", http_status=422)
        if len(items) > 20:
            raise TaskError("PLANNER_SCHEMA", "Auto-Plan exceeds maximum of 20 tasks", http_status=422)

        allowed = allowed_agent_ids or set()
        proposals: list[TaskAutoPlanProposal] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise TaskError("PLANNER_SCHEMA", f"Task proposal {idx} is not an object", http_status=422)
            title = str(item.get("title") or "").strip()
            if not title:
                raise TaskError("PLANNER_SCHEMA", f"Task proposal {idx} missing title", http_status=422)
            priority = str(item.get("priority") or "medium").strip().lower()
            if priority not in {"low", "medium", "high"}:
                raise TaskError("PLANNER_SCHEMA", f"Invalid priority on proposal {idx}", http_status=422)
            assignee = item.get("suggested_assignee_id") or item.get("suggestedAssigneeId")
            if assignee in ("", None):
                assignee = None
            else:
                assignee = str(assignee)
                if allowed and assignee not in allowed:
                    raise TaskError(
                        "INVALID_ASSIGNEE",
                        f"Suggested assignee is not in the allowed roster: {assignee}",
                        http_status=422,
                        details={"index": idx, "assignee": assignee},
                    )
            tags_raw = item.get("tags") or []
            if not isinstance(tags_raw, list):
                raise TaskError("PLANNER_SCHEMA", f"Tags must be a list on proposal {idx}", http_status=422)
            deps_raw = item.get("dependencies") or []
            if not isinstance(deps_raw, list):
                raise TaskError("PLANNER_SCHEMA", f"Dependencies must be a list on proposal {idx}", http_status=422)
            deps: list[int] = []
            for d in deps_raw:
                try:
                    di = int(d)
                except (TypeError, ValueError) as exc:
                    raise TaskError(
                        "PLANNER_SCHEMA",
                        f"Invalid dependency index on proposal {idx}",
                        http_status=422,
                    ) from exc
                if di < 0 or di >= len(items) or di >= idx:
                    raise TaskError(
                        "INVALID_DEPENDENCY",
                        f"Dependency index {di} on proposal {idx} is invalid (must reference an earlier task)",
                        http_status=422,
                    )
                deps.append(di)
            due_at = item.get("due_at") or item.get("dueAt")
            if due_at in ("", None):
                due_at = None
            else:
                due_at = str(due_at)
            proposals.append(
                TaskAutoPlanProposal(
                    title=title,
                    description=str(item.get("description") or ""),
                    priority=priority,
                    suggested_assignee_id=assignee,
                    tags=[str(t) for t in tags_raw],
                    due_at=due_at,
                    dependencies=deps,
                )
            )
        return proposals

    def _parse_json(self, text: str) -> Any:
        cleaned = text.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if fence:
            cleaned = fence.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise TaskError(
                        "PLANNER_SCHEMA",
                        f"Could not parse Auto-Plan JSON: {exc}",
                        http_status=422,
                    ) from exc
            raise TaskError("PLANNER_SCHEMA", "Could not parse Auto-Plan JSON", http_status=422)
