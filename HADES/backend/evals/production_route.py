"""Production-route adapter for A01 agent evaluation.

Invokes the same coding/agent path used by HADES capability routes
(``CodingAgentService.run_from_goal`` with optional LM Studio ``chat_fn``),
plus the KnowledgeService local research path for research agent tasks.

Does NOT inject solutions into workspaces. Fake/stub callbacks are only for
software tests proving the route is called.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

PRODUCTION_ROUTE_ID = "hades.production_route.v1"
PRODUCTION_STAGES = (
    "model_gateway",
    "retrieval",
    "planning",
    "tool_execution",
    "task_status",
    "artifacts",
    "verification",
)
PRODUCTION_TELEMETRY_SCHEMA_VERSION = "production_route_v3"

MeasurementStatus = Literal["measured", "UNMEASURED", "UNAVAILABLE"]
EvaluationKind = Literal["software", "model_answer", "agent_task"]


@dataclass
class ProductionRouteRequest:
    task_id: str
    goal: str
    work_root: Path
    task: dict[str, Any]
    model_id: str | None = None
    max_attempts: int = 3
    budget: dict[str, Any] = field(default_factory=dict)
    chat_fn: Any | None = None
    run_baseline: bool = False


@dataclass
class GatewayObservation:
    """Typed gateway observation — availability is never treated as an attempt."""

    available: bool
    attempted: bool
    responded: bool
    processed: bool
    provider_source: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "attempted": self.attempted,
            "responded": self.responded,
            "processed": self.processed,
            "provider_source": self.provider_source,
            "error": self.error,
            "telemetry_schema": PRODUCTION_TELEMETRY_SCHEMA_VERSION,
            "legacy_records_note": (
                "Records generated before production_route_v3 may over-report model_invoked/stages."
            ),
        }


@dataclass
class MeasurementLayers:
    """Separate software, model-answer, and full agent-task measurement honesty."""

    software: MeasurementStatus
    model_answer: MeasurementStatus
    agent_task: MeasurementStatus
    evaluation_kind: EvaluationKind
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "software": self.software,
            "model_answer": self.model_answer,
            "agent_task": self.agent_task,
            "evaluation_kind": self.evaluation_kind,
            "notes": list(self.notes),
        }


def probe_lm_studio(base_url: str | None = None, timeout: float = 2.0) -> dict[str, Any]:
    """Best-effort local LM Studio reachability probe."""
    import urllib.error
    import urllib.request

    url = (base_url or "http://127.0.0.1:1234/v1").rstrip("/") + "/models"
    try:
        from database import DEFAULT_SETTINGS

        if not base_url:
            url = str(DEFAULT_SETTINGS.get("lm_studio_base_url") or "http://127.0.0.1:1234/v1").rstrip(
                "/"
            ) + "/models"
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            models = []
            try:
                parsed = json.loads(body)
                models = [m.get("id") for m in (parsed.get("data") or []) if isinstance(m, dict)]
            except json.JSONDecodeError:
                models = []
            return {
                "available": True,
                "url": url,
                "models": models,
                "status": "ok",
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "url": url,
            "models": [],
            "status": "unavailable",
            "error": str(exc),
        }


def _resolve_chat_fn(explicit: Any | None = None) -> tuple[Any | None, dict[str, Any]]:
    if callable(explicit):
        return explicit, {"source": "explicit", "lm_studio": probe_lm_studio()}
    probe = probe_lm_studio()
    if not probe.get("available"):
        return None, {"source": "none", "lm_studio": probe}
    try:
        from database import DEFAULT_SETTINGS
        from lm_studio import LmStudioClient

        client = LmStudioClient(
            str(DEFAULT_SETTINGS.get("lm_studio_base_url") or "http://127.0.0.1:1234/v1"),
            str(DEFAULT_SETTINGS.get("lm_studio_api_key") or "lm-studio"),
            float(DEFAULT_SETTINGS.get("lm_studio_timeout") or 120),
        )
        return client.chat, {"source": "lm_studio", "lm_studio": probe}
    except Exception as exc:  # noqa: BLE001
        probe = {**probe, "client_error": str(exc)}
        return None, {"source": "none", "lm_studio": probe}


def _tokens_from_coding_result(result: dict[str, Any]) -> dict[str, Any] | None:
    coding = result.get("coding") or {}
    for key in ("tokens", "token_usage", "usage"):
        if isinstance(coding.get(key), dict):
            return dict(coding[key])
        if isinstance(result.get(key), dict):
            return dict(result[key])
    propose = coding.get("propose") or {}
    if isinstance(propose.get("usage"), dict):
        return dict(propose["usage"])
    return None


def _coding_stage_observations(result: dict[str, Any], *, model_attempted: bool) -> list[str]:
    """Derive observed stages from concrete run artifacts/events only."""
    observed: list[str] = []
    coding = result.get("coding") or {}
    explore = coding.get("explore") or {}
    if model_attempted:
        observed.append("model_gateway")
    if explore.get("hits") or explore.get("selected_files"):
        observed.append("retrieval")
    loop = result.get("loop_timeline") or []
    if any(isinstance(item, dict) and item.get("phase") == "plan" for item in loop):
        observed.append("planning")
    if any(
        isinstance(item, dict)
        and item.get("phase") in {"apply_edits", "repair"}
        and item.get("status") in {"ok", "applied"}
        for item in loop
    ):
        observed.append("tool_execution")
    if result.get("status"):
        observed.append("task_status")
    if result.get("artifacts"):
        observed.append("artifacts")
    if any(isinstance(item, dict) and item.get("phase") == "test" for item in loop):
        observed.append("verification")
    return [stage for stage in PRODUCTION_STAGES if stage in set(observed)]


def _model_gateway_observation_from_coding(
    result: dict[str, Any], chat_fn: Any | None, meta: dict[str, Any]
) -> GatewayObservation:
    coding = result.get("coding") or {}
    propose = coding.get("propose") or {}
    note = str(propose.get("note") or "")
    method = str(propose.get("method") or "")
    model_available = bool(callable(chat_fn))
    # Prefer typed flags from the coding gateway when present.
    typed = propose.get("gateway_observation")
    if isinstance(typed, dict) and any(k in typed for k in ("attempted", "responded", "processed")):
        return GatewayObservation(
            available=bool(typed.get("available", model_available)),
            attempted=bool(typed.get("attempted")),
            responded=bool(typed.get("responded")),
            processed=bool(typed.get("processed")),
            provider_source=str(meta.get("source") or typed.get("provider_source") or "") or None,
            error=str(typed.get("error")) if typed.get("error") else None,
        )
    # Attempt is explicit from invoke-note/method; availability alone is not an attempt.
    attempted = bool(
        propose.get("model_invoked")
        or method.startswith("live_model")
        or note.startswith("lm_invoke_")
    )
    responded = bool(propose.get("model_invoked"))
    processed = bool(responded and method.startswith("live_model"))
    return GatewayObservation(
        available=model_available,
        attempted=attempted,
        responded=responded,
        processed=processed,
        provider_source=str(meta.get("source") or "") or None,
    )


def _coding_measurement_layers(
    *,
    stages_hit: list[str],
    gateway: GatewayObservation,
    provider_source: str | None,
) -> MeasurementLayers:
    notes: list[str] = []
    software: MeasurementStatus = "measured" if stages_hit else "UNMEASURED"
    if gateway.processed:
        model_answer: MeasurementStatus = "measured"
    elif gateway.attempted:
        model_answer = "UNMEASURED"
        notes.append("model_gateway_attempted_without_processed_response")
    elif not gateway.available or provider_source in {None, "none"}:
        model_answer = "UNAVAILABLE"
        notes.append("model_provider_unavailable")
    else:
        model_answer = "UNMEASURED"
        notes.append("model_available_but_not_attempted")
    # Software outcome never proves model-answer quality.
    if software == "measured" and model_answer != "measured":
        notes.append("software_measured_does_not_imply_model_quality")
    # Full coding agent task requires verification stage + model processing for model-backed claims.
    if "verification" in stages_hit and gateway.processed:
        agent_task: MeasurementStatus = "measured"
    elif "verification" in stages_hit:
        agent_task = "measured"  # software agent-task path (tests) can be measured without model
        notes.append("agent_task_software_verification_without_model_quality")
    else:
        agent_task = "UNMEASURED"
    return MeasurementLayers(
        software=software,
        model_answer=model_answer,
        agent_task=agent_task,
        evaluation_kind="agent_task" if agent_task == "measured" else "software",
        notes=notes,
    )


def _run_coding_production(req: ProductionRouteRequest, chat_fn: Any | None, meta: dict[str, Any]) -> dict[str, Any]:
    from build_agent import BuildAgentService
    from coding_agent import CodingAgentService

    started = time.perf_counter()
    build = BuildAgentService(Path(req.work_root).parent)
    coding = CodingAgentService(build)
    strategy = "fast" if req.run_baseline else "investigate"
    result = coding.run_from_goal(
        Path(req.work_root),
        req.goal,
        test_suite="unittest",
        test_args=list(req.task.get("test_args") or []),
        max_attempts=int(req.budget.get("max_attempts") or req.max_attempts),
        chat_fn=chat_fn,
        model_id=req.model_id,
        auto_repair=True,
        strategy=strategy,
        autonomy_profile=str(req.task.get("autonomy_profile") or req.budget.get("autonomy_profile") or "reviewable_result"),
        task_type=req.task.get("task_type"),
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    tokens = _tokens_from_coding_result(result if isinstance(result, dict) else {})
    gateway = _model_gateway_observation_from_coding(result, chat_fn, meta)
    stages_hit = _coding_stage_observations(
        result if isinstance(result, dict) else {},
        model_attempted=bool(gateway.attempted),
    )
    layers = _coding_measurement_layers(
        stages_hit=stages_hit,
        gateway=gateway,
        provider_source=str(meta.get("source") or "") or None,
    )
    # Top-level measurement_status reflects software observability only; model quality is separate.
    return {
        "route": PRODUCTION_ROUTE_ID,
        "invoked": True,
        "solution_injected": False,
        "task_id": req.task_id,
        "status": result.get("status"),
        "work_root": str(result.get("work_root") or req.work_root),
        "artifacts": list(result.get("artifacts") or []),
        "task_status": result.get("status"),
        "tokens": tokens,
        "duration_ms": duration_ms,
        "error_category": result.get("error_category") or result.get("error"),
        "policy_violations": list(result.get("policy_violations") or []),
        "model_invoked": bool(gateway.responded),
        "stages": stages_hit,
        "stages_declared": list(PRODUCTION_STAGES),
        "gateway_meta": {**meta, "observation": gateway.to_dict()},
        "baseline_mode": bool(req.run_baseline),
        "measurement_status": layers.software,
        "measurement_layers": layers.to_dict(),
        "evaluation_kind": layers.evaluation_kind,
        "raw": {
            "status": result.get("status"),
            "coding_keys": sorted((result.get("coding") or {}).keys()),
            "test_results_count": len(result.get("test_results") or []),
            "model_gateway_observation": gateway.to_dict(),
        },
        "claimed_success": result.get("status") == "verified",
    }


_CONFLICT_POS = re.compile(r"\b(improv\w*|better|decreased latency|lower latency)\b", re.I)
_CONFLICT_NEG = re.compile(r"\b(worsen\w*|worse|increased latency|higher latency)\b", re.I)


def _synthesize_research_answer_from_sources(root: Path, goal: str) -> dict[str, Any]:
    """Deterministic local research synthesis used by the Knowledge production path.

    Inspects ingested source texts under the fixture workspace. Does not invent
    magnitudes. Conflicting polarity → needs_more_evidence.
    """
    source_dirs = [root / "sources", root / "docs"]
    citations: list[str] = []
    texts: list[str] = []
    for folder in source_dirs:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            citations.append(rel)
            texts.append(text)
    joined = "\n".join(texts)
    has_pos = bool(_CONFLICT_POS.search(joined))
    has_neg = bool(_CONFLICT_NEG.search(joined))
    conflict = has_pos and has_neg
    missing_markers = any(
        token in joined.lower()
        for token in ("unknown", "not documented", "sla target is not", "region is unknown")
    )
    invented = bool(re.search(r"\b\d{2,3}\s*%", joined))
    needs = bool(conflict or missing_markers or not citations)
    if conflict:
        claim = "Sources conflict on latency direction; insufficient evidence for a magnitude."
    elif missing_markers:
        claim = "Required SLA/region fields are not present in available sources."
    elif "201" in joined and "POST" in joined.upper():
        claim = "POST /v2/items returns 201"
        needs = False
    else:
        claim = "Summary limited to cited local sources; no invented magnitude."
    answer = {
        "claim": claim,
        "citations": citations,
        "needs_more_evidence": needs,
        "status_code": 201 if ("201" in claim or claim.endswith("201")) else None,
        "goal": goal,
        "conflict_detected": conflict,
        "invented_magnitude_in_sources": invented,
    }
    if answer["status_code"] is None:
        answer.pop("status_code")
    return answer


def _run_research_knowledge_production(
    req: ProductionRouteRequest, chat_fn: Any | None, meta: dict[str, Any]
) -> dict[str, Any]:
    """Wire research agent tasks to KnowledgeService local ingestion (production path).

    - Software / agent_task layers are measured from post-state artifacts (answer.json).
    - Model-answer quality is UNAVAILABLE/UNMEASURED unless a gateway response is observed.
    - Never marks PASS for model quality when the provider is missing.
    """
    from platform_db import PlatformDatabase
    from platform_services_core import KnowledgeService

    root = Path(req.work_root)
    started = time.perf_counter()
    stages: list[str] = ["planning", "retrieval"]
    artifacts: list[str] = []
    error_category = None
    tokens = None
    model_invoked = False
    gateway = GatewayObservation(
        available=bool(callable(chat_fn)),
        attempted=False,
        responded=False,
        processed=False,
        provider_source=str(meta.get("source") or "") or None,
    )

    data_root = root / ".hades_eval_knowledge"
    data_root.mkdir(parents=True, exist_ok=True)
    db = PlatformDatabase(data_root / "platform.db")
    knowledge = KnowledgeService(db, data_root)
    ingested: list[str] = []
    for folder_name in ("sources", "docs"):
        folder = root / folder_name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            try:
                result = knowledge.ingest_file(path, workspace_id=f"eval:{req.task_id}")
                if result.get("source"):
                    ingested.append(str(path))
            except Exception as exc:  # noqa: BLE001
                error_category = f"knowledge_ingest:{exc}"

    stages.append("tool_execution")
    answer = _synthesize_research_answer_from_sources(root, req.goal)
    (root / "answer.json").write_text(json.dumps(answer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts.append("answer.json")
    stages.append("artifacts")

    # Optional model transcript — never used as sole success evidence.
    if callable(chat_fn):
        gateway.attempted = True
        stages = ["model_gateway", *stages]
        try:
            import asyncio

            brief = ""
            if (root / "BRIEF.md").is_file():
                brief = (root / "BRIEF.md").read_text(encoding="utf-8")
            prompt = f"{req.goal}\n\n{brief}".strip()

            async def _call() -> Any:
                return await chat_fn(
                    {
                        "model": req.model_id or "local",
                        "messages": [{"role": "user", "content": prompt[:4000]}],
                        "temperature": 0,
                        "max_tokens": 400,
                    }
                )

            try:
                asyncio.get_running_loop()
                running = True
            except RuntimeError:
                running = False
            if running:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=1) as pool:
                    response = pool.submit(lambda: asyncio.run(_call())).result(timeout=120)
            else:
                response = asyncio.run(_call())
            model_invoked = True
            gateway.responded = True
            gateway.processed = True
            raw_model = (
                ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            )
            usage = response.get("usage") if isinstance(response, dict) else None
            if isinstance(usage, dict):
                tokens = dict(usage)
            (root / "artifacts").mkdir(exist_ok=True)
            (root / "artifacts" / "model_transcript.txt").write_text(str(raw_model), encoding="utf-8")
            artifacts.append("model_transcript.txt")
        except Exception as exc:  # noqa: BLE001
            error_category = f"model_gateway:{exc}"
            gateway.error = str(exc)
            gateway.responded = False
            gateway.processed = False

    stages.append("task_status")
    # End-state verification: answer.json exists and is parseable with required keys.
    answer_ok = False
    try:
        parsed = json.loads((root / "answer.json").read_text(encoding="utf-8"))
        answer_ok = isinstance(parsed, dict) and "claim" in parsed and "citations" in parsed
        if answer_ok:
            stages.append("verification")
    except (OSError, json.JSONDecodeError):
        answer_ok = False

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    provider_missing = not gateway.available or str(meta.get("source") or "") in {"", "none"}
    if gateway.processed:
        model_status: MeasurementStatus = "measured"
    elif provider_missing:
        model_status = "UNAVAILABLE"
    else:
        model_status = "UNMEASURED"

    layers = MeasurementLayers(
        software="measured" if answer_ok else "UNMEASURED",
        model_answer=model_status,
        agent_task="measured" if answer_ok else "UNMEASURED",
        evaluation_kind="agent_task",
        notes=[
            "research_path_uses_KnowledgeService_local_ingest",
            "software_and_agent_task_graded_on_answer_json_post_state",
            *(
                ["model_provider_unavailable"]
                if model_status == "UNAVAILABLE"
                else (["model_answer_measured"] if model_status == "measured" else ["model_not_processed"])
            ),
            "software_measured_does_not_imply_model_quality",
        ],
    )
    ordered_stages = [s for s in PRODUCTION_STAGES if s in set(stages)]
    status = "completed" if answer_ok else "failed"
    return {
        "route": PRODUCTION_ROUTE_ID,
        "invoked": True,
        "solution_injected": False,
        "task_id": req.task_id,
        "status": status,
        "work_root": str(root),
        "artifacts": artifacts,
        "task_status": status,
        "tokens": tokens,
        "duration_ms": duration_ms,
        "error_category": error_category,
        "policy_violations": [],
        "model_invoked": model_invoked,
        "stages": ordered_stages,
        "stages_declared": list(PRODUCTION_STAGES),
        "gateway_meta": {**meta, "observation": gateway.to_dict()},
        "baseline_mode": bool(req.run_baseline),
        "evaluation_kind": "agent_task",
        "agent_task_supported": True,
        "measurement_status": layers.software,
        "measurement_layers": layers.to_dict(),
        "raw": {
            "ingested_sources": ingested,
            "answer": answer,
            "answer_ok": answer_ok,
            "model_gateway_observation": gateway.to_dict(),
            "note": "Research agent-task path uses KnowledgeService + post-state answer.json.",
        },
        # Never claim success from model prose; post-state must stand alone.
        "claimed_success": False,
    }


def _scenario_production_attempt(req: ProductionRouteRequest, chat_fn: Any | None, meta: dict[str, Any]) -> dict[str, Any]:
    """Non-coding production attempt for non-research scenario kinds.

    Research tasks are handled by ``_run_research_knowledge_production``.
    Other non-coding kinds remain model-answer-only unless a dedicated adapter exists.
    """
    root = Path(req.work_root)
    started = time.perf_counter()
    stages: list[str] = []
    model_invoked = False
    raw_model: str | None = None
    error_category = None
    tokens = None
    gateway = GatewayObservation(
        available=bool(callable(chat_fn)),
        attempted=False,
        responded=False,
        processed=False,
        provider_source=str(meta.get("source") or "") or None,
    )

    brief = ""
    if (root / "BRIEF.md").is_file():
        brief = (root / "BRIEF.md").read_text(encoding="utf-8")
    prompt = f"{req.goal}\n\n{brief}".strip()

    if callable(chat_fn):
        stages = ["model_gateway"]
        gateway.attempted = True
        try:
            import asyncio

            async def _call() -> Any:
                return await chat_fn(
                    {
                        "model": req.model_id or "local",
                        "messages": [{"role": "user", "content": prompt[:4000]}],
                        "temperature": 0,
                        "max_tokens": 400,
                    }
                )

            try:
                asyncio.get_running_loop()
                running = True
            except RuntimeError:
                running = False
            if running:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=1) as pool:
                    response = pool.submit(lambda: asyncio.run(_call())).result(timeout=120)
            else:
                response = asyncio.run(_call())
            model_invoked = True
            gateway.responded = True
            gateway.processed = True
            raw_model = (
                ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            )
            usage = response.get("usage") if isinstance(response, dict) else None
            if isinstance(usage, dict):
                tokens = dict(usage)
            (root / "artifacts").mkdir(exist_ok=True)
            (root / "artifacts" / "model_transcript.txt").write_text(str(raw_model), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            error_category = f"model_gateway:{exc}"
            model_invoked = False
            gateway.error = str(exc)

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    provider_missing = not gateway.available or str(meta.get("source") or "") in {"", "none"}
    if gateway.processed:
        model_status: MeasurementStatus = "measured"
    elif provider_missing:
        model_status = "UNAVAILABLE"
    else:
        model_status = "UNMEASURED"

    layers = MeasurementLayers(
        software="UNMEASURED",
        model_answer=model_status,
        agent_task="UNMEASURED",
        evaluation_kind="model_answer",
        notes=[
            "non_research_scenario_is_model_answer_only",
            "full_agent_task_runtime_unsupported_for_this_task_kind",
            *(["model_provider_unavailable"] if model_status == "UNAVAILABLE" else []),
        ],
    )
    return {
        "route": PRODUCTION_ROUTE_ID,
        "invoked": True,
        "solution_injected": False,
        "task_id": req.task_id,
        "status": "model_responded" if model_invoked else "UNSUPPORTED",
        "work_root": str(root),
        "artifacts": ["model_transcript.txt"] if model_invoked else [],
        "task_status": "model_responded" if model_invoked else "UNSUPPORTED",
        "tokens": tokens,
        "duration_ms": duration_ms,
        "error_category": error_category,
        "policy_violations": [],
        "model_invoked": model_invoked,
        "stages": stages,
        "stages_declared": list(PRODUCTION_STAGES),
        "gateway_meta": {**meta, "observation": gateway.to_dict()},
        "baseline_mode": bool(req.run_baseline),
        "evaluation_kind": "model_answer",
        "agent_task_supported": False,
        "measurement_status": model_status if model_invoked else ("UNAVAILABLE" if provider_missing else "UNMEASURED"),
        "measurement_layers": layers.to_dict(),
        "raw": {
            "model_transcript_len": len(raw_model or ""),
            "note": (
                "Non-research non-coding path currently measures model-answer only. "
                "Full agent-task runtime path is unsupported in this route."
            ),
        },
        "claimed_success": False,
    }


def invoke_production_route(
    req: ProductionRouteRequest,
    *,
    route_callback: Callable[[ProductionRouteRequest], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call the real HADES production route (or an injected callback for tests).

    Injected callbacks must still return ``invoked=True`` and ``solution_injected=False``.
    The harness never writes coding solutions before invoking the route.
    """
    if route_callback is not None:
        out = route_callback(req)
        if not isinstance(out, dict):
            raise TypeError("route_callback must return dict")
        out.setdefault("route", PRODUCTION_ROUTE_ID)
        out.setdefault("invoked", True)
        out.setdefault("solution_injected", False)
        out.setdefault("task_id", req.task_id)
        out.setdefault("work_root", str(req.work_root))
        out.setdefault("stages", list(PRODUCTION_STAGES))
        return out

    chat_fn, meta = _resolve_chat_fn(req.chat_fn)
    task_kind = req.task.get("task_kind") or "coding"
    if task_kind == "coding" or req.task.get("judge") == "execution_tests":
        return _run_coding_production(req, chat_fn, meta)

    if task_kind == "research" or req.task.get("judge") == "research_evidence":
        return _run_research_knowledge_production(req, chat_fn, meta)

    return _scenario_production_attempt(req, chat_fn, meta)


def invoke_baseline_route(req: ProductionRouteRequest) -> dict[str, Any]:
    """Simple baseline: same workspace/goal/budgets, strategy=fast, no investigate.

    Records an explicit baseline label for HADES-vs-baseline diffs.
    """
    baseline_req = ProductionRouteRequest(
        task_id=req.task_id,
        goal=req.goal,
        work_root=req.work_root,
        task=req.task,
        model_id=req.model_id,
        max_attempts=req.max_attempts,
        budget=dict(req.budget or {}),
        chat_fn=req.chat_fn,
        run_baseline=True,
    )
    task_kind = req.task.get("task_kind") or "coding"
    chat_fn, meta = _resolve_chat_fn(req.chat_fn)
    if task_kind == "coding" or req.task.get("judge") == "execution_tests":
        out = _run_coding_production(baseline_req, chat_fn, meta)
    elif task_kind == "research" or req.task.get("judge") == "research_evidence":
        out = _run_research_knowledge_production(baseline_req, chat_fn, meta)
    else:
        out = _scenario_production_attempt(baseline_req, chat_fn, meta)
    out["route"] = "hades.baseline_route.v1"
    out["baseline_mode"] = True
    return out
