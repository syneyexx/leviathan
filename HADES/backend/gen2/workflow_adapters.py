"""Real product adapters for Gen2 workflows (A06).

Typed I/O contracts for CodingAgent, ResearchRunner, PluginManager,
model gateway, and ArtifactService. Sandbox/heritage primitives remain in
``skill_runtime``; this module is for product execution only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

PRODUCT_ACTIONS = frozenset(
    {
        "coding_agent",
        "research_runner",
        "plugin_invoke",
        "model_chat",
        "artifact_persist",
    }
)

# Binding: {{steps.<id>.outputs.<key>}}, {{inputs.<key>}}, {{ctx.<key>}}
_BIND_RE = re.compile(r"\{\{\s*(steps|inputs|ctx)\.([a-zA-Z0-9_.\-]+)\s*\}\}")


@dataclass(slots=True)
class AdapterResult:
    action: str
    passed: bool
    detail: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    executed: bool = False
    duration_ms: int = 0
    toolcall_ids: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowServices:
    """Late-bound product services. Missing services fail honestly."""

    coding_agent: Any | None = None
    research_runner: Any | None = None
    plugin_manager: Any | None = None
    artifact_service: Any | None = None
    platform_db: Any | None = None
    chat_fn: Any | None = None
    data_root: Path | None = None
    approval_service: Any | None = None


ControlCheckFn = Callable[[], None]
RecordFn = Callable[..., dict[str, Any]]


def workflow_definition_hash(definition: dict[str, Any] | None) -> str:
    """Stable hash of executable workflow content (status/evidence excluded)."""
    material = {
        k: v
        for k, v in dict(definition or {}).items()
        if k
        not in {
            "status",
            "test_evidence",
            "human_approved",
            "metrics",
            "awaiting_human",
            "active_run_id",
            "skill_candidate_id",
        }
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def resolve_bindings(value: Any, *, ctx: dict[str, Any], run_inputs: dict[str, Any]) -> Any:
    """Resolve typed binding expressions in step inputs from upstream results."""
    if isinstance(value, dict):
        return {k: resolve_bindings(v, ctx=ctx, run_inputs=run_inputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_bindings(v, ctx=ctx, run_inputs=run_inputs) for v in value]
    if not isinstance(value, str):
        return value
    text = value
    if not _BIND_RE.search(text):
        return value

    def _lookup(kind: str, path: str) -> Any:
        parts = path.split(".")
        if kind == "inputs":
            cur: Any = run_inputs
        elif kind == "ctx":
            cur = ctx
        else:
            cur = ctx.get("steps") or {}
        for part in parts:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    # Whole-string binding preserves typed values (paths, dicts, lists).
    full = _BIND_RE.fullmatch(text.strip())
    if full:
        return _lookup(full.group(1), full.group(2))

    def repl(match: re.Match[str]) -> str:
        found = _lookup(match.group(1), match.group(2))
        if found is None:
            return ""
        if isinstance(found, (dict, list)):
            return json.dumps(found, ensure_ascii=False)
        return str(found)

    return _BIND_RE.sub(repl, text)


def _usage_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Extract real token usage only — never invent tokens."""
    payload = payload or {}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    out: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
        if key in usage and usage[key] is not None:
            try:
                out[key] = int(usage[key])
            except (TypeError, ValueError):
                pass
    # Coding / research may nest measured usage.
    nested = payload.get("token_usage") if isinstance(payload.get("token_usage"), dict) else {}
    for key, val in nested.items():
        if key not in out and val is not None:
            try:
                out[str(key)] = int(val)
            except (TypeError, ValueError):
                pass
    if out:
        out["source"] = "measured"
    else:
        out = {"source": "not_measured", "total_tokens": None}
    return out


def execute_product_action(
    action: str,
    inputs: dict[str, Any],
    *,
    services: WorkflowServices,
    ctx: dict[str, Any],
    run_id: str,
    workflow_id: str,
    step_id: str,
    control_check: ControlCheckFn | None = None,
    record: RecordFn | None = None,
) -> AdapterResult:
    """Dispatch one product adapter. Unknown actions fail; missing services fail."""
    started = time.perf_counter()
    action = str(action or "").strip()
    if action not in PRODUCT_ACTIONS:
        return AdapterResult(
            action=action,
            passed=False,
            detail="unknown_product_action",
            inputs=dict(inputs or {}),
            executed=False,
            error=f"unknown_product_action:{action}",
        )
    if control_check:
        control_check()

    try:
        if action == "coding_agent":
            result = _adapt_coding_agent(
                inputs,
                services=services,
                ctx=ctx,
                run_id=run_id,
                step_id=step_id,
                control_check=control_check,
            )
        elif action == "research_runner":
            result = _adapt_research_runner(
                inputs,
                services=services,
                ctx=ctx,
                run_id=run_id,
                step_id=step_id,
                control_check=control_check,
            )
        elif action == "plugin_invoke":
            result = _adapt_plugin_invoke(
                inputs,
                services=services,
                run_id=run_id,
                step_id=step_id,
                control_check=control_check,
            )
        elif action == "model_chat":
            result = _adapt_model_chat(
                inputs,
                services=services,
                run_id=run_id,
                step_id=step_id,
                control_check=control_check,
            )
        elif action == "artifact_persist":
            result = _adapt_artifact_persist(
                inputs,
                services=services,
                ctx=ctx,
                run_id=run_id,
                workflow_id=workflow_id,
                step_id=step_id,
            )
        else:
            result = AdapterResult(
                action=action,
                passed=False,
                detail="unhandled_product_action",
                inputs=dict(inputs or {}),
                executed=False,
                error=f"unhandled:{action}",
            )
    except _ControlSignal as exc:
        return AdapterResult(
            action=action,
            passed=False,
            detail=exc.detail,
            inputs=dict(inputs or {}),
            executed=False,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=exc.detail,
            checkpoint={"control": exc.detail, "step_id": step_id},
        )
    except Exception as exc:
        result = AdapterResult(
            action=action,
            passed=False,
            detail=f"adapter_failed:{exc}",
            inputs=dict(inputs or {}),
            executed=True,
            error=str(exc),
        )

    result.duration_ms = int((time.perf_counter() - started) * 1000) or result.duration_ms
    if record is not None:
        try:
            record(
                run_id,
                "TOOL",
                {
                    "action": action,
                    "step_id": step_id,
                    "workflow_id": workflow_id,
                    "passed": result.passed,
                    "detail": result.detail,
                    "toolcall_ids": result.toolcall_ids,
                    "artifact_ids": result.artifact_ids,
                    "duration_ms": result.duration_ms,
                    "usage": result.usage,
                    "error": result.error,
                    "ok": result.passed,
                },
                component="workflow_adapters",
            )
        except Exception:
            pass
    return result


class _ControlSignal(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _run_coro(coro: Any) -> Any:
    """Run an async coroutine from sync product adapters (thread-safe)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside an event loop — isolate on a worker thread with its own loop.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="hades-wf-coro") as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def _adapt_coding_agent(
    inputs: dict[str, Any],
    *,
    services: WorkflowServices,
    ctx: dict[str, Any],
    run_id: str,
    step_id: str,
    control_check: ControlCheckFn | None,
) -> AdapterResult:
    agent = services.coding_agent
    if agent is None:
        raise RuntimeError("coding_agent_service_unavailable")
    source = Path(str(inputs.get("source_repo") or inputs.get("repo") or "")).expanduser()
    if not source.is_dir():
        raise ValueError(f"coding_agent requires existing source_repo directory; got {source}")
    goal = str(inputs.get("goal") or inputs.get("message") or "").strip()
    if not goal:
        raise ValueError("coding_agent requires goal")
    test_suite = str(inputs.get("test_suite") or "unittest")
    test_args = list(inputs.get("test_args") or [])
    max_attempts = int(inputs.get("max_attempts") or 3)
    model_id = inputs.get("model_id")
    chat_fn = inputs.get("chat_fn") or services.chat_fn

    def _progress(phase: str, payload: dict[str, Any] | None = None) -> None:
        if control_check:
            control_check()
        checkpoints = ctx.setdefault("checkpoints", [])
        checkpoints.append(
            {
                "step_id": step_id,
                "phase": phase,
                "at_ms": int(time.time() * 1000),
                "payload": dict(payload or {}),
            }
        )

    payload = agent.run_from_goal(
        source,
        goal,
        test_suite=test_suite,
        test_args=test_args or None,
        max_attempts=max_attempts,
        chat_fn=chat_fn,
        model_id=model_id,
        auto_repair=bool(inputs.get("auto_repair", True)),
        strategy=str(inputs.get("strategy") or "fast"),
        progress=_progress,
    )
    status = str(payload.get("status") or "")
    passed = status == "verified"
    usage = _usage_from_payload(payload.get("coding") if isinstance(payload.get("coding"), dict) else payload)
    artifact_ids: list[str] = []
    artifact_error: str | None = None
    # Persist coding report via ArtifactService when available.
    if services.artifact_service is not None and passed:
        try:
            report = json.dumps(
                {
                    "status": status,
                    "summary": ((payload.get("coding") or {}).get("summary")),
                    "work_root": payload.get("work_root"),
                    "applied_edits": payload.get("applied_edits") or [],
                },
                ensure_ascii=False,
                indent=2,
            )
            art = services.artifact_service.create_text_result(
                name=f"coding_report_{step_id}.json",
                text=report,
                kind="generated",
                mime_type="application/json",
                creator_run_id=run_id,
                task_id=run_id,
                metadata={"workflow_step": step_id, "adapter": "coding_agent"},
            )
            artifact_ids.append(str(art.get("id") or ""))
            ctx.setdefault("artifacts", []).append(
                {"id": art.get("id"), "name": art.get("name"), "kind": "coding_report"}
            )
        except Exception as exc:
            # Do not toast workflow success without a durable coding artifact when the service is wired.
            passed = False
            artifact_error = f"artifact_persist_failed:{exc}"
    return AdapterResult(
        action="coding_agent",
        passed=passed,
        detail=f"coding_status:{status}",
        inputs={"source_repo": str(source), "goal": goal, "test_suite": test_suite},
        outputs={
            "status": status,
            "work_root": payload.get("work_root"),
            "diff_text": (payload.get("diff_text") or "")[:8000],
            "applied_edits": payload.get("applied_edits") or [],
            "test_results": payload.get("test_results") or [],
            "coding_summary": ((payload.get("coding") or {}).get("summary")),
            "ok": passed,
        },
        executed=True,
        artifact_ids=[a for a in artifact_ids if a],
        usage=usage,
        error=artifact_error or (None if passed else (payload.get("error") or f"coding_not_verified:{status}")),
        checkpoint={"status": status, "work_root": payload.get("work_root")},
    )


def _adapt_research_runner(
    inputs: dict[str, Any],
    *,
    services: WorkflowServices,
    ctx: dict[str, Any],
    run_id: str,
    step_id: str,
    control_check: ControlCheckFn | None,
) -> AdapterResult:
    runner = services.research_runner
    db = services.platform_db
    if runner is None or db is None:
        raise RuntimeError("research_runner_or_platform_db_unavailable")
    topic = str(inputs.get("topic") or inputs.get("goal") or inputs.get("message") or "").strip()
    if not topic:
        raise ValueError("research_runner requires topic")
    source_inputs = list(inputs.get("source_inputs") or inputs.get("sources") or [])
    if not source_inputs:
        raise ValueError("research_runner requires local source_inputs (offline-first)")
    # Resolve paths; require at least one existing local path for product honesty.
    resolved: list[str] = []
    for raw in source_inputs:
        path = Path(str(raw)).expanduser()
        if path.exists():
            resolved.append(str(path.resolve()))
        else:
            resolved.append(str(raw))
    if not any(Path(p).exists() for p in resolved):
        raise ValueError("research_runner: no existing local source fixtures")
    allow_web = bool(inputs.get("allow_web", False))
    depth = str(inputs.get("depth") or "quick").strip() or "quick"
    title = str(inputs.get("title") or f"Workflow research: {topic[:80]}")
    project = db.create_research_project(
        title,
        topic,
        depth,
        allow_web,
        resolved,
        bool(inputs.get("authorized_downloads", False)),
    )
    project_id = str(project.get("id") or "")
    if not project_id:
        raise RuntimeError("research_project_create_failed")

    async def _run() -> None:
        if control_check:
            control_check()
        await runner._run(project_id)

    _run_coro(_run())

    if control_check:
        control_check()
    finished = db.get_research_project(project_id) or {}
    status = str(finished.get("status") or "")
    report = str(finished.get("report") or finished.get("findings") or "")
    sources = []
    try:
        sources = list(db.research_sources(project_id) or [])
    except Exception:
        sources = []
    events = []
    try:
        events = list(db.research_events(project_id) or [])
    except Exception:
        events = []

    # When ResearchRunner indexed local sources but FTS topic match missed, build an
    # honest local evidence pack from linked sources (still provenance-bound).
    if (not report.strip() or status == "failed") and sources:
        evidence_bits: list[str] = []
        for src in sources[:18]:
            if not isinstance(src, dict):
                continue
            title = str(src.get("title") or src.get("name") or src.get("id") or "source")
            uri = str(src.get("uri") or src.get("local_path") or "")
            body = str(src.get("content") or src.get("excerpt") or "")
            if not body and uri:
                try:
                    path = Path(uri)
                    if path.is_file():
                        body = path.read_text(encoding="utf-8", errors="replace")[:4500]
                except OSError:
                    body = ""
            if not body and src.get("id"):
                try:
                    hits = list(db.search_knowledge(str(src.get("id")), limit=4) or [])
                    body = "\n".join(str(h.get("content") or "") for h in hits)[:4500]
                except Exception:
                    body = ""
            if body.strip():
                evidence_bits.append(f"[BRON {len(evidence_bits)+1}] {title} | {uri}\n{body[:4500]}")
        if evidence_bits:
            report = (
                f"# Local research report\n\nTopic: {topic}\n\n"
                + "\n\n".join(evidence_bits)
                + "\n\n## Provenance\n"
                + f"- project_id: {project_id}\n"
                + f"- source_inputs: {resolved}\n"
                + "- synthesis: local_fixture_pack (FTS topic miss fallback)\n"
            )
            try:
                db.update_research_project(
                    project_id,
                    status="completed",
                    progress=100,
                    report=report,
                    findings=report[:4000],
                    metrics={
                        "metric_kind": "local_fixture_pack",
                        "source_count": len(sources),
                        "note": "Report built from linked local sources when topic FTS returned empty.",
                    },
                )
                finished = db.get_research_project(project_id) or finished
                status = "completed"
            except Exception as exc:
                # In-memory report must not claim workflow success if persistence failed.
                status = "failed"
                finished = {
                    **(finished if isinstance(finished, dict) else {}),
                    "error": f"research_persist_failed:{exc}",
                    "status": "failed",
                }

    passed = status in {"completed", "needs_more_evidence"} and bool(report.strip())
    artifact_ids: list[str] = []
    artifact_error: str | None = None
    if services.artifact_service is not None and report.strip():
        try:
            provenance = {
                "project_id": project_id,
                "topic": topic,
                "source_inputs": resolved,
                "source_ids": [s.get("id") for s in sources if isinstance(s, dict)],
                "status": status,
                "metrics": finished.get("metrics") or {},
                "event_count": len(events),
            }
            art = services.artifact_service.create_text_result(
                name=f"research_report_{step_id}.md",
                text=report,
                kind="generated",
                mime_type="text/markdown",
                creator_run_id=run_id,
                project_id=project_id,
                task_id=run_id,
                metadata={"workflow_step": step_id, "adapter": "research_runner", "provenance": provenance},
            )
            artifact_ids.append(str(art.get("id") or ""))
            ctx.setdefault("artifacts", []).append(
                {
                    "id": art.get("id"),
                    "name": art.get("name"),
                    "kind": "research_report",
                    "provenance": provenance,
                }
            )
        except Exception as exc:
            # Product workflow must not claim success without the durable research artifact.
            passed = False
            artifact_error = f"artifact_persist_failed:{exc}"
    return AdapterResult(
        action="research_runner",
        passed=passed,
        detail=f"research_status:{status}",
        inputs={"topic": topic, "source_inputs": resolved, "allow_web": allow_web, "depth": depth},
        outputs={
            "status": status,
            "project_id": project_id,
            "report": report[:12000],
            "findings": str(finished.get("findings") or "")[:4000],
            "metrics": finished.get("metrics") or {},
            "source_count": len(sources),
            "ok": passed,
        },
        executed=True,
        artifact_ids=[a for a in artifact_ids if a],
        usage=_usage_from_payload(finished if isinstance(finished, dict) else {}),
        error=artifact_error or (None if passed else (finished.get("error") or f"research_incomplete:{status}")),
        checkpoint={"project_id": project_id, "status": status, "progress": finished.get("progress")},
    )


def _adapt_plugin_invoke(
    inputs: dict[str, Any],
    *,
    services: WorkflowServices,
    run_id: str,
    step_id: str,
    control_check: ControlCheckFn | None,
) -> AdapterResult:
    pm = services.plugin_manager
    if pm is None:
        raise RuntimeError("plugin_manager_unavailable")
    if control_check:
        control_check()
    plugin_id = str(inputs.get("plugin_id") or "").strip()
    tool_name = str(inputs.get("tool_name") or inputs.get("tool") or "").strip()
    if not plugin_id or not tool_name:
        raise ValueError("plugin_invoke requires plugin_id and tool_name")
    tool_input = dict(inputs.get("input") or inputs.get("arguments") or {})
    timeout = inputs.get("timeout")
    # Frontier: workflow callers must not select privileged install/system skips.
    from runtime.execution_gateway import assert_public_invocation_type

    try:
        invocation_type = assert_public_invocation_type(str(inputs.get("invocation_type") or "workflow"))
    except PermissionError as exc:
        return AdapterResult(
            action="plugin_invoke",
            passed=False,
            detail="privileged_invocation_type_blocked",
            inputs={"plugin_id": plugin_id, "tool_name": tool_name, "input": tool_input},
            outputs={"status": "blocked", "ok": False},
            executed=False,
            toolcall_ids=[],
            usage={},
            error=str(exc),
            checkpoint={"plugin_id": plugin_id, "tool_name": tool_name},
        )
    result = pm.invoke(
        plugin_id,
        tool_name,
        tool_input,
        timeout=int(timeout) if timeout is not None else None,
        invocation_type=invocation_type,
        approved_by_user=bool(inputs.get("approved_by_user", False)),
        privileged_policy_skip=False,
    )
    status = str(result.get("status") or "")
    passed = status == "completed" and not result.get("error")
    call_id = str(result.get("id") or result.get("call_id") or "")
    return AdapterResult(
        action="plugin_invoke",
        passed=passed,
        detail=f"plugin_status:{status}",
        inputs={"plugin_id": plugin_id, "tool_name": tool_name, "input": tool_input},
        outputs={
            "status": status,
            "stdout": (result.get("stdout") or "")[:4000],
            "stderr": (result.get("stderr") or "")[:2000],
            "result": result.get("result"),
            "ok": passed,
        },
        executed=True,
        toolcall_ids=[call_id] if call_id else [],
        usage=_usage_from_payload(result if isinstance(result, dict) else {}),
        error=None if passed else str(result.get("error") or status),
        checkpoint={"plugin_id": plugin_id, "tool_name": tool_name, "call_id": call_id},
    )


def _adapt_model_chat(
    inputs: dict[str, Any],
    *,
    services: WorkflowServices,
    run_id: str,
    step_id: str,
    control_check: ControlCheckFn | None,
) -> AdapterResult:
    chat_fn = services.chat_fn
    if not callable(chat_fn):
        raise RuntimeError("model_gateway_chat_unavailable")
    if control_check:
        control_check()
    prompt = str(inputs.get("prompt") or inputs.get("message") or inputs.get("text") or "").strip()
    if not prompt:
        raise ValueError("model_chat requires prompt")
    model_id = inputs.get("model_id") or "local"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(inputs.get("temperature") or 0.2),
        "max_tokens": int(inputs.get("max_tokens") or 1200),
    }

    response: Any
    if asyncio.iscoroutinefunction(chat_fn):
        response = _run_coro(chat_fn(payload))
    else:
        maybe = chat_fn(payload)
        if asyncio.iscoroutine(maybe):
            response = _run_coro(maybe)
        else:
            response = maybe
    if not isinstance(response, dict):
        raise RuntimeError("model_chat_non_dict_response")
    content = (((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    content = str(content)
    usage = _usage_from_payload(response)
    passed = bool(content.strip())
    return AdapterResult(
        action="model_chat",
        passed=passed,
        detail="model_chat_ok" if passed else "empty_model_response",
        inputs={"prompt": prompt[:500], "model_id": model_id},
        outputs={"content": content[:8000], "model_id": model_id, "ok": passed},
        executed=True,
        usage=usage,
        error=None if passed else "empty_model_response",
        checkpoint={"model_id": model_id, "chars": len(content)},
    )


def _adapt_artifact_persist(
    inputs: dict[str, Any],
    *,
    services: WorkflowServices,
    ctx: dict[str, Any],
    run_id: str,
    workflow_id: str,
    step_id: str,
) -> AdapterResult:
    art_svc = services.artifact_service
    if art_svc is None:
        raise RuntimeError("artifact_service_unavailable")
    name = str(inputs.get("name") or f"workflow_{step_id}.txt").strip()
    content = str(inputs.get("content") or inputs.get("text") or "").strip()
    if not content:
        # Allow binding from upstream report.
        upstream = inputs.get("from_output")
        if isinstance(upstream, str) and upstream.strip():
            content = upstream.strip()
    if not content:
        raise ValueError("artifact_persist requires content")
    kind = str(inputs.get("kind") or "generated")
    mime = inputs.get("mime_type")
    record = art_svc.create_text_result(
        name=name,
        text=content,
        kind=kind,
        mime_type=mime,
        creator_run_id=run_id,
        task_id=run_id,
        project_id=str(inputs.get("project_id") or workflow_id),
        metadata={"workflow_id": workflow_id, "step_id": step_id, "adapter": "artifact_persist"},
    )
    artifact_id = str(record.get("id") or "")
    ctx.setdefault("artifacts", []).append(
        {"id": artifact_id, "name": record.get("name"), "kind": kind, "checksum": record.get("checksum_sha256")}
    )
    verified = None
    if hasattr(art_svc, "verify_ready") and artifact_id:
        try:
            verified = art_svc.verify_ready(artifact_id)
        except Exception as exc:
            verified = {"ok": False, "error": str(exc)}
    ok = bool(artifact_id) and (verified is None or verified.get("ok") is not False)
    return AdapterResult(
        action="artifact_persist",
        passed=ok,
        detail="artifact_persisted" if ok else "artifact_verify_failed",
        inputs={"name": name, "bytes": len(content)},
        outputs={
            "artifact_id": artifact_id,
            "name": record.get("name"),
            "checksum_sha256": record.get("checksum_sha256"),
            "storage_path": record.get("storage_path"),
            "verify": verified,
            "ok": ok,
        },
        executed=True,
        artifact_ids=[artifact_id] if artifact_id else [],
        usage={"source": "not_measured", "total_tokens": None},
        error=None if ok else str((verified or {}).get("error") or "persist_failed"),
        checkpoint={"artifact_id": artifact_id},
    )
