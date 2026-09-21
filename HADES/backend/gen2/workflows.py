"""Gen2 Workflows — first-class IR, versioning, dry/sandbox/product run, promotion.

Honesty:
- dry-run never claims live execution.
- sandbox-run uses skill_runtime primitives only (heritage/demo); never product-ready.
- product-run uses real CodingAgent / ResearchRunner / PluginManager / gateway /
  ArtifactService adapters via workflow_executor.
- Promotion for product workflows requires passed product evidence + definition hash.
Offline-first: templates and NL draft work without network/LM.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Callable

from gen2 import agent_factory as agent_factory_mod
from gen2.skill_runtime import (
    PLACEHOLDER_NAMES,
    SKILL_ACTION_HANDLERS,
    execute_skill_step,
)
from gen2.store import Gen2Store, utc_now
from gen2.workflow_adapters import PRODUCT_ACTIONS, workflow_definition_hash
from gen2.workflow_executor import (
    execute_sandbox,
    is_product_workflow,
    request_cancel,
    request_pause,
    request_resume,
    start_product_run,
)

RecordFn = Callable[..., dict[str, Any]]
ChatFn = Callable[[str], str]

WORKFLOW_STATUSES = frozenset({"draft", "tested", "promoted", "archived"})
HITL_STEP_TYPES = frozenset({"approve", "choose", "provide_secret"})
ACTION_STEP_TYPES = frozenset({"action", "skill", "handler", ""})
PERMISSION_KEYS = frozenset({"network", "filesystem", "subprocess", "autonomous"})
PERMISSION_VALUES = frozenset({"deny", "ask", "allow", "offline_only"})
HADES_WORKFLOW_FORMAT = "HadesWorkflow"
HADES_WORKFLOW_FORMAT_VERSION = 1

WORKFLOW_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"tested", "archived", "draft"},
    "tested": {"promoted", "draft", "archived", "tested"},
    "promoted": {"tested", "draft", "archived"},
    "archived": set(),
}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _topo_order(steps: list[dict[str, Any]]) -> list[str]:
    """Return step ids in dependency order (deps first). Raises ValueError on cycle."""
    deps_map: dict[str, list[str]] = {
        str(s["id"]): [str(d) for d in (s.get("depends_on") or [])] for s in steps if s.get("id")
    }
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError(f"dependency cycle involving:{node}")
        if node in visited:
            return
        visiting.add(node)
        for dep in deps_map.get(node, []):
            if dep in deps_map:
                visit(dep)
        visiting.remove(node)
        visited.add(node)
        ordered.append(node)

    for sid in deps_map:
        visit(sid)
    return ordered


def validate_workflow(ir: dict[str, Any]) -> list[str]:
    """Return human-readable Workflow IR validation errors (empty = valid)."""
    errors: list[str] = []
    ir = ir or {}
    name = str(ir.get("name") or "").strip()
    if not name:
        errors.append("name missing")
    status = str(ir.get("status") or "draft").strip()
    if status not in WORKFLOW_STATUSES:
        errors.append(f"invalid status:{status}")
    steps = list(ir.get("steps") or [])
    if not steps:
        errors.append("steps missing")
        return errors

    ids: list[str] = []
    deps_map: dict[str, list[str]] = {}
    for step in steps:
        if not isinstance(step, dict):
            errors.append("step must be an object")
            continue
        sid = str(step.get("id") or "").strip()
        if not sid:
            errors.append("step missing id")
            continue
        if sid in ids:
            errors.append(f"duplicate step id:{sid}")
        ids.append(sid)
        deps = [str(d) for d in (step.get("depends_on") or [])]
        deps_map[sid] = deps
        stype = str(step.get("type") or "action").strip().lower()
        if stype in HITL_STEP_TYPES:
            continue
        if stype not in ACTION_STEP_TYPES and stype not in {"tool", "check"}:
            errors.append(f"step {sid} unknown type:{stype}")
        action = str(step.get("action") or step.get("op") or step.get("name") or "").strip()
        if not action and stype in ACTION_STEP_TYPES:
            errors.append(f"step {sid} missing action")
        elif action.lower() in PLACEHOLDER_NAMES:
            errors.append(f"step {sid} placeholder action rejected:{action}")
        elif action and action not in SKILL_ACTION_HANDLERS and action not in PRODUCT_ACTIONS:
            # Unknown actions are allowed in draft IR but flagged for dry-run honesty.
            # Validation does not reject — execution modes enforce resolvability.
            pass
        tools = step.get("tools")
        if tools is not None and not isinstance(tools, list):
            errors.append(f"step {sid} tools must be a list")

    known = set(ids)
    for sid, deps in deps_map.items():
        for dep in deps:
            if dep not in known:
                errors.append(f"step {sid} depends on unknown:{dep}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in deps_map.get(node, []):
            if visit(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    for sid in ids:
        if visit(sid):
            errors.append(f"dependency cycle involving:{sid}")
            break

    inputs_schema = ir.get("inputs_schema")
    if inputs_schema is not None and not isinstance(inputs_schema, dict):
        errors.append("inputs_schema must be an object")
    success_checks = ir.get("success_checks")
    if success_checks is not None and not isinstance(success_checks, list):
        errors.append("success_checks must be a list")
    permissions = ir.get("permissions")
    if permissions is not None:
        if not isinstance(permissions, dict):
            errors.append("permissions must be an object")
        else:
            for key, val in permissions.items():
                if str(key) not in PERMISSION_KEYS:
                    errors.append(f"unknown permission key:{key}")
                if str(val) not in PERMISSION_VALUES:
                    errors.append(f"invalid permission value for {key}:{val}")
    if "offline_safe" in ir and not isinstance(ir.get("offline_safe"), bool):
        errors.append("offline_safe must be a boolean")
    # Offline-safe workflows cannot allow network.
    if ir.get("offline_safe") is True:
        net = str((_as_dict(permissions).get("network") or "deny")).lower()
        if net == "allow":
            errors.append("offline_safe workflow cannot allow network")
    return errors


def normalize_workflow_ir(ir: dict[str, Any] | None, *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fill typed Workflow IR defaults without inventing fake success."""
    base = dict(defaults or {})
    raw = dict(ir or {})
    merged = {**base, **raw}
    steps = []
    for step in list(merged.get("steps") or []):
        if not isinstance(step, dict):
            continue
        stype = str(step.get("type") or "action").strip().lower() or "action"
        normalized = {
            "id": str(step.get("id") or "").strip(),
            "type": stype,
            "action": str(step.get("action") or step.get("op") or step.get("name") or "").strip(),
            "inputs": dict(step.get("inputs") or {}),
            "depends_on": [str(d) for d in (step.get("depends_on") or [])],
            "description": str(step.get("description") or step.get("label") or "").strip(),
            "success_criteria": list(step.get("success_criteria") or step.get("success") or []),
            "tools": list(step.get("tools") or []),
        }
        if stype in HITL_STEP_TYPES:
            normalized["prompt"] = str(step.get("prompt") or step.get("description") or stype)
            if stype == "choose":
                normalized["choices"] = list(step.get("choices") or [])
        steps.append(normalized)
    version = int(merged.get("version") or 1)
    return {
        "id": str(merged.get("id") or ""),
        "name": str(merged.get("name") or "untitled").strip() or "untitled",
        "description": str(merged.get("description") or "").strip(),
        "version": version,
        "status": str(merged.get("status") or "draft"),
        "steps": steps,
        "inputs_schema": dict(merged.get("inputs_schema") or {}),
        "success_checks": list(merged.get("success_checks") or []),
        "permissions": dict(merged.get("permissions") or {"network": "deny", "filesystem": "ask"}),
        "offline_safe": bool(merged.get("offline_safe", True)),
        "metrics": dict(merged.get("metrics") or {}),
        "draft_source": str(merged.get("draft_source") or "manual"),
        "human_approved": bool(merged.get("human_approved", False)),
        "pattern_tags": list(merged.get("pattern_tags") or []),
        "test_evidence": dict(merged.get("test_evidence") or {}),
        "skill_candidate_id": merged.get("skill_candidate_id"),
        "awaiting_human": merged.get("awaiting_human"),
        "active_run_id": merged.get("active_run_id"),
        "fixture_kind": str(merged.get("fixture_kind") or "").strip(),
        "timeout_seconds": merged.get("timeout_seconds"),
    }


def _base_template(
    *,
    name: str,
    description: str,
    steps: list[dict[str, Any]],
    tags: list[str],
    offline_safe: bool = True,
    permissions: dict[str, Any] | None = None,
    success_checks: list[str] | None = None,
    inputs_schema: dict[str, Any] | None = None,
    fixture_kind: str = "",
) -> dict[str, Any]:
    return normalize_workflow_ir(
        {
            "name": name,
            "description": description,
            "version": 1,
            "status": "draft",
            "steps": steps,
            "inputs_schema": inputs_schema
            or {"goal": {"type": "string", "required": True}, "context": {"type": "object"}},
            "success_checks": success_checks
            or ["all_steps_passed", "artifacts_recorded"],
            "permissions": permissions
            or {"network": "deny" if offline_safe else "ask", "filesystem": "ask"},
            "offline_safe": offline_safe,
            "metrics": {},
            "draft_source": "template",
            "human_approved": False,
            "pattern_tags": tags,
            "fixture_kind": fixture_kind,
        }
    )


def template_research_demo() -> dict[str, Any]:
    """Heritage/demo fixture — skill_runtime primitives only (not product research)."""
    return _base_template(
        name="research_demo",
        description="HERITAGE DEMO: Retrieve evidence via primitives only (not ResearchRunner).",
        tags=["research", "evidence", "heritage", "demo", "heritage_demo"],
        fixture_kind="heritage_demo",
        steps=[
            {
                "id": "scope",
                "type": "action",
                "action": "echo",
                "inputs": {"message": "scope research goal"},
                "depends_on": [],
                "description": "Scope the research question",
            },
            {
                "id": "assert_findings",
                "type": "action",
                "action": "assert_nonempty",
                "inputs": {"value": "evidence"},
                "depends_on": ["scope"],
                "description": "Require non-empty evidence payload",
            },
            {
                "id": "record",
                "type": "action",
                "action": "record_artifact",
                "inputs": {"name": "research_notes", "content": "research findings summary"},
                "depends_on": ["assert_findings"],
                "description": "Persist research artifact",
            },
            {
                "id": "approve_publish",
                "type": "approve",
                "action": "",
                "depends_on": ["record"],
                "prompt": "Approve publishing research summary?",
                "description": "Human approval before publish",
            },
        ],
        success_checks=["all_steps_passed", "artifacts_recorded", "human_approved_if_required"],
    )


def template_research() -> dict[str, Any]:
    """Product research workflow — ResearchRunner + ArtifactService."""
    return _base_template(
        name="research",
        description="Product research via ResearchRunner on local source fixtures; durable report with provenance.",
        tags=["research", "evidence", "product"],
        fixture_kind="product",
        permissions={"network": "deny", "filesystem": "allow"},
        offline_safe=True,
        inputs_schema={
            "topic": {"type": "string", "required": True},
            "source_inputs": {"type": "array", "required": True},
            "depth": {"type": "string", "required": False},
        },
        steps=[
            {
                "id": "scope",
                "type": "action",
                "action": "echo",
                "inputs": {"message": "{{inputs.topic}}"},
                "depends_on": [],
                "description": "Record research topic",
            },
            {
                "id": "run_research",
                "type": "action",
                "action": "research_runner",
                "inputs": {
                    "topic": "{{inputs.topic}}",
                    "source_inputs": "{{inputs.source_inputs}}",
                    "depth": "{{inputs.depth}}",
                    "allow_web": False,
                },
                "depends_on": ["scope"],
                "description": "Execute ResearchRunner on local fixtures",
                "success_criteria": ["output:ok", "output:project_id"],
            },
            {
                "id": "persist_report",
                "type": "action",
                "action": "artifact_persist",
                "inputs": {
                    "name": "research_workflow_report.md",
                    "content": "{{steps.run_research.outputs.report}}",
                    "project_id": "{{steps.run_research.outputs.project_id}}",
                },
                "depends_on": ["run_research"],
                "description": "Durable ArtifactService report with provenance",
            },
        ],
        success_checks=["all_steps_passed", "artifacts_recorded"],
    )


def template_coding_demo() -> dict[str, Any]:
    """Heritage/demo fixture — skill_runtime primitives only (not CodingAgent)."""
    return _base_template(
        name="coding_demo",
        description="HERITAGE DEMO: Plan → flags → fake artifact (not CodingAgent).",
        tags=["coding", "implementation", "heritage", "demo", "heritage_demo"],
        fixture_kind="heritage_demo",
        steps=[
            {
                "id": "plan",
                "type": "action",
                "action": "echo",
                "inputs": {"message": "coding plan ready"},
                "depends_on": [],
            },
            {
                "id": "mark_ready",
                "type": "action",
                "action": "set_ctx_flag",
                "inputs": {"flag": "code_ready"},
                "depends_on": ["plan"],
            },
            {
                "id": "verify_ready",
                "type": "action",
                "action": "check_ctx_flag",
                "inputs": {"flag": "code_ready"},
                "depends_on": ["mark_ready"],
            },
            {
                "id": "artifact",
                "type": "action",
                "action": "record_artifact",
                "inputs": {"name": "patch_notes", "content": "coding changes applied"},
                "depends_on": ["verify_ready"],
            },
        ],
    )


def template_coding() -> dict[str, Any]:
    """Product coding workflow — CodingAgent repair loop in isolated worktree."""
    return _base_template(
        name="coding",
        description="Product coding via CodingAgent: repair failing tests in an isolated repo worktree.",
        tags=["coding", "implementation", "product"],
        fixture_kind="product",
        permissions={"network": "deny", "filesystem": "allow"},
        offline_safe=True,
        inputs_schema={
            "goal": {"type": "string", "required": True},
            "source_repo": {"type": "string", "required": True},
            "test_args": {"type": "array", "required": False},
        },
        steps=[
            {
                "id": "plan",
                "type": "action",
                "action": "echo",
                "inputs": {"message": "{{inputs.goal}}"},
                "depends_on": [],
                "description": "Capture coding goal",
            },
            {
                "id": "repair",
                "type": "action",
                "action": "coding_agent",
                "inputs": {
                    "goal": "{{inputs.goal}}",
                    "source_repo": "{{inputs.source_repo}}",
                    "test_args": "{{inputs.test_args}}",
                    "test_suite": "unittest",
                    "max_attempts": 3,
                    "auto_repair": True,
                    "strategy": "fast",
                },
                "depends_on": ["plan"],
                "description": "CodingAgent isolated repair + verify",
                "success_criteria": ["output:ok"],
            },
            {
                "id": "record",
                "type": "action",
                "action": "artifact_persist",
                "inputs": {
                    "name": "coding_patch_notes.txt",
                    "content": "{{steps.repair.outputs.coding_summary}}",
                },
                "depends_on": ["repair"],
                "description": "Persist coding summary artifact",
            },
        ],
        success_checks=["all_steps_passed", "artifacts_recorded"],
    )


def template_ingest() -> dict[str, Any]:
    return _base_template(
        name="ingest",
        description="HERITAGE DEMO: Ingest local files into knowledge with offline-safe handlers.",
        tags=["ingest", "knowledge", "files", "heritage", "demo"],
        fixture_kind="heritage_demo",
        steps=[
            {
                "id": "announce",
                "type": "action",
                "action": "echo",
                "inputs": {"message": "begin ingest"},
                "depends_on": [],
            },
            {
                "id": "require_path",
                "type": "action",
                "action": "assert_nonempty",
                "inputs": {"value": "local_path"},
                "depends_on": ["announce"],
            },
            {
                "id": "store",
                "type": "action",
                "action": "record_artifact",
                "inputs": {"name": "ingest_manifest", "content": "files ingested locally"},
                "depends_on": ["require_path"],
            },
        ],
        permissions={"network": "deny", "filesystem": "ask"},
        offline_safe=True,
    )


def template_eval() -> dict[str, Any]:
    return _base_template(
        name="eval",
        description="HERITAGE DEMO: Run deterministic eval checks and record scores.",
        tags=["eval", "quality", "heritage", "demo"],
        fixture_kind="heritage_demo",
        steps=[
            {
                "id": "start",
                "type": "action",
                "action": "echo",
                "inputs": {"message": "eval suite start"},
                "depends_on": [],
            },
            {
                "id": "assert_suite",
                "type": "action",
                "action": "assert_nonempty",
                "inputs": {"value": "suite"},
                "depends_on": ["start"],
            },
            {
                "id": "scores",
                "type": "action",
                "action": "record_artifact",
                "inputs": {"name": "eval_scores", "content": "pass_rate recorded"},
                "depends_on": ["assert_suite"],
            },
        ],
    )


def template_paper_trade_study() -> dict[str, Any]:
    return _base_template(
        name="paper_trade_study",
        description="PAPER-only trade study: hypothesis → checks → artifact (no live orders).",
        tags=["finance", "paper_trade", "study", "heritage", "demo"],
        fixture_kind="heritage_demo",
        offline_safe=True,
        permissions={"network": "deny", "filesystem": "ask"},
        steps=[
            {
                "id": "hypothesis",
                "type": "action",
                "action": "echo",
                "inputs": {"message": "paper trade hypothesis"},
                "depends_on": [],
            },
            {
                "id": "mark_paper",
                "type": "action",
                "action": "set_ctx_flag",
                "inputs": {"flag": "paper_only"},
                "depends_on": ["hypothesis"],
            },
            {
                "id": "verify_paper",
                "type": "action",
                "action": "check_ctx_flag",
                "inputs": {"flag": "paper_only"},
                "depends_on": ["mark_paper"],
            },
            {
                "id": "report",
                "type": "action",
                "action": "record_artifact",
                "inputs": {"name": "paper_study", "content": "paper trade study complete — no live orders"},
                "depends_on": ["verify_paper"],
            },
            {
                "id": "choose_next",
                "type": "choose",
                "action": "",
                "depends_on": ["report"],
                "prompt": "Next action for paper study?",
                "choices": ["archive", "extend", "promote_to_skill"],
            },
        ],
        success_checks=["all_steps_passed", "paper_only", "no_live_orders"],
    )


TEMPLATE_LIBRARY: dict[str, Callable[[], dict[str, Any]]] = {
    "research": template_research,
    "coding": template_coding,
    "research_demo": template_research_demo,
    "coding_demo": template_coding_demo,
    "ingest": template_ingest,
    "eval": template_eval,
    "paper_trade_study": template_paper_trade_study,
}


def list_templates() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, factory in TEMPLATE_LIBRARY.items():
        ir = factory()
        out.append(
            {
                "id": key,
                "name": ir.get("name") or key,
                "description": ir.get("description") or "",
                "pattern_tags": list(ir.get("pattern_tags") or []),
                "offline_safe": bool(ir.get("offline_safe", True)),
                "fixture_kind": ir.get("fixture_kind") or "",
                "product": is_product_workflow(ir),
                "definition": ir,
            }
        )
    return out


def get_template(template_id: str) -> dict[str, Any]:
    factory = TEMPLATE_LIBRARY.get(str(template_id or "").strip())
    if not factory:
        raise ValueError(f"unknown template:{template_id}")
    return factory()


def _keyword_template_id(goal: str) -> str:
    text = (goal or "").lower()
    rules = [
        ("paper_trade_study", ("paper-trade", "paper trade", "paper_trade", "trading study", "backtest")),
        ("research", ("research", "evidence", "investigate", "literature")),
        ("coding", ("coding", "code", "implement", "refactor", "patch", "lsp")),
        ("coding_demo", ("coding demo", "heritage coding", "demo coding")),
        ("research_demo", ("research demo", "heritage research", "demo research")),
        ("ingest", ("ingest", "import file", "index file", "chunk", "knowledge ingest")),
        ("eval", ("eval", "benchmark", "quality suite", "regression suite")),
    ]
    for tid, keywords in rules:
        if any(k in text for k in keywords):
            return tid
    return "research"


def draft_from_nl(goal: str, *, chat_fn: ChatFn | None = None) -> dict[str, Any]:
    """Natural language → workflow draft. Offline-safe without chat_fn."""
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("goal required")

    if chat_fn is not None:
        prompt = (
            "Return ONLY JSON for a HADES workflow IR with keys: "
            "name, description, steps (id,type,action,inputs,depends_on), "
            "inputs_schema, success_checks, permissions, offline_safe. "
            f"Goal: {goal}"
        )
        raw = chat_fn(prompt)
        parsed = _parse_json_object(raw)
        if parsed is not None:
            ir = normalize_workflow_ir(
                parsed,
                defaults={
                    "name": parsed.get("name") or goal[:80],
                    "description": parsed.get("description") or goal,
                    "draft_source": "nl_lm",
                    "status": "draft",
                },
            )
            ir["draft_source"] = "nl_lm"
            ir["status"] = "draft"
            ir["human_approved"] = False
            errors = validate_workflow(ir)
            if not errors:
                return ir
            # Fall through to deterministic if LM JSON invalid.
            ir["draft_source"] = "nl_lm_invalid_fallback"
            ir["validation_errors"] = errors

    tid = _keyword_template_id(goal)
    ir = get_template(tid)
    ir = normalize_workflow_ir(
        {
            **ir,
            "name": f"{tid}:{goal[:60]}".strip(":"),
            "description": goal,
            "draft_source": "nl_deterministic",
            "status": "draft",
            "human_approved": False,
            "pattern_tags": list(ir.get("pattern_tags") or []) + ["nl_draft", tid],
        }
    )
    # Ensure first echo carries the goal for determinism/traceability.
    if ir["steps"] and ir["steps"][0].get("action") == "echo":
        ir["steps"][0]["inputs"] = {
            **dict(ir["steps"][0].get("inputs") or {}),
            "message": f"goal:{goal[:200]}",
        }
    return ir


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else None
        except Exception:
            return None
    return None


def create_workflow(
    store: Gen2Store,
    record: RecordFn,
    definition: dict[str, Any],
    *,
    note: str = "create",
) -> dict[str, Any]:
    ir = normalize_workflow_ir(definition)
    errors = validate_workflow(ir)
    if errors:
        raise ValueError("invalid workflow: " + "; ".join(errors))
    ir["status"] = "draft"
    ir["version"] = int(ir.get("version") or 1)
    # Let the store allocate id when caller did not supply one.
    create_values: dict[str, Any] = {
        "name": ir["name"],
        "status": "draft",
        "definition": {k: v for k, v in ir.items() if k != "id" or v},
        "metrics": ir.get("metrics") or {},
        "note": note,
    }
    if ir.get("id"):
        create_values["id"] = ir["id"]
    row = store.create_workflow(create_values)
    definition_out = dict(row.get("definition") or {})
    definition_out["id"] = row["id"]
    definition_out["status"] = row["status"]
    row = store.update_workflow(row["id"], definition=definition_out) or row
    record(row["id"], "RUN_CREATED", {"kind": "workflow", "name": row["name"]}, component="workflows")
    return row


def update_workflow(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    definition: dict[str, Any] | None = None,
    *,
    name: str | None = None,
    bump_version: bool = True,
    note: str = "update",
) -> dict[str, Any]:
    current = store.get_workflow(workflow_id)
    if not current:
        raise ValueError("workflow not found")
    if current.get("status") == "archived":
        raise ValueError("cannot update archived workflow")
    merged = normalize_workflow_ir(
        {**(current.get("definition") or {}), **(definition or {})},
    )
    if name:
        merged["name"] = name
    merged["id"] = workflow_id
    merged["status"] = str(current.get("status") or "draft")
    # Editing a promoted/tested workflow returns it to draft until re-tested.
    if merged["status"] in {"tested", "promoted"} and definition is not None:
        merged["status"] = "draft"
        merged["human_approved"] = False
    errors = validate_workflow(merged)
    if errors:
        raise ValueError("invalid workflow: " + "; ".join(errors))
    if bump_version:
        merged["version"] = int(current.get("version") or merged.get("version") or 1) + 1
        store.save_workflow_revision(workflow_id, merged, note=note, version=merged["version"])
    updated = store.update_workflow(
        workflow_id,
        name=merged["name"],
        status=merged["status"],
        definition=merged,
    )
    record(
        workflow_id,
        "STATUS_SYNC",
        {"status": merged["status"], "version": merged["version"], "note": note},
        component="workflows",
    )
    return updated or current


def soft_archive(store: Gen2Store, record: RecordFn, workflow_id: str) -> dict[str, Any]:
    current = store.get_workflow(workflow_id)
    if not current:
        raise ValueError("workflow not found")
    updated = store.archive_workflow(workflow_id)
    definition = dict((updated or current).get("definition") or {})
    definition["status"] = "archived"
    store.update_workflow(workflow_id, definition=definition)
    record(workflow_id, "STATUS_SYNC", {"status": "archived"}, component="workflows")
    return store.get_workflow(workflow_id) or current


def list_revisions(store: Gen2Store, workflow_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not store.get_workflow(workflow_id):
        raise ValueError("workflow not found")
    return store.list_workflow_revisions(workflow_id, limit=limit)


def diff_revisions(store: Gen2Store, workflow_id: str, from_version: int, to_version: int) -> dict[str, Any]:
    left = store.get_workflow_revision(workflow_id, int(from_version))
    right = store.get_workflow_revision(workflow_id, int(to_version))
    if not left or not right:
        raise ValueError("revision not found")
    a = normalize_workflow_ir(left.get("definition") or {})
    b = normalize_workflow_ir(right.get("definition") or {})
    changes: list[dict[str, Any]] = []
    for key in ("name", "description", "status", "offline_safe", "draft_source"):
        if a.get(key) != b.get(key):
            changes.append({"path": key, "from": a.get(key), "to": b.get(key)})
    if a.get("permissions") != b.get("permissions"):
        changes.append({"path": "permissions", "from": a.get("permissions"), "to": b.get("permissions")})
    if a.get("success_checks") != b.get("success_checks"):
        changes.append(
            {"path": "success_checks", "from": a.get("success_checks"), "to": b.get("success_checks")}
        )
    a_steps = {str(s["id"]): s for s in a.get("steps") or [] if s.get("id")}
    b_steps = {str(s["id"]): s for s in b.get("steps") or [] if s.get("id")}
    for sid in sorted(set(a_steps) | set(b_steps)):
        if sid not in a_steps:
            changes.append({"path": f"steps.{sid}", "from": None, "to": b_steps[sid], "op": "added"})
        elif sid not in b_steps:
            changes.append({"path": f"steps.{sid}", "from": a_steps[sid], "to": None, "op": "removed"})
        elif a_steps[sid] != b_steps[sid]:
            changes.append({"path": f"steps.{sid}", "from": a_steps[sid], "to": b_steps[sid], "op": "changed"})
    return {
        "workflow_id": workflow_id,
        "from_version": int(from_version),
        "to_version": int(to_version),
        "changes": changes,
        "change_count": len(changes),
    }


def _validate_permissions(ir: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    permissions = _as_dict(ir.get("permissions"))
    offline_safe = bool(ir.get("offline_safe", True))
    net = str(permissions.get("network") or "deny").lower()
    ok = not (offline_safe and net == "allow")
    checks.append(
        {
            "check": "permissions_offline_safe",
            "passed": ok,
            "detail": "ok" if ok else "offline_safe cannot allow network",
        }
    )
    for key, val in permissions.items():
        valid = str(key) in PERMISSION_KEYS and str(val) in PERMISSION_VALUES
        checks.append(
            {
                "check": f"permission:{key}",
                "passed": valid,
                "detail": "ok" if valid else f"invalid {key}={val}",
            }
        )
    return checks


def _evaluate_success_checks(ir: dict[str, Any], *, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Evaluate declared success_checks structurally (no side effects)."""
    ctx = ctx or {}
    results: list[dict[str, Any]] = []
    checks = list(ir.get("success_checks") or [])
    steps = list(ir.get("steps") or [])
    has_handlers = all(
        str(s.get("type") or "action") in HITL_STEP_TYPES
        or str(s.get("action") or "") in SKILL_ACTION_HANDLERS
        or str(s.get("action") or "") in PRODUCT_ACTIONS
        for s in steps
        if isinstance(s, dict)
    )
    for check in checks:
        name = str(check).strip()
        passed = False
        detail = ""
        if name in {"all_steps_passed", "handlers_resolvable"}:
            passed = has_handlers and bool(steps)
            detail = "handlers_ok" if passed else "unresolvable_or_empty"
        elif name == "artifacts_recorded":
            # Structural: workflow declares a record_artifact or artifact_persist step.
            passed = any(
                str(s.get("action") or "") in {"record_artifact", "artifact_persist"} for s in steps
            )
            detail = "artifact_step_present" if passed else "missing_artifact_step"
            if ctx.get("artifacts") is not None:
                passed = bool(ctx.get("artifacts"))
                detail = "artifacts_in_ctx" if passed else "no_artifacts_in_ctx"
        elif name == "human_approved_if_required":
            needs = any(str(s.get("type") or "") in HITL_STEP_TYPES for s in steps)
            passed = (not needs) or bool(ir.get("human_approved")) or bool(ctx.get("hitl_resolved"))
            detail = "not_required" if not needs else ("approved" if passed else "pending_human")
        elif name == "paper_only":
            passed = "paper" in str(ir.get("name") or "").lower() or "paper_only" in list(
                ir.get("pattern_tags") or []
            ) or bool(ctx.get("paper_only"))
            detail = "paper_constraint_ok" if passed else "not_marked_paper"
        elif name == "no_live_orders":
            live_actions = {"place_order", "live_trade", "broker_submit"}
            passed = not any(str(s.get("action") or "") in live_actions for s in steps)
            detail = "no_live_order_actions" if passed else "live_order_action_present"
        else:
            # Unknown named check: treat as declarative label — pass only if ctx flag set.
            passed = bool(ctx.get(name))
            detail = "ctx_flag" if passed else "unknown_check_unproven"
        results.append({"check": name, "passed": passed, "detail": detail})
    return results


def dry_run(store: Gen2Store, record: RecordFn, workflow_id: str) -> dict[str, Any]:
    """Validate + plan without side effects. Never claims live execution."""
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    ir = normalize_workflow_ir(row.get("definition") or {})
    errors = validate_workflow(ir)
    perm_checks = _validate_permissions(ir)
    success_checks = _evaluate_success_checks(ir)
    definition_hash = workflow_definition_hash(ir)
    try:
        order = _topo_order(list(ir.get("steps") or []))
        plan_error = None
    except ValueError as exc:
        order = []
        plan_error = str(exc)
        errors.append(plan_error)

    plan_steps = []
    for sid in order:
        step = next(s for s in ir["steps"] if s["id"] == sid)
        stype = str(step.get("type") or "action")
        action = str(step.get("action") or "")
        handler_known = None
        if stype not in HITL_STEP_TYPES:
            handler_known = action in SKILL_ACTION_HANDLERS or action in PRODUCT_ACTIONS
        plan_steps.append(
            {
                "id": sid,
                "type": stype,
                "action": action,
                "depends_on": list(step.get("depends_on") or []),
                "would_execute": stype not in HITL_STEP_TYPES,
                "human_required": stype in HITL_STEP_TYPES,
                "handler_known": handler_known,
                "product_adapter": action in PRODUCT_ACTIONS if stype not in HITL_STEP_TYPES else False,
            }
        )
    passed = (
        not errors
        and all(c["passed"] for c in perm_checks)
        and all(c["passed"] for c in success_checks if c["check"] != "human_approved_if_required")
    )
    hitl_pending = any(
        c["check"] == "human_approved_if_required" and not c["passed"] for c in success_checks
    )
    result = {
        "mode": "dry_run",
        "live_execution": False,
        "product_ready": False,
        "side_effects": False,
        "passed": passed,
        "validation_errors": errors,
        "permission_checks": perm_checks,
        "success_checks": success_checks,
        "definition_hash": definition_hash,
        "product_workflow": is_product_workflow(ir),
        "plan": {
            "step_order": order,
            "steps": plan_steps,
            "hitl_pending": hitl_pending,
        },
        "note": (
            "Dry-run validates schema/permissions/success_checks and returns an execution plan; "
            "no handlers or product adapters were invoked."
        ),
    }
    run = store.create_workflow_run(
        workflow_id=workflow_id,
        version=int(ir.get("version") or row.get("version") or 1),
        mode="dry_run",
        status="passed" if passed else "failed",
        result=result,
    )
    definition = dict(row.get("definition") or {})
    evidence = dict(definition.get("test_evidence") or {})
    evidence["last_dry_run_id"] = run["id"]
    evidence["last_dry_run_passed"] = passed
    evidence["last_dry_run_definition_hash"] = definition_hash
    definition["test_evidence"] = evidence
    store.update_workflow(workflow_id, definition=definition)
    record(
        workflow_id,
        "VERIFICATION",
        {"mode": "dry_run", "passed": passed, "run_id": run["id"], "definition_hash": definition_hash},
        component="workflows",
    )
    return {**result, "run_id": run["id"], "workflow_id": workflow_id}


def sandbox_run(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    *,
    run_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Isolated skill_runtime only. Never product-ready / live Coding|Research."""
    result = execute_sandbox(store, record, workflow_id, run_inputs=run_inputs)
    _update_aggregate_metrics(store, workflow_id)
    return result


def product_run(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    *,
    services: Any,
    run_inputs: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
    async_mode: bool = True,
    blocking: bool = False,
) -> dict[str, Any]:
    """Real product adapters. Long-running work is non-blocking unless blocking=True."""
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    ir = normalize_workflow_ir(row.get("definition") or {})
    timeout = timeout_seconds
    if timeout is None and ir.get("timeout_seconds") is not None:
        try:
            timeout = float(ir.get("timeout_seconds"))
        except (TypeError, ValueError):
            timeout = None
    result = start_product_run(
        store,
        record,
        workflow_id,
        services=services,
        run_inputs=run_inputs,
        timeout_seconds=timeout,
        async_mode=async_mode,
        blocking=blocking,
    )
    if blocking or result.get("status") not in {"queued", "running"}:
        _update_aggregate_metrics(store, workflow_id)
    return result


def decide_human_step(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    step_id: str,
    *,
    decision: str,
    value: Any = None,
    resume: bool = True,
    services: Any | None = None,
) -> dict[str, Any]:
    """Resolve HITL step (approve|choose|provide_secret) on an awaiting run."""
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    ir = normalize_workflow_ir(row.get("definition") or {})
    step = next((s for s in ir.get("steps") or [] if s.get("id") == step_id), None)
    if not step:
        raise ValueError("step not found")
    stype = str(step.get("type") or "")
    # Synthetic permission pause: product action parked as approve in awaiting_human.
    definition_preview = dict(row.get("definition") or {})
    evidence_preview = dict(definition_preview.get("test_evidence") or {})
    awaiting_preview = evidence_preview.get("awaiting_step") or {}
    synthetic_approve = (
        stype not in HITL_STEP_TYPES
        and isinstance(awaiting_preview, dict)
        and str(awaiting_preview.get("step_id") or "") == step_id
        and str(awaiting_preview.get("type") or "") == "approve"
    )
    if stype not in HITL_STEP_TYPES and not synthetic_approve:
        raise ValueError("step is not a human-in-the-loop step")
    if synthetic_approve:
        stype = "approve"

    decision_norm = str(decision or "").strip().lower()
    if stype == "approve":
        if decision_norm not in {"approve", "approved", "reject", "rejected", "deny"}:
            raise ValueError("approve step requires decision approve|reject")
        approved = decision_norm in {"approve", "approved"}
        decision_payload = {"decision": "approved" if approved else "rejected", "value": value}
    elif stype == "choose":
        choices = list(step.get("choices") or [])
        chosen = value if value is not None else decision
        if choices and chosen not in choices:
            raise ValueError(f"choice must be one of: {choices}")
        decision_payload = {"decision": "chosen", "value": chosen}
        approved = True
    else:  # provide_secret
        secret = value if value is not None else decision
        if secret is None or str(secret).strip() == "":
            raise ValueError("provide_secret requires a non-empty value")
        decision_payload = {"decision": "secret_provided", "value_present": True}
        approved = True

    # Sync durable ApprovalService decision when the pause carried an approval_request_id.
    approval_request_id = None
    if isinstance(awaiting_preview, dict):
        approval_request_id = awaiting_preview.get("approval_request_id") or awaiting_preview.get("approval_id")
    if approval_request_id and services is not None and getattr(services, "approval_service", None) is not None:
        try:
            services.approval_service.decide(
                str(approval_request_id),
                approve=bool(approved),
                note="workflow HITL decide",
            )
        except Exception:
            # HITL decision still proceeds; product resume validates approval_id fail-closed.
            pass

    definition = dict(row.get("definition") or {})
    evidence = dict(definition.get("test_evidence") or {})
    hitl = dict(evidence.get("hitl_decisions") or {})
    hitl[step_id] = {**decision_payload, "at": utc_now()}
    evidence["hitl_decisions"] = hitl
    if stype == "approve" and approved:
        definition["human_approved"] = True
    definition["test_evidence"] = evidence
    store.update_workflow(workflow_id, definition=definition)

    run_id = evidence.get("awaiting_run_id")
    run = store.get_workflow_run(str(run_id)) if run_id else None
    run_mode = str((run or {}).get("mode") or "sandbox")
    if run and str(run.get("status")) == "awaiting_human":
        result = dict(run.get("result") or {})
        result["human_decision"] = {"step_id": step_id, **decision_payload}
        if not approved and stype == "approve":
            result["status"] = "failed"
            result["passed"] = False
            store.update_workflow_run(run["id"], status="failed", result=result)
            record(workflow_id, "STATUS_SYNC", {"hitl": "rejected", "step_id": step_id}, component="workflows")
            return {
                "workflow_id": workflow_id,
                "step_id": step_id,
                "status": "failed",
                "decision": decision_payload,
                "run_id": run["id"],
            }
        result["status"] = "human_resolved"
        result["awaiting_human"] = None
        store.update_workflow_run(run["id"], status="human_resolved", result=result)

    record(
        workflow_id,
        "STATUS_SYNC",
        {"hitl": decision_payload.get("decision"), "step_id": step_id},
        component="workflows",
    )

    resume_result = None
    if resume and approved:
        if run_mode == "product" and services is not None:
            from gen2.workflow_executor import resume_product_after_hitl

            resume_result = resume_product_after_hitl(
                store, record, workflow_id, step_id, services=services, blocking=True
            )
        else:
            resume_result = _resume_after_hitl(store, record, workflow_id, step_id)

    return {
        "workflow_id": workflow_id,
        "step_id": step_id,
        "status": "resolved",
        "decision": decision_payload,
        "run_id": run["id"] if run else run_id,
        "resume": resume_result,
    }


def _resume_after_hitl(
    store: Gen2Store, record: RecordFn, workflow_id: str, resolved_step_id: str
) -> dict[str, Any]:
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    ir = normalize_workflow_ir(row.get("definition") or {})
    order = _topo_order(list(ir.get("steps") or []))
    if resolved_step_id not in order:
        return {"passed": False, "detail": "resolved_step_not_in_order"}
    start_at = order.index(resolved_step_id) + 1
    remaining = order[start_at:]
    ctx: dict[str, Any] = {"artifacts": [], "hitl_resolved": True, "steps": {}}
    steps_by_id = {str(s["id"]): s for s in ir["steps"]}
    for sid in order[: start_at - 1]:
        step = steps_by_id[sid]
        if str(step.get("type") or "action") in HITL_STEP_TYPES:
            continue
        action = str(step.get("action") or "")
        if action in PRODUCT_ACTIONS:
            continue
        execute_skill_step(
            {
                "action": step.get("action"),
                "inputs": step.get("inputs") or {},
                "success_criteria": step.get("success_criteria") or [],
            },
            ctx=ctx,
        )

    step_results: list[dict[str, Any]] = []
    tool_failures = 0
    status = "completed"
    passed = True
    awaiting_step = None
    for index, sid in enumerate(remaining, start=start_at):
        step = steps_by_id[sid]
        stype = str(step.get("type") or "action").lower()
        if stype in HITL_STEP_TYPES:
            decisions = ((row.get("definition") or {}).get("test_evidence") or {}).get("hitl_decisions") or {}
            if sid in decisions:
                step_results.append(
                    {
                        "index": index,
                        "id": sid,
                        "type": stype,
                        "passed": True,
                        "executed": False,
                        "detail": "human_already_decided",
                    }
                )
                continue
            awaiting_step = {"step_id": sid, "type": stype, "prompt": step.get("prompt") or stype}
            status = "awaiting_human"
            passed = False
            break
        action = str(step.get("action") or "")
        if action in PRODUCT_ACTIONS:
            step_results.append(
                {
                    "index": index,
                    "id": sid,
                    "type": stype,
                    "action": action,
                    "passed": False,
                    "executed": False,
                    "detail": "product_action_requires_product_mode",
                }
            )
            tool_failures += 1
            passed = False
            status = "failed"
            break
        result = execute_skill_step(
            {
                "action": step.get("action"),
                "inputs": step.get("inputs") or {},
                "success_criteria": step.get("success_criteria") or [],
            },
            index=index,
            ctx=ctx,
        )
        entry = result.to_dict()
        entry["id"] = sid
        entry["usage"] = {"source": "not_measured", "total_tokens": None}
        step_results.append(entry)
        if not result.passed:
            tool_failures += 1
            passed = False
            status = "failed"
            break

    result = {
        "mode": "sandbox",
        "live_execution": False,
        "product_ready": False,
        "passed": passed and status == "completed",
        "status": status,
        "step_results": step_results,
        "artifacts": list(ctx.get("artifacts") or []),
        "awaiting_human": awaiting_step,
        "resumed_after": resolved_step_id,
        "metrics": {
            "tool_failures": tool_failures,
            "cost_tokens": None,
            "usage": {"source": "not_measured", "total_tokens": None},
            "passed": passed and status == "completed",
        },
        "note": "Resumed sandbox after HITL decision.",
    }
    run = store.create_workflow_run(
        workflow_id=workflow_id,
        version=int(ir.get("version") or 1),
        mode="sandbox",
        status=status if status != "completed" else ("passed" if passed else "failed"),
        result=result,
    )
    definition = dict(row.get("definition") or {})
    evidence = dict(definition.get("test_evidence") or {})
    if status == "awaiting_human":
        evidence["awaiting_run_id"] = run["id"]
        evidence["awaiting_step"] = awaiting_step
    elif result["passed"]:
        evidence["last_sandbox_run_id"] = run["id"]
        evidence["last_sandbox_run_passed"] = True
        evidence.pop("awaiting_run_id", None)
        evidence.pop("awaiting_step", None)
    definition["test_evidence"] = evidence
    store.update_workflow(workflow_id, definition=definition)
    _update_aggregate_metrics(store, workflow_id)
    record(workflow_id, "VERIFICATION", {"mode": "sandbox_resume", "run_id": run["id"]}, component="workflows")
    return {**result, "run_id": run["id"]}


def _update_aggregate_metrics(store: Gen2Store, workflow_id: str) -> dict[str, Any]:
    runs = store.list_workflow_runs(workflow_id, limit=200)
    executable = [r for r in runs if r.get("mode") in {"sandbox", "product"}]
    if not executable:
        metrics = {
            "success_rate": 0.0,
            "latency_ms": 0,
            "tool_failures": 0,
            "cost_tokens": None,
            "usage": {"source": "not_measured", "total_tokens": None},
            "run_count": 0,
        }
        store.update_workflow(workflow_id, metrics=metrics)
        return metrics
    successes = 0
    latencies: list[int] = []
    tool_failures = 0
    measured_tokens = 0
    measured_runs = 0
    for run in executable:
        result = run.get("result") or {}
        m = result.get("metrics") or {}
        if result.get("passed") or run.get("status") == "passed":
            successes += 1
        latencies.append(int(m.get("latency_ms") or 0))
        tool_failures += int(m.get("tool_failures") or 0)
        usage = m.get("usage") if isinstance(m.get("usage"), dict) else {}
        if usage.get("source") == "measured" and usage.get("total_tokens") is not None:
            measured_tokens += int(usage["total_tokens"])
            measured_runs += 1
        elif m.get("cost_tokens") is not None:
            # Only accept non-null cost_tokens that came from measured usage.
            if usage.get("source") == "measured":
                measured_tokens += int(m["cost_tokens"])
                measured_runs += 1
    metrics = {
        "success_rate": round(successes / max(1, len(executable)), 4),
        "latency_ms": int(sum(latencies) / max(1, len(latencies))),
        "tool_failures": tool_failures,
        "cost_tokens": measured_tokens if measured_runs else None,
        "usage": (
            {"source": "measured", "total_tokens": measured_tokens}
            if measured_runs
            else {"source": "not_measured", "total_tokens": None}
        ),
        "run_count": len(executable),
        "sandbox_run_count": sum(1 for r in runs if r.get("mode") == "sandbox"),
        "product_run_count": sum(1 for r in runs if r.get("mode") == "product"),
        "dry_run_count": sum(1 for r in runs if r.get("mode") == "dry_run"),
    }
    store.update_workflow(workflow_id, metrics=metrics)
    definition = dict((store.get_workflow(workflow_id) or {}).get("definition") or {})
    definition["metrics"] = metrics
    store.update_workflow(workflow_id, definition=definition)
    return metrics


def workflow_metrics(store: Gen2Store, workflow_id: str) -> dict[str, Any]:
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    metrics = _update_aggregate_metrics(store, workflow_id)
    return {
        "workflow_id": workflow_id,
        "metrics": metrics,
        "runs": store.list_workflow_runs(workflow_id, limit=20),
    }


def promote_workflow(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    *,
    human_approved: bool = False,
    target: str | None = None,
) -> dict[str, Any]:
    """Promotion: draft→tested → promoted with hash-bound evidence.

    Product coding/research workflows require passed product-run evidence.
    Sandbox/heritage simulation alone cannot promote product workflows to Ready.
    """
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    current = str(row.get("status") or "draft")
    definition = normalize_workflow_ir(row.get("definition") or {})
    errors = validate_workflow(definition)
    if errors:
        raise ValueError("broken workflow cannot promote: " + "; ".join(errors))

    evidence = dict((row.get("definition") or {}).get("test_evidence") or {})
    current_hash = workflow_definition_hash(definition)
    product = is_product_workflow(definition)

    dry_ok = bool(evidence.get("last_dry_run_passed"))
    sand_ok = bool(evidence.get("last_sandbox_run_passed"))
    product_ok = bool(evidence.get("last_product_run_passed")) and bool(evidence.get("last_product_ready"))

    # Hash binding: evidence must match current definition.
    if dry_ok and evidence.get("last_dry_run_definition_hash") not in {None, current_hash}:
        dry_ok = False
    if sand_ok and evidence.get("last_sandbox_definition_hash") not in {None, current_hash}:
        sand_ok = False
    if product_ok and evidence.get("last_product_definition_hash") not in {None, current_hash}:
        product_ok = False

    if product:
        tested_ok = product_ok
    else:
        tested_ok = dry_ok or sand_ok

    if target:
        next_status = str(target)
    elif current == "draft":
        next_status = "tested"
    elif current == "tested":
        next_status = "promoted"
    elif current == "promoted":
        next_status = "promoted"
    else:
        raise ValueError(f"cannot promote from {current}")

    if next_status not in WORKFLOW_STATUSES:
        raise ValueError(f"invalid promotion target:{next_status}")
    if next_status not in WORKFLOW_TRANSITIONS.get(current, set()) and next_status != current:
        raise ValueError(f"illegal transition {current} → {next_status}")

    if next_status == "tested":
        if not tested_ok:
            if product:
                raise ValueError(
                    "tested requires passed product-run evidence for product workflows "
                    "(sandbox/demo simulation does not promote coding/research to Ready)"
                )
            raise ValueError("tested requires passed dry-run or sandbox-run")
    elif next_status == "promoted":
        if current not in {"tested", "promoted"}:
            raise ValueError("workflow must be tested before promotion")
        if not tested_ok:
            if product:
                raise ValueError("promoted requires passed product-run evidence bound to definition hash")
            raise ValueError("promoted requires passed dry-run or sandbox-run evidence")
        approved = human_approved or bool(definition.get("human_approved"))
        if not approved:
            raise ValueError("human approval required to promote workflow")
        definition["human_approved"] = True

    definition["status"] = next_status
    definition["test_evidence"] = {
        **evidence,
        "promoted_definition_hash": current_hash,
        "product_workflow": product,
    }
    updated = store.update_workflow(
        workflow_id,
        status=next_status,
        definition=definition,
        name=definition.get("name") or row.get("name"),
    )
    record(
        workflow_id,
        "RUN_COMPLETED",
        {
            "status": next_status,
            "from": current,
            "definition_hash": current_hash,
            "evidence": {
                "dry_ok": dry_ok,
                "sand_ok": sand_ok,
                "product_ok": product_ok,
                "product_workflow": product,
            },
        },
        component="workflows",
    )
    return updated or row


def cancel_workflow_run(run_id: str) -> dict[str, Any]:
    return request_cancel(run_id)


def pause_workflow_run(run_id: str) -> dict[str, Any]:
    return request_pause(run_id)


def resume_workflow_run(run_id: str) -> dict[str, Any]:
    return request_resume(run_id)


def rollback_workflow(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
    *,
    to_status: str = "tested",
    to_version: int | None = None,
) -> dict[str, Any]:
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    if to_status not in {"draft", "tested", "archived"}:
        raise ValueError("invalid rollback status")
    definition = dict(row.get("definition") or {})
    if to_version is not None:
        rev = store.get_workflow_revision(workflow_id, int(to_version))
        if not rev:
            raise ValueError("revision not found")
        definition = dict(rev.get("definition") or {})
        definition["version"] = int(to_version)
    definition["status"] = to_status
    if to_status != "promoted":
        definition["human_approved"] = False
    updated = store.update_workflow(
        workflow_id,
        status=to_status,
        definition=definition,
        name=definition.get("name") or row.get("name"),
    )
    record(
        workflow_id,
        "STATUS_SYNC",
        {"status": to_status, "reason": "rollback", "from": row.get("status"), "to_version": to_version},
        component="workflows",
    )
    return updated or row


def export_workflow(store: Gen2Store, workflow_id: str, *, as_zip: bool = False) -> dict[str, Any] | bytes:
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    package = {
        "format": HADES_WORKFLOW_FORMAT,
        "format_version": HADES_WORKFLOW_FORMAT_VERSION,
        "definition": normalize_workflow_ir(row.get("definition") or {}),
        "metadata": {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "version": row.get("version"),
            "metrics": row.get("metrics") or {},
            "exported_at": utc_now(),
        },
    }
    errors = validate_workflow(package["definition"])
    if errors:
        raise ValueError("cannot export invalid workflow: " + "; ".join(errors))
    if not as_zip:
        return package
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("workflow.json", json.dumps(package, ensure_ascii=False, indent=2))
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": HADES_WORKFLOW_FORMAT,
                    "format_version": HADES_WORKFLOW_FORMAT_VERSION,
                    "name": row["name"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return buf.getvalue()


def import_workflow(
    store: Gen2Store,
    record: RecordFn,
    package: dict[str, Any] | bytes | str,
) -> dict[str, Any]:
    data = _load_package(package)
    if data.get("format") != HADES_WORKFLOW_FORMAT:
        raise ValueError(f'package format must be "{HADES_WORKFLOW_FORMAT}"')
    if int(data.get("format_version") or 0) != HADES_WORKFLOW_FORMAT_VERSION:
        raise ValueError(f"unsupported format_version:{data.get('format_version')}")
    definition = normalize_workflow_ir(data.get("definition") or {})
    definition["status"] = "draft"
    definition["human_approved"] = False
    definition["draft_source"] = str(definition.get("draft_source") or "import")
    definition["version"] = 1
    definition.pop("id", None)
    errors = validate_workflow(definition)
    if errors:
        raise ValueError("import validation failed: " + "; ".join(errors))
    meta = _as_dict(data.get("metadata"))
    if meta.get("name") and not definition.get("name"):
        definition["name"] = meta["name"]
    return create_workflow(store, record, definition, note="import")


def _load_package(package: dict[str, Any] | bytes | str) -> dict[str, Any]:
    if isinstance(package, dict):
        return package
    raw: bytes
    if isinstance(package, str):
        text = package.strip()
        if text.startswith("{"):
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError("package JSON must be an object")
            return value
        raw = package.encode("utf-8")
    else:
        raw = package
    # Try zip first.
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
            names = zf.namelist()
            target = "workflow.json" if "workflow.json" in names else names[0]
            value = json.loads(zf.read(target).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("zip workflow.json must be an object")
            return value
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("package JSON must be an object")
    return value


def workflow_to_skill_candidate(
    store: Gen2Store,
    record: RecordFn,
    workflow_id: str,
) -> dict[str, Any]:
    """Bridge: extract Agent Factory skill candidate from workflow steps."""
    row = store.get_workflow(workflow_id)
    if not row:
        raise ValueError("workflow not found")
    ir = normalize_workflow_ir(row.get("definition") or {})
    errors = validate_workflow(ir)
    if errors:
        raise ValueError("cannot convert invalid workflow: " + "; ".join(errors))
    workflow_steps: list[Any] = []
    tools: list[str] = []
    for step in ir.get("steps") or []:
        stype = str(step.get("type") or "action")
        if stype in HITL_STEP_TYPES:
            # HITL is not an executable skill handler — skip for skill workflow list.
            continue
        action = str(step.get("action") or "").strip()
        if not action:
            continue
        entry: dict[str, Any] = {
            "action": action,
            "inputs": dict(step.get("inputs") or {}),
            "success_criteria": list(step.get("success_criteria") or []),
            "description": str(step.get("description") or ""),
        }
        workflow_steps.append(entry)
        for t in step.get("tools") or []:
            if t not in tools:
                tools.append(str(t))
    if not workflow_steps:
        raise ValueError("workflow has no executable steps for skill candidate")
    skill = agent_factory_mod.extract_skill_candidate(
        store,
        record,
        name=str(ir.get("name") or row.get("name") or workflow_id),
        workflow=workflow_steps,
        pattern_source=f"workflow:{workflow_id}",
        tools=tools,
    )
    # Link back on workflow definition.
    definition = dict(row.get("definition") or {})
    definition["skill_candidate_id"] = skill["id"]
    store.update_workflow(workflow_id, definition=definition)
    record(
        workflow_id,
        "STATUS_SYNC",
        {"bridged_skill_id": skill["id"], "pattern_source": f"workflow:{workflow_id}"},
        component="workflows",
    )
    return skill


def create_from_template(
    store: Gen2Store,
    record: RecordFn,
    template_id: str,
    *,
    name: str | None = None,
) -> dict[str, Any]:
    ir = get_template(template_id)
    if name:
        ir["name"] = name
    return create_workflow(store, record, ir, note=f"template:{template_id}")
