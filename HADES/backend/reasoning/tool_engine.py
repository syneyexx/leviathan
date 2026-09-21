"""Shared tool execution engine for Chat / Work / Agents.

Native OpenAI-compatible tools are primary; text ``hades_tool_call`` is a
controlled fallback. All executions go through PluginManager after policy checks.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from .atomic_budget import BudgetExhausted, shared_budget_pool
from .orchestration import finalize_without_tool_json
from .steering import action_fingerprint, classify_tool_signal, next_steering_action
from .tool_capability import ToolsUnsupportedError
from .tool_protocol import (
    ClassifiedResponse,
    NormalizedToolCall,
    ResponseState,
    ToolCallMode,
    assistant_tool_call_message,
    classify_model_response,
    encode_provider_function_name,
    strip_raw_tool_protocol,
    tool_result_message,
)
from .tool_registry import build_native_tools_payload, resolve_tool_row, validate_against_schema
from .tools import (
    DISCOVER_PLUGIN_ID,
    DISCOVER_TOOL_ALIASES,
    DISCOVER_TOOL_NAME,
    render_tool_catalog,
)

ChatFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
EmitFn = Callable[[str | None, dict[str, Any]], Awaitable[None]]
PermissionFn = Callable[[dict[str, Any], dict[str, Any]], None]
InvokeFn = Callable[..., Any]
DiscoverFn = Callable[..., dict[str, Any]]
RejectFn = Callable[..., dict[str, Any]]
ApprovalFn = Callable[..., dict[str, Any]]

_DISCOVER_PROVIDER_NAMES = {
    encode_provider_function_name(DISCOVER_PLUGIN_ID, name) for name in DISCOVER_TOOL_ALIASES
}


def _is_discover_call(call: NormalizedToolCall) -> bool:
    if call.provider_function_name in _DISCOVER_PROVIDER_NAMES:
        return True
    if call.plugin_id != DISCOVER_PLUGIN_ID:
        return False
    # Native decode sanitizes '.' → '_' so accept both forms.
    candidates = set(DISCOVER_TOOL_ALIASES)
    candidates.update(name.replace(".", "_") for name in DISCOVER_TOOL_ALIASES)
    return call.tool_name in candidates


@dataclass
class ToolEngineConfig:
    autonomous: bool = True
    max_rounds: int | None = 3
    max_model_calls: int | None = 20
    tool_call_mode: ToolCallMode = "native"
    tool_result_max_chars: int | None = 30_000
    allow_text_fallback: bool = True
    max_empty_recoveries: int = 1
    # None = Unlimited concurrent PluginManager invokes within one model turn.
    max_parallel_tool_calls: int | None = 4
    selected_mode: str = ""
    profile_name: str = "fast"
    plugin_directory: str = ""
    tools_offered: list[str] = field(default_factory=list)


@dataclass
class ToolEngineResult:
    content: str
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    model_calls: int = 0
    tool_call_mode: ToolCallMode = "native"
    response_states: list[str] = field(default_factory=list)
    usage_events: list[dict[str, Any]] = field(default_factory=list)
    tools_offered: list[str] = field(default_factory=list)


def observation_payload(result: dict[str, Any], *, limit: int | None) -> str:
    from .tool_observation_budget import observation_payload_json

    return observation_payload_json(result, limit=limit)


def normalize_tool_result_status(result: dict[str, Any]) -> dict[str, Any]:
    """Anti-false-success normalization for tool results.

    Model-authored nested claim fields (knowledge_updated, etc.) never force success.
    """
    row = dict(result)
    status = str(row.get("status") or "unknown")
    exit_code = row.get("exit_code")
    if status == "completed" and exit_code not in (None, 0, "0"):
        row["status"] = "failed"
        row["error"] = row.get("error") or f"exit_code={exit_code}"
    structured = row.get("structured_output")
    if isinstance(structured, dict):
        if structured.get("success") is False and status == "completed":
            row["status"] = "failed"
            row["error"] = row.get("error") or "structured_output.success=false"
        # Strip untrusted authority fields so callers cannot treat them as runtime truth.
        try:
            from execution_truth import strip_model_authority_fields

            row["structured_output"] = strip_model_authority_fields(structured)
        except Exception:
            pass
    return row


async def _invoke_selected_tool(
    *,
    call: NormalizedToolCall,
    selected: dict[str, Any],
    call_mode: ToolCallMode,
    invoke: InvokeFn,
    enforce_permissions: PermissionFn | None,
    record_rejected: RejectFn | None,
    create_approval: ApprovalFn | None,
    emit_tool: EmitFn | None,
    run_id: str | None,
    tool_result_max_chars: int | None,
    started: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute one validated tool via PluginManager (or blocked/approval path)."""
    if emit_tool:
        await emit_tool(
            run_id,
            {
                "call_id": call.call_id,
                "plugin_id": selected["plugin_id"],
                "tool_name": selected["name"],
                "status": "running",
                "tool_call_mode": call_mode,
            },
        )

    result: dict[str, Any]
    try:
        # A09 — G11/G8 shared enforcement before any side effect.
        try:
            from policy_enforcement import enforce_tool_invocation_policies

            settings = {}
            try:
                # Optional settings callback attached on invoke closure / selected metadata.
                settings = dict((selected.get("plugin") or {}).get("_runtime_settings") or {})
            except Exception:
                settings = {}
            is_mcp = bool(
                (selected.get("metadata") or {}).get("mcp")
                or (selected.get("metadata") or {}).get("mcp_remote")
                or (selected.get("metadata") or {}).get("mcp_managed")
                or str(selected.get("name") or "").startswith("mcp.")
                or str(selected.get("name") or "").startswith("mcp__")
                or "mcp" in str((selected.get("plugin") or {}).get("plugin_type") or "").lower()
            )
            policy = enforce_tool_invocation_policies(
                tool_name=str(selected.get("name") or call.tool_name or ""),
                arguments=call.arguments,
                settings=settings,
                source="tool_engine",
                is_mcp_tool=is_mcp,
            )
            if not policy.get("allowed"):
                message = f"Policy blocked tool call: {policy.get('reason')}"
                if record_rejected is not None:
                    result = record_rejected(
                        selected["plugin_id"],
                        selected["name"],
                        call.arguments,
                        status="blocked",
                        error=message,
                    )
                else:
                    result = {
                        "id": call.call_id,
                        "status": "blocked",
                        "error": message,
                        "exit_code": None,
                        "invocation_type": "autonomous",
                        "policy": policy,
                    }
                result = normalize_tool_result_status(result)
                tool_row = {
                    "call_id": call.call_id,
                    "plugin_id": selected["plugin_id"],
                    "tool_name": selected["name"],
                    "provider_function_name": call.provider_function_name,
                    "status": result.get("status") or "blocked",
                    "error": result.get("error") or message,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "tool_call_mode": call_mode,
                    "policy": policy,
                }
                content = json.dumps(
                    {"status": "blocked", "error": message, "policy": {"reason": policy.get("reason"), "defenses": policy.get("defenses")}},
                    ensure_ascii=False,
                )
                if tool_result_max_chars is not None:
                    content = content[: int(tool_result_max_chars)]
                return tool_row, tool_result_message(call_id=call.call_id, content=content, mode=call_mode)
            if policy.get("args") is not None:
                call.arguments = policy["args"]
        except ImportError as exc:
            message = f"Policy module unavailable (fail-closed): {exc}"
            if record_rejected is not None:
                result = record_rejected(
                    selected["plugin_id"],
                    selected["name"],
                    call.arguments,
                    status="blocked",
                    error=message,
                )
            else:
                result = {
                    "status": "blocked",
                    "error": message,
                    "plugin_id": selected["plugin_id"],
                    "tool_name": selected["name"],
                }
            tool_row = {
                "call_id": call.call_id,
                "plugin_id": selected["plugin_id"],
                "tool_name": selected["name"],
                "status": "blocked",
                "error": message,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "tool_call_mode": call_mode,
            }
            content = json.dumps({"status": "blocked", "error": message, "failure_class": "POLICY_BLOCK"}, ensure_ascii=False)
            if tool_result_max_chars is not None:
                content = content[: int(tool_result_max_chars)]
            return tool_row, tool_result_message(call_id=call.call_id, content=content, mode=call_mode)

        if enforce_permissions is not None:
            enforce_permissions(selected["plugin"], selected)
    except PermissionError as exc:
        message = str(exc)
        if "expliciete goedkeuring" in message.lower() and record_rejected is not None:
            request = None
            if create_approval is not None:
                request = create_approval(
                    plugin_id=selected["plugin_id"],
                    tool_name=selected["name"],
                    arguments=call.arguments,
                )
            result = record_rejected(
                selected["plugin_id"],
                selected["name"],
                call.arguments,
                status="approval_required",
                error=message,
            )
            if request:
                result = {**result, "approval_request_id": request.get("id")}
        elif record_rejected is not None:
            result = record_rejected(
                selected["plugin_id"],
                selected["name"],
                call.arguments,
                status="blocked",
                error=message,
            )
        else:
            result = {
                "id": call.call_id,
                "status": "blocked",
                "error": message,
                "exit_code": None,
                "invocation_type": "autonomous",
            }
    else:
        result = await asyncio.to_thread(
            invoke,
            selected["plugin_id"],
            selected["name"],
            call.arguments,
        )
        if asyncio.iscoroutine(result):
            result = await result
        if not isinstance(result, dict):
            result = {
                "id": call.call_id,
                "status": "failed",
                "error": "PluginManager gaf geen dict-resultaat terug.",
                "exit_code": None,
                "invocation_type": "autonomous",
            }

    result = normalize_tool_result_status(result)
    tool_row = {
        "call_id": result.get("id") or call.call_id,
        "plugin_id": selected["plugin_id"],
        "tool_name": selected["name"],
        "provider_function_name": call.provider_function_name,
        "status": result.get("status"),
        "error": result.get("error"),
        "reason_code": result.get("reason_code") or (result.get("metadata") or {}).get("reason_code"),
        "exit_code": result.get("exit_code"),
        "invocation_type": result.get("invocation_type", "autonomous"),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "tool_call_mode": call_mode,
        "mcp_remote": bool((selected.get("metadata") or {}).get("mcp_remote")),
    }
    result_msg = tool_result_message(
        call_id=call.call_id,
        content=observation_payload(result, limit=tool_result_max_chars),
        mode=call_mode,
    )
    return tool_row, result_msg


async def run_tool_engine(
    *,
    messages: list[dict[str, Any]],
    query: str,
    tools: list[dict[str, Any]],
    chat: ChatFn,
    build_payload: Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], dict[str, Any]],
    invoke: InvokeFn,
    discover: DiscoverFn | None = None,
    hydrate_discovered: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    enforce_permissions: PermissionFn | None = None,
    record_rejected: RejectFn | None = None,
    create_approval: ApprovalFn | None = None,
    emit_tool: EmitFn | None = None,
    on_usage: Callable[[dict[str, Any]], None] | None = None,
    config: ToolEngineConfig | None = None,
    run_id: str | None = None,
    execution_budget: Any | None = None,
) -> ToolEngineResult:
    cfg = config or ToolEngineConfig()
    if len(tools) > 8:
        try:
            from hades_brain.tool_context import bound_tools_for_model

            tools = list(bound_tools_for_model(tools, query=query).get("tools") or tools[:8])
        except Exception:
            tools = list(tools[:8])
    tool_log: list[dict[str, Any]] = []
    response_states: list[str] = []
    usage_events: list[dict[str, Any]] = []
    offered = list(cfg.tools_offered or [])

    def _result(**kwargs: Any) -> ToolEngineResult:
        kwargs.setdefault("tools_offered", offered)
        return ToolEngineResult(**kwargs)

    base_messages: list[dict[str, Any]] = [dict(item) for item in messages]
    model_calls = 0
    empty_recoveries = 0
    mode: ToolCallMode = cfg.tool_call_mode
    catalog_text = render_tool_catalog(
        [
            {
                "plugin_id": item["plugin_id"],
                "plugin": (item.get("plugin") or {}).get("name", item["plugin_id"]),
                "category": (item.get("plugin") or {}).get("category", "Tool"),
                "tool_name": item["name"],
                "description": item.get("description", ""),
                "input_schema": item.get("input_schema", {}),
                "action": (item.get("metadata") or {}).get("action", item["name"]),
            }
            for item in tools
        ],
        include_discover_hint=True,
    ) if cfg.autonomous and tools else (
        render_tool_catalog([], include_discover_hint=True) if cfg.autonomous else ""
    )
    directory_text = (cfg.plugin_directory or "").strip()

    round_index = -1
    failed_fingerprints: dict[str, int] = {}
    while True:
        round_index += 1
        if cfg.max_rounds is not None and round_index > int(cfg.max_rounds):
            break
        # Respect shared ExecutionBudget, including reserved verification/finalize calls.
        if execution_budget is not None and hasattr(execution_budget, "can_model_call"):
            reserve = bool(getattr(execution_budget, "reserved_verification_calls", 0))
            if not execution_budget.can_model_call(reserve_verification=reserve):
                return _result(
                    content=finalize_without_tool_json(
                        "",
                        reason="Modelcall-budget bereikt (verificatiereserve gerespecteerd).",
                    ),
                    tool_log=tool_log,
                    model_calls=model_calls,
                    tool_call_mode=mode,
                    response_states=response_states,
                    usage_events=usage_events,
                )
        elif cfg.max_model_calls is not None and model_calls >= int(cfg.max_model_calls):
            return _result(
                content=finalize_without_tool_json(
                    "",
                    reason=f"Modelcall-budget ({cfg.max_model_calls}) is bereikt.",
                ),
                tool_log=tool_log,
                model_calls=model_calls,
                tool_call_mode=mode,
                response_states=response_states,
                usage_events=usage_events,
            )

        turn_messages = list(base_messages)
        # Text-fallback mode still needs the catalog; native mode uses schemas.
        use_native = mode == "native" and cfg.autonomous and (cfg.max_rounds is None or cfg.max_rounds > 0)
        native_tools = build_native_tools_payload(tools, query=query) if use_native else None
        prefix: list[dict[str, Any]] = []
        tools_open = cfg.max_rounds is None or cfg.max_rounds > 0
        if directory_text and cfg.autonomous and tools_open:
            prefix.append({"role": "system", "content": directory_text})
        if catalog_text and not use_native and tools_open:
            prefix.append({"role": "system", "content": catalog_text})
        if prefix:
            turn_messages = prefix + turn_messages

        payload = build_payload(turn_messages, native_tools)
        if isinstance(payload, dict) and payload.get("_provider_overflow"):
            return _result(
                content=finalize_without_tool_json(
                    "",
                    reason="Provider-request past niet binnen modelcontextbudget (overflow vóór call).",
                ),
                tool_log=tool_log,
                model_calls=model_calls,
                tool_call_mode=mode,
                response_states=[*response_states, "provider_overflow"],
                usage_events=usage_events,
            )
        try:
            if execution_budget is not None:
                try:
                    shared_budget_pool.lease("model", 1)
                    execution_budget.leased_model_calls = int(getattr(execution_budget, "leased_model_calls", 0) or 0) + 1
                except BudgetExhausted:
                    return _result(
                        content=finalize_without_tool_json(
                            "",
                            reason="Gedeeld modelbudget uitgeput vóór de call.",
                        ),
                        tool_log=tool_log,
                        model_calls=model_calls,
                        tool_call_mode=mode,
                        response_states=[*response_states, "shared_budget_exhausted"],
                        usage_events=usage_events,
                    )
            response = await chat(payload)
        except ToolsUnsupportedError:
            # Provider rejected native tools — controlled text fallback for remaining rounds.
            mode = "text_fallback"
            use_native = False
            native_tools = None
            turn_messages = list(base_messages)
            prefix = []
            tools_open = cfg.max_rounds is None or cfg.max_rounds > 0
            if directory_text and cfg.autonomous and tools_open:
                prefix.append({"role": "system", "content": directory_text})
            if catalog_text and tools_open:
                prefix.append({"role": "system", "content": catalog_text})
            if prefix:
                turn_messages = prefix + turn_messages
            payload = build_payload(turn_messages, None)
            if isinstance(payload, dict) and payload.get("_provider_overflow"):
                return _result(
                    content=finalize_without_tool_json(
                        "",
                        reason="Provider-request past niet binnen modelcontextbudget (overflow vóór call).",
                    ),
                    tool_log=tool_log,
                    model_calls=model_calls,
                    tool_call_mode=mode,
                    response_states=[*response_states, "provider_overflow"],
                    usage_events=usage_events,
                )
            response = await chat(payload)
        except Exception:
            if execution_budget is not None:
                try:
                    shared_budget_pool.release_lease("model", 1)
                except Exception:
                    pass
                execution_budget.leased_model_calls = max(0, int(getattr(execution_budget, "leased_model_calls", 0) or 0) - 1)
            raise
        model_calls += 1
        if execution_budget is not None:
            try:
                shared_budget_pool.commit_lease("model", 1)
            except Exception:
                pass
            execution_budget.leased_model_calls = max(0, int(getattr(execution_budget, "leased_model_calls", 0) or 0) - 1)
            execution_budget.record_model_call()
            usage = response.get("usage") if isinstance(response, dict) and isinstance(response.get("usage"), dict) else None
            estimated = None
            if usage is None:
                try:
                    from reasoning.usage_telemetry import estimate_usage_from_response

                    estimated = estimate_usage_from_response(response if isinstance(response, dict) else None)
                except Exception:
                    estimated = None
            if hasattr(execution_budget, "apply_provider_usage"):
                execution_budget.apply_provider_usage(usage, estimated=estimated)

        classified = classify_model_response(
            response,
            allow_text_fallback=cfg.allow_text_fallback and cfg.autonomous,
        )
        response_states.append(classified.state.value)
        if classified.mode in {"native", "text_fallback"}:
            mode = classified.mode
        if classified.usage and on_usage:
            on_usage(classified.usage)
            usage_events.append(dict(classified.usage))

        if classified.state == ResponseState.FINAL_CONTENT:
            return _result(
                content=strip_raw_tool_protocol(classified.content or ""),
                tool_log=tool_log,
                model_calls=model_calls,
                tool_call_mode=mode,
                response_states=response_states,
                usage_events=usage_events,
            )

        if classified.state in {ResponseState.EMPTY_FATAL, ResponseState.PROVIDER_ERROR, ResponseState.CANCELLED}:
            raise RuntimeError(classified.error or "Het model gaf een leeg resultaat terug.")

        if classified.state == ResponseState.EMPTY_RECOVERABLE:
            empty_recoveries += 1
            if empty_recoveries > cfg.max_empty_recoveries:
                raise RuntimeError(classified.error or "Lege modelrespons na recovery.")
            base_messages = list(base_messages) + [
                {
                    "role": "system",
                    "content": "Vorige modelrespons was leeg/afgekapt. Geef nu een volledig eindantwoord of een geldige toolcall.",
                }
            ]
            continue

        # TOOL_CALLS
        can_run_tools = cfg.autonomous and (cfg.max_rounds is None or (cfg.max_rounds > 0 and round_index < cfg.max_rounds))
        if execution_budget is not None:
            can_run_tools = can_run_tools and execution_budget.can_tool_round()
        if not can_run_tools:
            return _result(
                content=finalize_without_tool_json(
                    classified.content or "",
                    reason=f"Toolrondes uitgeput ({cfg.max_rounds}) of niet toegestaan.",
                    had_tool_request=True,
                ),
                tool_log=tool_log,
                model_calls=model_calls,
                tool_call_mode=mode,
                response_states=response_states,
                usage_events=usage_events,
            )

        if execution_budget is not None:
            execution_budget.record_tool_round()

        call_mode: ToolCallMode = classified.mode if classified.mode in {"native", "text_fallback"} else mode
        # Persist successful native round for capability cache callers via mode.
        if call_mode == "native":
            mode = "native"
        assistant_msg = assistant_tool_call_message(
            content=classified.content,
            tool_calls=classified.tool_calls,
            mode=call_mode,
        )
        # Preserve provider tool_call order; fill slots as validations/invokes complete.
        result_slots: list[dict[str, Any] | None] = [None] * len(classified.tool_calls)
        log_slots: list[dict[str, Any] | None] = [None] * len(classified.tool_calls)
        pending_invokes: list[tuple[int, NormalizedToolCall, dict[str, Any], float]] = []

        for index, call in enumerate(classified.tool_calls):
            started = time.perf_counter()
            if _is_discover_call(call) and discover is not None:
                page = discover(
                    str((call.arguments or {}).get("query") or query),
                    limit=min(20, int((call.arguments or {}).get("limit") or 8)),
                    offset=max(0, int((call.arguments or {}).get("offset") or 0)),
                    category=str(call.arguments["category"]) if call.arguments.get("category") else None,
                )
                # Architecture invariant: discovery returns observations only.
                # Do NOT hydrate plugin/MCP schemas into the model-visible tool set.
                # Dynamic execution goes through hades.capabilities.invoke.
                _ = hydrate_discovered  # retained for call-site compatibility; unused
                discovery_row = {
                    "call_id": call.call_id,
                    "plugin_id": DISCOVER_PLUGIN_ID,
                    "tool_name": str(call.tool_name or DISCOVER_TOOL_NAME),
                    "provider_function_name": call.provider_function_name,
                    "status": "completed",
                    "error": None,
                    "exit_code": 0,
                    "invocation_type": "autonomous",
                    "optional": True,
                    "discovery_total": page.get("total") or page.get("total_indexed"),
                    "discovery_offset": page.get("offset", 0),
                    "discovery_next_offset": page.get("next_offset"),
                    "capability_search_used": True,
                    "capability_candidates": [
                        item.get("capability_id")
                        for item in (page.get("matches") or page.get("tools") or [])[:12]
                        if isinstance(item, dict)
                    ],
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "tool_call_mode": call_mode,
                }
                log_slots[index] = discovery_row
                if emit_tool:
                    await emit_tool(run_id, discovery_row)
                obs = json.dumps(
                    {
                        "total": page.get("total") or page.get("total_indexed"),
                        "offset": page.get("offset", 0),
                        "next_offset": page.get("next_offset"),
                        "matches": page.get("matches"),
                        "tools": page.get("tools") or page.get("matches"),
                        "note": (
                            "Optional capabilities discovered. Invoke via "
                            "hades.capabilities.invoke with capability_id — "
                            "do not expect dynamic tools in the schema list."
                        ),
                    },
                    ensure_ascii=False,
                )
                result_slots[index] = tool_result_message(call_id=call.call_id, content=obs, mode=call_mode)
                continue

            selected = resolve_tool_row(plugin_id=call.plugin_id, tool_name=call.tool_name, tools=tools)
            if not selected:
                rejected_row = {
                    "call_id": call.call_id,
                    "plugin_id": call.plugin_id,
                    "tool_name": call.tool_name,
                    "provider_function_name": call.provider_function_name,
                    "status": "blocked",
                    "reason_code": "unknown_tool",
                    "error": "unknown_tool: model selected a tool that is not in the allowed shortlist/registry.",
                    "optional": True,
                    "tool_call_mode": call_mode,
                }
                if record_rejected is not None:
                    try:
                        persisted = record_rejected(
                            call.plugin_id,
                            call.tool_name,
                            call.arguments if isinstance(call.arguments, dict) else {},
                            status="blocked",
                            error=rejected_row["error"],
                        )
                        if isinstance(persisted, dict) and persisted.get("id"):
                            rejected_row["call_id"] = persisted.get("id") or rejected_row["call_id"]
                    except Exception:
                        pass
                log_slots[index] = rejected_row
                if emit_tool:
                    await emit_tool(run_id, rejected_row)
                result_slots[index] = tool_result_message(
                    call_id=call.call_id,
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "reason_code": "unknown_tool",
                            "error": rejected_row["error"],
                        },
                        ensure_ascii=False,
                    ),
                    mode=call_mode,
                )
                continue

            if call.parse_error:
                err_row = {
                    "call_id": call.call_id,
                    "plugin_id": call.plugin_id,
                    "tool_name": call.tool_name,
                    "provider_function_name": call.provider_function_name,
                    "status": "failed",
                    "error": call.parse_error,
                    "retryable": True,
                    "tool_call_mode": call_mode,
                }
                log_slots[index] = err_row
                if emit_tool:
                    await emit_tool(run_id, err_row)
                result_slots[index] = tool_result_message(
                    call_id=call.call_id,
                    content=json.dumps({"status": "failed", "error": call.parse_error, "schema_repair": True}, ensure_ascii=False),
                    mode=call_mode,
                )
                continue

            schema_errors = validate_against_schema(
                call.arguments,
                selected.get("input_schema") if isinstance(selected.get("input_schema"), dict) else {},
            )
            fingerprint = action_fingerprint(str(call.plugin_id), str(call.tool_name), call.arguments if isinstance(call.arguments, dict) else {})
            if failed_fingerprints.get(fingerprint, 0) >= 1:
                err_row = {
                    "call_id": call.call_id,
                    "plugin_id": call.plugin_id,
                    "tool_name": call.tool_name,
                    "status": "blocked",
                    "error": "Identieke mislukte toolactie niet herhaald zonder gewijzigde argumenten.",
                    "retryable": False,
                    "tool_call_mode": call_mode,
                    "steering_signal": "repeated_no_new_info",
                }
                log_slots[index] = err_row
                if emit_tool:
                    await emit_tool(run_id, err_row)
                result_slots[index] = tool_result_message(
                    call_id=call.call_id,
                    content=json.dumps({"status": "blocked", "error": err_row["error"]}, ensure_ascii=False),
                    mode=call_mode,
                )
                continue
            if schema_errors:
                err = "; ".join(schema_errors)
                failed_fingerprints[fingerprint] = failed_fingerprints.get(fingerprint, 0) + 1
                err_row = {
                    "call_id": call.call_id,
                    "plugin_id": call.plugin_id,
                    "tool_name": call.tool_name,
                    "provider_function_name": call.provider_function_name,
                    "status": "failed",
                    "error": f"Ongeldige toolargumenten: {err}",
                    "retryable": True,
                    "tool_call_mode": call_mode,
                }
                log_slots[index] = err_row
                if emit_tool:
                    await emit_tool(run_id, err_row)
                result_slots[index] = tool_result_message(
                    call_id=call.call_id,
                    content=json.dumps(
                        {"status": "failed", "error": err_row["error"], "schema_errors": schema_errors},
                        ensure_ascii=False,
                    ),
                    mode=call_mode,
                )
                continue

            pending_invokes.append((index, call, selected, started))

        if pending_invokes:
            parallel_limit = cfg.max_parallel_tool_calls
            if parallel_limit is not None:
                parallel_limit = max(1, int(parallel_limit))
            # Serial when limit is 1; otherwise bounded (or unlimited) concurrency.
            if parallel_limit == 1 or len(pending_invokes) == 1:
                for index, call, selected, started in pending_invokes:
                    tool_row, result_msg = await _invoke_selected_tool(
                        call=call,
                        selected=selected,
                        call_mode=call_mode,
                        invoke=invoke,
                        enforce_permissions=enforce_permissions,
                        record_rejected=record_rejected,
                        create_approval=create_approval,
                        emit_tool=emit_tool,
                        run_id=run_id,
                        tool_result_max_chars=cfg.tool_result_max_chars,
                        started=started,
                    )
                    log_slots[index] = tool_row
                    result_slots[index] = result_msg
                    if emit_tool:
                        await emit_tool(run_id, tool_row)
            else:
                sem = asyncio.Semaphore(parallel_limit) if parallel_limit is not None else None

                async def _bounded(
                    index: int,
                    call: NormalizedToolCall,
                    selected: dict[str, Any],
                    started: float,
                ) -> tuple[int, dict[str, Any], dict[str, Any]]:
                    if sem is None:
                        tool_row, result_msg = await _invoke_selected_tool(
                            call=call,
                            selected=selected,
                            call_mode=call_mode,
                            invoke=invoke,
                            enforce_permissions=enforce_permissions,
                            record_rejected=record_rejected,
                            create_approval=create_approval,
                            emit_tool=emit_tool,
                            run_id=run_id,
                            tool_result_max_chars=cfg.tool_result_max_chars,
                            started=started,
                        )
                    else:
                        async with sem:
                            tool_row, result_msg = await _invoke_selected_tool(
                                call=call,
                                selected=selected,
                                call_mode=call_mode,
                                invoke=invoke,
                                enforce_permissions=enforce_permissions,
                                record_rejected=record_rejected,
                                create_approval=create_approval,
                                emit_tool=emit_tool,
                                run_id=run_id,
                                tool_result_max_chars=cfg.tool_result_max_chars,
                                started=started,
                            )
                    return index, tool_row, result_msg

                gathered = await asyncio.gather(
                    *[_bounded(index, call, selected, started) for index, call, selected, started in pending_invokes]
                )
                for index, tool_row, result_msg in gathered:
                    log_slots[index] = tool_row
                    result_slots[index] = result_msg
                    if emit_tool:
                        await emit_tool(run_id, tool_row)

        for slot in log_slots:
            if slot is not None:
                tool_log.append(slot)
                fp = action_fingerprint(
                    str(slot.get("plugin_id") or ""),
                    str(slot.get("tool_name") or ""),
                    {},
                )
                signal = classify_tool_signal(slot)
                if signal and str(slot.get("status") or "") not in {"completed", "succeeded", "success", "ok"}:
                    failed_fingerprints[fp] = failed_fingerprints.get(fp, 0) + 1
                    slot.setdefault("steering_signal", signal)
                if signal == "capability_missing" and failed_fingerprints.get(fp, 0) >= 1:
                    return _result(
                        content=(
                            "Uitvoering gestopt: de gevraagde capability ontbreekt of is niet toegestaan. "
                            "Er volgt geen eindeloze herhaling."
                        ),
                        tool_log=tool_log,
                        model_calls=model_calls,
                        tool_call_mode=mode,
                        response_states=[*response_states, "capability_missing"],
                        usage_events=usage_events,
                    )
        if cfg.selected_mode == "adaptive" and execution_budget is not None:
            last_fail = next(
                (
                    slot
                    for slot in reversed(log_slots)
                    if slot is not None
                    and str(slot.get("status") or "") not in {"completed", "succeeded", "success", "ok"}
                ),
                None,
            )
            if last_fail:
                signal = str(last_fail.get("steering_signal") or classify_tool_signal(last_fail) or "")
                steer = next_steering_action(
                    signal,
                    profile=str(cfg.profile_name or "fast"),
                    selected_mode="adaptive",
                    fingerprint=action_fingerprint(
                        str(last_fail.get("plugin_id") or ""),
                        str(last_fail.get("tool_name") or ""),
                        last_fail.get("arguments") if isinstance(last_fail.get("arguments"), dict) else {},
                    ),
                )
                last_fail["steering_action"] = steer.action
                last_fail["steering_reason"] = steer.reason
                if steer.next_policy and steer.next_policy != cfg.profile_name:
                    from .budgets import scale_execution_budget

                    if scale_execution_budget(execution_budget, steer.next_policy):
                        cfg.profile_name = steer.next_policy
                        if execution_budget.max_tool_rounds is not None:
                            cfg.max_rounds = int(execution_budget.max_tool_rounds)
                        if execution_budget.max_model_calls is not None:
                            cfg.max_model_calls = int(execution_budget.max_model_calls)
                        last_fail["adaptive_effective_policy"] = steer.next_policy
                if steer.terminal:
                    return _result(
                        content=(
                            str(last_fail.get("error") or "")
                            or "Uitvoering gestopt na gerichte bijsturing; geen verdere herhaling."
                        ),
                        tool_log=tool_log,
                        model_calls=model_calls,
                        tool_call_mode=mode,
                        response_states=[*response_states, f"steering_{steer.action}"],
                        usage_events=usage_events,
                    )
        result_messages = [slot for slot in result_slots if slot is not None]
        base_messages = list(base_messages) + [assistant_msg] + result_messages

    return _result(
        content=finalize_without_tool_json(
            "",
            reason=f"Maximaal aantal autonome toolrondes ({cfg.max_rounds}) bereikt zonder definitief antwoord.",
        ),
        tool_log=tool_log,
        model_calls=model_calls,
        tool_call_mode=mode,
        response_states=response_states,
        usage_events=usage_events,
    )
