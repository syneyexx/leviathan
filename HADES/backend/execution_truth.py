"""Authoritative backend-owned execution and persistence truth.

LLM output is untrusted *intent* only. The model may propose tools, arguments,
plans, and requested next states. It must never authoritatively set:

- success / completed / executed / saved / persisted
- knowledge_updated / memory_updated / evidence_saved / result_saved
- tool_executed / task_completed / verification_passed

Only the runtime, repositories, and deterministic gates may set those values.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping

ToolExecutionStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "blocked",
    "cancelled",
]

RouteCompletionStatus = Literal[
    "completed",
    "partial",
    "failed",
    "blocked",
    "cancelled",
    "running",
    "finished_unchecked",
]

# Model-proposal fields that must never be copied into authoritative state.
MODEL_AUTHORITY_FIELDS = frozenset(
    {
        "success",
        "succeeded",
        "completed",
        "status",
        "executed",
        "saved",
        "persisted",
        "verified",
        "verification_passed",
        "knowledge_updated",
        "memory_updated",
        "evidence_saved",
        "result_saved",
        "tool_executed",
        "task_completed",
        "may_complete",
    }
)

_SUCCESS_CLAIM_RE = re.compile(
    r"("
    r"kennis(items?)?\s+(is\s+|zijn\s+)?(ge[uü]pdatet|bijgewerkt|opgeslagen|ge[iï]ndexeerd)|"
    r"\d+\s+kennis(items?)?\s+\w*\s*(opgeslagen|bijgewerkt|ge[uü]pdatet)|"
    r"knowledge[_\s-]?(updated|saved|ingested)|"
    r"memory[_\s-]?(updated|saved)|"
    r"geheugen\s+(is\s+)?(bijgewerkt|opgeslagen)|"
    r"(newsfeeder|plugin|tool)\s+(is\s+)?(gebruikt|uitgevoerd|aangeroepen)|"
    r"tool[_\s-]?executed|"
    r"status\s*[:=]\s*completed|"
    r"task[_\s-]?completed|"
    r"resultaat\s+(is\s+)?opgeslagen|"
    r"results?\s+(were\s+)?saved|"
    r"evidence[_\s-]?(saved|stored)|"
    r"bewijs\s+(is\s+)?opgeslagen"
    r")",
    flags=re.I,
)

_TOOL_SUCCESS_STATUSES = frozenset({"completed", "succeeded", "success", "ok", "succeeded"})
_TOOL_FAIL_STATUSES = frozenset({"failed", "error", "blocked", "denied", "cancelled", "canceled"})


class PersistenceVerificationError(RuntimeError):
    """Insert appeared to succeed but read-after-write verification failed."""


class ToolNotFoundError(LookupError):
    pass


class ToolPermissionError(PermissionError):
    pass


class ToolValidationError(ValueError):
    pass


class ToolExecutionError(RuntimeError):
    pass


class PersistenceError(RuntimeError):
    pass


class InvalidModelProposalError(ValueError):
    pass


class TaskTransitionError(RuntimeError):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utc_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class ToolExecutionResult:
    """Backend-owned tool execution record. Never instantiate as success from LLM JSON."""

    execution_id: str
    tool_id: str
    plugin_id: str = ""
    tool_name: str = ""
    status: ToolExecutionStatus = "queued"
    success: bool = False
    args: dict[str, Any] = field(default_factory=dict)
    validated_args: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    structured_result: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None
    permission_outcome: str | None = None
    execution_source: str = "plugin_manager"
    trace_id: str | None = None
    task_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PersistenceResult:
    """Backend-owned persistence outcome with mandatory read-after-write fields."""

    operation_id: str
    entity_type: str
    requested_count: int = 0
    inserted_count: int = 0
    inserted_ids: list[str] = field(default_factory=list)
    verified_count: int = 0
    success: bool = False
    verification_passed: bool = False
    error: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelActionProposal:
    """Untrusted model intent — never copy success fields into BackendExecutionState."""

    requested_tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    intended_action: str | None = None
    reasoning_summary: str | None = None
    requested_next_state: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BackendExecutionState:
    """Deterministic truth for one request/turn."""

    request_id: str
    chat_id: str | None = None
    task_id: str | None = None
    tool_executions: list[ToolExecutionResult] = field(default_factory=list)
    persistence_results: list[PersistenceResult] = field(default_factory=list)
    verification_called: bool = False
    verification_passed: bool | None = None
    verification_reason: str | None = None
    route_status: RouteCompletionStatus = "running"
    required_tools: bool = False
    required_persistence: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def emit(self, kind: str, **payload: Any) -> dict[str, Any]:
        event = {
            "kind": kind,
            "request_id": self.request_id,
            "chat_id": self.chat_id,
            "task_id": self.task_id,
            "ts_ms": utc_ms(),
            **payload,
        }
        self.events.append(event)
        return event

    @property
    def any_tool_executed(self) -> bool:
        return any(t.status not in {"queued"} for t in self.tool_executions)

    @property
    def any_tool_succeeded(self) -> bool:
        return any(t.success for t in self.tool_executions)

    @property
    def any_tool_failed(self) -> bool:
        return any(t.status in {"failed", "blocked", "cancelled"} for t in self.tool_executions)

    @property
    def persistence_verified(self) -> bool:
        if not self.persistence_results:
            return False
        return all(p.verification_passed and p.success for p in self.persistence_results)

    @property
    def saved_knowledge_count(self) -> int:
        return sum(
            int(p.verified_count)
            for p in self.persistence_results
            if p.entity_type == "knowledge" and p.verification_passed
        )

    @property
    def saved_memory_count(self) -> int:
        return sum(
            int(p.verified_count)
            for p in self.persistence_results
            if p.entity_type == "memory" and p.verification_passed
        )

    def grounding_context(self) -> dict[str, Any]:
        """Context the assistant may use — never invent success beyond this."""
        tools = []
        for t in self.tool_executions:
            tools.append(
                {
                    "tool": t.tool_id or f"{t.plugin_id}/{t.tool_name}",
                    "plugin_id": t.plugin_id,
                    "tool_name": t.tool_name,
                    "executed": t.status not in {"queued"},
                    "tool_success": bool(t.success),
                    "status": t.status,
                    "execution_id": t.execution_id,
                    "error": t.error_message,
                }
            )
        persistence = [p.to_dict() for p in self.persistence_results]
        return {
            "request_id": self.request_id,
            "executed": self.any_tool_executed,
            "tool_success": self.any_tool_succeeded,
            "tools": tools,
            "saved_count": self.saved_knowledge_count + self.saved_memory_count,
            "saved_knowledge_count": self.saved_knowledge_count,
            "saved_memory_count": self.saved_memory_count,
            "saved_ids": [
                iid
                for p in self.persistence_results
                if p.verification_passed
                for iid in p.inserted_ids
            ],
            "persistence_verified": self.persistence_verified if self.persistence_results else False,
            "persistence": persistence,
            "verification_called": self.verification_called,
            "verification_passed": self.verification_passed,
            "route_status": self.route_status,
            "notes": list(self.notes),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "chat_id": self.chat_id,
            "task_id": self.task_id,
            "tool_executions": [t.to_dict() for t in self.tool_executions],
            "persistence_results": [p.to_dict() for p in self.persistence_results],
            "verification_called": self.verification_called,
            "verification_passed": self.verification_passed,
            "verification_reason": self.verification_reason,
            "route_status": self.route_status,
            "required_tools": self.required_tools,
            "required_persistence": self.required_persistence,
            "events": list(self.events),
            "notes": list(self.notes),
            "grounding": self.grounding_context(),
        }


def strip_model_authority_fields(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove fields the model must not authoritatively define."""
    if not isinstance(payload, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        key_l = str(key).strip().lower()
        if key_l in MODEL_AUTHORITY_FIELDS:
            continue
        if isinstance(value, Mapping):
            out[str(key)] = strip_model_authority_fields(value)
        else:
            out[str(key)] = value
    return out


def parse_model_action_proposal(payload: Mapping[str, Any] | None) -> ModelActionProposal:
    """Treat model JSON as a proposal only; drop authoritative success fields."""
    raw = dict(payload or {})
    safe = strip_model_authority_fields(raw)
    requested = (
        safe.get("requested_tool")
        or safe.get("tool")
        or safe.get("tool_name")
        or safe.get("name")
    )
    args = safe.get("args") or safe.get("arguments") or {}
    if not isinstance(args, dict):
        args = {"value": args}
    return ModelActionProposal(
        requested_tool=str(requested).strip() if requested else None,
        args=dict(args),
        intended_action=str(safe.get("intended_action") or safe.get("action") or "") or None,
        reasoning_summary=str(safe.get("reasoning_summary") or safe.get("reason") or "") or None,
        requested_next_state=str(raw.get("status") or raw.get("requested_next_state") or "") or None,
        raw=safe,
    )


def _normalize_tool_status(raw_status: str | None, *, exit_code: Any = None, error: str | None = None) -> ToolExecutionStatus:
    status = str(raw_status or "").strip().lower()
    if status in {"blocked", "denied"}:
        return "blocked"
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    if status in {"running", "queued"}:
        return status  # type: ignore[return-value]
    if status in _TOOL_FAIL_STATUSES or error:
        return "failed"
    if exit_code not in (None, 0, "0") and status in _TOOL_SUCCESS_STATUSES | {""}:
        return "failed"
    if status in _TOOL_SUCCESS_STATUSES:
        return "succeeded"
    if status in {"partial"}:
        return "failed"
    return "failed"


def tool_execution_from_invoke(
    result: Mapping[str, Any] | None,
    *,
    plugin_id: str = "",
    tool_name: str = "",
    args: Mapping[str, Any] | None = None,
    execution_source: str = "plugin_manager",
    trace_id: str | None = None,
    task_id: str | None = None,
) -> ToolExecutionResult:
    """Build an authoritative ToolExecutionResult from a PluginManager/tool-engine result.

    Never trusts model-authored success fields inside nested JSON unless the runtime
    already normalized status/exit_code.
    """
    row = dict(result or {})
    # Ignore nested LLM claim keys if present in structured_output.
    structured = row.get("structured_output")
    if isinstance(structured, dict):
        if structured.get("success") is False:
            row["status"] = "failed"
            row["error"] = row.get("error") or "structured_output.success=false"
        structured = strip_model_authority_fields(structured)

    plugin = str(row.get("plugin_id") or plugin_id or "")
    name = str(row.get("tool_name") or row.get("tool") or tool_name or "")
    exit_code = row.get("exit_code")
    error = str(row.get("error") or "") or None
    status = _normalize_tool_status(str(row.get("status") or ""), exit_code=exit_code, error=error)
    success = status == "succeeded"
    execution_id = str(row.get("id") or row.get("call_id") or row.get("execution_id") or _new_id("tex"))
    permission = None
    if status == "blocked":
        permission = "blocked"
    elif row.get("approved_by_user") is True:
        permission = "approved"
    elif row.get("approved_by_user") is False:
        permission = "not_approved"

    return ToolExecutionResult(
        execution_id=execution_id,
        tool_id=f"{plugin}/{name}" if plugin or name else execution_id,
        plugin_id=plugin,
        tool_name=name,
        status=status,
        success=success,
        args=dict(args or row.get("input") or {}),
        validated_args=dict(row.get("validated_args") or args or row.get("input") or {}),
        output=str(row.get("output") or "")[:50_000],
        stdout=str(row.get("stdout") or "")[:50_000],
        stderr=str(row.get("stderr") or "")[:50_000],
        exit_code=int(exit_code) if exit_code not in (None, "") else None,
        structured_result=structured if isinstance(structured, dict) else None,
        error_type="ToolExecutionError" if status == "failed" else ("ToolPermissionError" if status == "blocked" else None),
        error_message=error,
        permission_outcome=permission,
        execution_source=execution_source,
        trace_id=trace_id,
        task_id=task_id or (str(row.get("task_id")) if row.get("task_id") else None),
        started_at=str(row.get("started_at") or "") or None,
        finished_at=str(row.get("finished_at") or "") or None,
        duration_ms=int(row["duration_ms"]) if row.get("duration_ms") not in (None, "") else None,
    )


def collect_tool_executions(tool_log: list[Mapping[str, Any]] | None, **kwargs: Any) -> list[ToolExecutionResult]:
    return [tool_execution_from_invoke(item, **kwargs) for item in (tool_log or [])]


def make_persistence_result(
    *,
    entity_type: str,
    requested_count: int,
    inserted_ids: list[str] | None = None,
    verified_ids: list[str] | None = None,
    error: str | None = None,
    error_type: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    operation_id: str | None = None,
) -> PersistenceResult:
    inserted = list(inserted_ids or [])
    verified = list(verified_ids or [])
    verification_passed = (
        error is None
        and requested_count >= 0
        and len(verified) == len(inserted)
        and (requested_count == 0 or len(verified) >= min(requested_count, len(inserted)))
        and (len(inserted) > 0 or requested_count == 0)
    )
    # Empty intentional write (requested 0) can verify as success with 0 ids.
    if requested_count == 0 and error is None and not inserted:
        verification_passed = True
    success = verification_passed and error is None
    if error and not error_type:
        error_type = "PersistenceError"
    if not verification_passed and not error:
        error = "read_after_write_verification_failed"
        error_type = "PersistenceVerificationError"
        success = False
    return PersistenceResult(
        operation_id=operation_id or _new_id("pers"),
        entity_type=entity_type,
        requested_count=int(requested_count),
        inserted_count=len(inserted),
        inserted_ids=inserted,
        verified_count=len(verified),
        success=success,
        verification_passed=verification_passed,
        error=error,
        error_type=error_type,
        metadata=dict(metadata or {}),
    )


def verify_rows_exist(
    *,
    entity_type: str,
    ids: list[str],
    fetch_one,
    required_fields: list[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PersistenceResult:
    """Commit is assumed done by the repository; this only verifies read-back."""
    verified: list[str] = []
    missing: list[str] = []
    required = list(required_fields or [])
    try:
        for item_id in ids:
            row = fetch_one(item_id)
            if not row:
                missing.append(item_id)
                continue
            if any(not row.get(field) and row.get(field) != 0 for field in required):
                missing.append(item_id)
                continue
            verified.append(item_id)
        error = None
        error_type = None
        if missing:
            error = f"missing_or_invalid_after_write:{missing[:5]}"
            error_type = "PersistenceVerificationError"
        return make_persistence_result(
            entity_type=entity_type,
            requested_count=len(ids),
            inserted_ids=list(ids),
            verified_ids=verified,
            error=error,
            error_type=error_type,
            metadata={**(metadata or {}), "missing_ids": missing},
        )
    except Exception as exc:
        return make_persistence_result(
            entity_type=entity_type,
            requested_count=len(ids),
            inserted_ids=list(ids),
            verified_ids=verified,
            error=str(exc),
            error_type=type(exc).__name__,
            metadata=dict(metadata or {}),
        )


def decide_route_completion(
    *,
    verification_called: bool,
    verification_allowed: bool | None,
    tool_executions: list[ToolExecutionResult] | None = None,
    persistence_results: list[PersistenceResult] | None = None,
    required_tools: bool = False,
    required_persistence: bool = False,
    cancelled: bool = False,
) -> tuple[RouteCompletionStatus, str]:
    """Deterministic chat/route completion — LLM cannot force completed."""
    if cancelled:
        return "cancelled", "cancelled"
    tools = list(tool_executions or [])
    persistence = list(persistence_results or [])

    if required_tools and not any(t.success for t in tools):
        if any(t.status == "blocked" for t in tools):
            return "blocked", "required_tool_blocked"
        return "failed", "required_tool_not_succeeded"
    if any(t.status == "failed" for t in tools) and required_tools:
        return "failed", "required_tool_failed"
    if required_persistence:
        if not persistence:
            return "failed", "required_persistence_missing"
        if not all(p.verification_passed and p.success for p in persistence):
            return "failed", "persistence_verification_failed"
    if persistence and any(not p.success for p in persistence):
        return "failed", "persistence_failed"

    if verification_called:
        if verification_allowed is True:
            return "completed", "verification_passed"
        if verification_allowed is False:
            return "partial", "verification_failed"
        return "partial", "verification_inconclusive"

    # No verification: never claim verified completion when tools/persistence were in play.
    if tools or persistence or required_tools or required_persistence:
        return "finished_unchecked", "finished_without_verification"
    return "finished_unchecked", "no_verification_required"


def message_claims_success(text: str) -> bool:
    return bool(_SUCCESS_CLAIM_RE.search(text or ""))


def ground_assistant_message(content: str, state: BackendExecutionState) -> tuple[str, list[str]]:
    """Ensure user-visible text cannot claim unverified tool/persistence success.

    Does not invent success. When the draft claims success without backend proof,
    append an authoritative truth note and keep the draft marked unverified.
    """
    notes: list[str] = []
    text = content or ""
    grounding = state.grounding_context()
    claims = message_claims_success(text)
    if not claims:
        return text, notes

    problems: list[str] = []
    lower = text.lower()
    knowledge_claim = bool(
        re.search(r"kennis|knowledge", lower)
        and re.search(r"ge[uü]pdatet|bijgewerkt|opgeslagen|updated|saved|ingested", lower)
    )
    tool_claim = bool(
        re.search(r"newsfeeder|plugin|tool|gebruikt|uitgevoerd|tool_executed", lower)
    )
    memory_claim = bool(re.search(r"memory|geheugen", lower) and re.search(r"updated|bijgewerkt|opgeslagen|saved", lower))

    if tool_claim and not grounding.get("executed"):
        problems.append("Geen tool-uitvoering vastgelegd door de runtime.")
    if tool_claim and grounding.get("executed") and not grounding.get("tool_success"):
        problems.append("Tool-uitvoering is niet geslaagd volgens de runtime.")
    if knowledge_claim and int(grounding.get("saved_knowledge_count") or 0) <= 0:
        problems.append("Geen geverifieerde kennispersistentie (0 items).")
    if memory_claim and int(grounding.get("saved_memory_count") or 0) <= 0:
        problems.append("Geen geverifieerde geheugenpersistentie (0 items).")
    if re.search(r"status\s*[:=]\s*completed|task_completed|voltooid", lower) and state.route_status not in {
        "completed",
    }:
        problems.append(f"Backend-status is '{state.route_status}', niet completed.")

    if not problems:
        notes.append("claims_aligned_with_execution_truth")
        return text, notes

    notes.append("ungrounded_success_claims_stripped")
    truth_lines = [
        "---",
        "HADES runtime-waarheid (autoritatief — niet modeltekst):",
        f"- tools uitgevoerd: {'ja' if grounding.get('executed') else 'nee'}",
        f"- tool succes: {'ja' if grounding.get('tool_success') else 'nee'}",
        f"- kennis opgeslagen (geverifieerd): {grounding.get('saved_knowledge_count', 0)}",
        f"- geheugen opgeslagen (geverifieerd): {grounding.get('saved_memory_count', 0)}",
        f"- persistentie geverifieerd: {'ja' if grounding.get('persistence_verified') else 'nee'}",
        f"- routestatus: {state.route_status}",
    ]
    for problem in problems:
        truth_lines.append(f"- correctie: {problem}")
    truth_lines.append(
        "Claims over uitvoering of opslag zonder bovenstaande runtime-bevestiging zijn ongeldig."
    )
    return f"{text.rstrip()}\n\n" + "\n".join(truth_lines), notes


def build_execution_result_artifact_payload(state: BackendExecutionState) -> dict[str, Any]:
    """Structured Results-panel payload from backend truth only."""
    return {
        "schema": "hades.execution_result.v1",
        "request_id": state.request_id,
        "chat_id": state.chat_id,
        "task_id": state.task_id,
        "route_status": state.route_status,
        "tools": [t.to_dict() for t in state.tool_executions],
        "persistence": [p.to_dict() for p in state.persistence_results],
        "grounding": state.grounding_context(),
        "events": list(state.events),
        "notes": list(state.notes),
    }


def resolve_sqlite_paths(*, database_path: str, data_root: str | None = None) -> dict[str, str]:
    """Deterministic path diagnostics for startup logs."""
    from pathlib import Path

    db = Path(database_path).expanduser().resolve()
    root = Path(data_root).expanduser().resolve() if data_root else db.parent
    return {
        "sqlite_path": str(db),
        "data_root": str(root),
        "embedding_index": str(root / "embedding_index.sqlite3"),
        "artifacts_root": str(root / "artifacts"),
        "knowledge_raw": str(root / "knowledge" / "raw"),
        "evidence_web": str(root / "evidence" / "web"),
    }


def format_db_startup_log(paths: Mapping[str, str]) -> str:
    return f"[DB] SQLite path: {paths.get('sqlite_path')}"
