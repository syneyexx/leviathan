"""Mission Control / Mission Compiler — IR validation, compile, start, gates, sync.

Honesty: completion is evidence-based (failed steps / non-pass verification cannot
become ``completed``). Gate approvals drive lifecycle; budget ledger stays on Gen2Services.
Executable acceptance checks (not prose-only) gate completion. Resource plans are
domain-template stubs — never presented as live host measurements. Replans are
bounded by ``max_replans`` with an explicit cause taxonomy.

Lifecycle ownership (A12 / ``backend/run_lifecycle.py``):
- Work Runtime owns Work task status.
- Mission Control **mirrors** Work Runtime via ``sync_mission_from_task`` and may
  downgrade false ``completed`` claims when acceptance evidence fails.
- Mission Control must not invent completion without a Work Runtime terminal signal.
- Workflows own workflow-run status only and must not rewrite Work/Mission completion.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Callable

from gen2.store import Gen2Store, utc_now

RecordFn = Callable[..., dict[str, Any]]

# Agents/steps that may be dropped under budget pressure (optional trailing work).
_OPTIONAL_BUDGET_AGENTS = frozenset({"knowledge_builder"})
_MODEL_REPLAN_PROFILES = ("worker", "critic_first", "compact_retry")

# Verification statuses that may never silently become "passed".
_VERIFICATION_NON_PASS = frozenset(
    {"", "pending", "skipped", "unknown", "failed", "rejected", "incomplete", "blocked"}
)

# Executable acceptance check types (evaluated against task/step/verification evidence).
ACCEPTANCE_CHECK_TYPES = frozenset(
    {"status_equals", "artifact_exists", "verification_passed", "step_completed"}
)

# Bounded replan cause taxonomy (aligned with Flight Recorder failure taxonomy where shared).
REPLAN_CAUSES = frozenset({"tool", "model", "verification", "budget", "permission", "schema"})

# Mission lifecycle. Terminal states cannot become running without an explicit retry.
MISSION_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"compiled", "failed"},
    "compiled": {"awaiting_approval", "ready", "queued", "blocked", "failed", "running", "dispatched"},
    "awaiting_approval": {"ready", "failed", "awaiting_approval", "blocked", "running", "paused", "dispatched"},
    "ready": {"queued", "running", "blocked", "failed", "awaiting_approval", "dispatched"},
    "queued": {"running", "blocked", "failed", "cancelled", "dispatched"},
    # Dispatched = Work task created + scheduled; not yet executing (task still queued).
    "dispatched": {"running", "blocked", "failed", "cancelled", "paused", "awaiting_approval"},
    "running": {"completed", "failed", "blocked", "paused", "cancelled", "awaiting_approval"},
    "paused": {"running", "cancelled", "failed", "blocked", "awaiting_approval", "dispatched"},
    "blocked": {"ready", "queued", "failed", "cancelled", "dispatched"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


def validate_mission_ir(ir: dict[str, Any]) -> list[str]:
    """Return human-readable IR validation errors (empty = valid)."""
    errors: list[str] = []
    waves = list((ir or {}).get("execution_waves") or [])
    if not waves:
        errors.append("execution_waves missing")
        return errors
    ids: list[str] = []
    deps_map: dict[str, list[str]] = {}
    for wave in waves:
        for step in wave.get("steps") or []:
            sid = str(step.get("id") or "").strip()
            if not sid:
                errors.append("step missing id")
                continue
            if sid in ids:
                errors.append(f"duplicate step id:{sid}")
            ids.append(sid)
            deps = list(step.get("depends_on") or [])
            deps_map[sid] = [str(d) for d in deps]
            if not step.get("agent"):
                errors.append(f"step {sid} missing agent")
            tools = step.get("tools")
            if tools is not None and not isinstance(tools, list):
                errors.append(f"step {sid} tools must be a list")
    known = set(ids)
    for sid, deps in deps_map.items():
        for dep in deps:
            if dep not in known:
                errors.append(f"step {sid} depends on unknown:{dep}")
    # Cycle detection (DFS).
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
    contracts = (ir or {}).get("io_contracts")
    if contracts is not None and not isinstance(contracts, dict):
        errors.append("io_contracts must be an object")
    return errors


def pending_gates_for_wave(mission: dict[str, Any], before_wave: int) -> list[dict[str, Any]]:
    gates = list(mission.get("gates") or [])
    return [
        g
        for g in gates
        if g.get("required")
        and g.get("status") != "approved"
        and int(g.get("before_wave", 0) or 0) <= int(before_wave)
        and int(g.get("before_wave", 0) or 0) > 0
    ]


def default_acceptance_checks(
    *,
    domain: str,
    artifacts: list[str] | None = None,
    step_ids: list[str] | None = None,
    per_step: bool = False,
    artifacts_required: bool | None = None,
) -> list[dict[str, Any]]:
    """Structured executable acceptance checks compiled with the mission IR.

    Default uses aggregate ``require_all`` step accounting. Per-step id checks are
    opt-in (``per_step=True``) because Work Runtime often reports only counts.
    Explicit deliverable names become hard ``artifact_exists`` gates (required=True)
    unless ``artifacts_required=False`` is passed for optional placeholders.
    """
    checks: list[dict[str, Any]] = [
        {
            "id": "ac_status_completed",
            "type": "status_equals",
            "expected": "completed",
            "required": True,
            "source": "executable",
        },
        {
            "id": "ac_verification_passed",
            "type": "verification_passed",
            "required": True,
            "source": "executable",
        },
    ]
    if per_step and step_ids:
        for sid in step_ids:
            checks.append(
                {
                    "id": f"ac_step_{sid}",
                    "type": "step_completed",
                    "step_id": sid,
                    "required": True,
                    "source": "executable",
                }
            )
    else:
        checks.append(
            {
                "id": "ac_all_steps_completed",
                "type": "step_completed",
                "require_all": True,
                "required": True,
                "source": "executable",
            }
        )
    # Explicit deliverables are hard completion gates; empty list → no file requirement.
    require_arts = True if artifacts_required is None else bool(artifacts_required)
    for name in artifacts or []:
        checks.append(
            {
                "id": f"ac_artifact_{name.replace('.', '_')}",
                "type": "artifact_exists",
                "name": name,
                "required": require_arts,
                "source": "executable",
                "min_bytes": 1,
            }
        )
    for check in checks:
        check["domain"] = domain
    return checks


def evaluate_acceptance_checks(
    checks: list[dict[str, Any]] | None,
    *,
    status: str,
    verification: dict[str, Any] | None = None,
    step_summary: dict[str, Any] | None = None,
    mission: dict[str, Any] | None = None,
    artifact_service: Any | None = None,
) -> dict[str, Any]:
    """Evaluate executable acceptance checks against evidence — not prose matching.

    Returns ``{"passed": bool, "results": [...], "blockers": [...]}``.
    Unknown check types fail closed. Optional checks (``required=False``) are
    evaluated and reported but do not block overall pass.
    Artifact presence requires ArtifactService verification (bytes + ready status),
    not a bare filename or evidence_refs string.
    """
    ver = dict(verification or {})
    summary = dict(step_summary or {})
    mission = dict(mission or {})
    results: list[dict[str, Any]] = []
    blockers: list[str] = []

    for index, raw in enumerate(checks or []):
        if not isinstance(raw, dict):
            # Legacy prose strings are not executable evidence.
            results.append(
                {
                    "id": f"prose_{index}",
                    "type": "prose",
                    "passed": False,
                    "detail": "prose_not_executable",
                    "required": True,
                }
            )
            blockers.append(f"prose_not_executable:{index}")
            continue
        check_type = str(raw.get("type") or "").strip()
        check_id = str(raw.get("id") or f"check_{index}")
        required = bool(raw.get("required", True))
        if check_type not in ACCEPTANCE_CHECK_TYPES:
            results.append(
                {
                    "id": check_id,
                    "type": check_type or "unknown",
                    "passed": False,
                    "detail": "unknown_check_type",
                    "required": required,
                }
            )
            if required:
                blockers.append(f"unknown_check_type:{check_id}")
            continue

        passed = False
        detail = ""
        evidence: dict[str, Any] = {}

        if check_type == "status_equals":
            expected = str(raw.get("expected") or "completed").strip()
            actual = str(status or "").strip()
            passed = actual == expected
            detail = "status_match" if passed else f"status_mismatch:{actual}!={expected}"
            evidence = {"expected": expected, "actual": actual}

        elif check_type == "verification_passed":
            ver_status = str(ver.get("status") or "").lower().strip()
            passed = ver_status == "passed"
            detail = "verification_passed" if passed else f"verification_{ver_status or 'missing'}"
            evidence = {
                "verification_status": ver_status or None,
                "evidence_refs": list(ver.get("evidence_refs") or []),
            }

        elif check_type == "artifact_exists":
            name = str(raw.get("name") or raw.get("artifact") or "").strip()
            artifact_id = str(raw.get("artifact_id") or raw.get("id_ref") or "").strip() or None
            min_bytes = int(raw.get("min_bytes") or 1)
            expect_schema = raw.get("schema") or raw.get("expect_schema")
            presence = _artifact_verified(
                name,
                artifact_id=artifact_id,
                ver=ver,
                mission=mission,
                step_summary=summary,
                artifact_service=artifact_service,
                min_bytes=min_bytes,
                expect_schema=expect_schema,
            )
            passed = bool(presence.get("ok"))
            detail = str(presence.get("detail") or ("artifact_verified" if passed else "artifact_missing"))
            evidence = presence

        elif check_type == "step_completed":
            step_id = str(raw.get("step_id") or "").strip()
            require_all = bool(raw.get("require_all"))
            completed_ids = {
                str(x)
                for x in (
                    summary.get("completed_ids")
                    or summary.get("completed_step_ids")
                    or summary.get("completed_steps")
                    or []
                )
            }
            # Also accept per-step map: steps: {id: status}
            steps_map = summary.get("steps") if isinstance(summary.get("steps"), dict) else {}
            for sid, st in steps_map.items():
                if str(st).lower() in {"completed", "done", "passed", "ok"}:
                    completed_ids.add(str(sid))
            failed = int(summary.get("failed") or 0)
            pending = int(summary.get("pending") or 0)
            unknown = int(summary.get("unknown") or 0)
            total = int(summary.get("total") or 0)
            completed_count = int(summary.get("completed") or 0)
            if step_id:
                passed = step_id in completed_ids
                detail = "step_completed" if passed else f"step_not_completed:{step_id}"
                evidence = {"step_id": step_id, "completed_ids": sorted(completed_ids)}
            elif require_all or not step_id:
                accounting_ok = failed == 0 and pending == 0 and unknown == 0
                if total > 0:
                    passed = accounting_ok and completed_count >= total and completed_count > 0
                elif completed_ids:
                    passed = accounting_ok and len(completed_ids) > 0
                else:
                    passed = accounting_ok and completed_count > 0
                detail = "all_steps_completed" if passed else "steps_incomplete"
                evidence = {
                    "total": total,
                    "completed": completed_count,
                    "failed": failed,
                    "pending": pending,
                    "unknown": unknown,
                    "completed_ids": sorted(completed_ids),
                }

        results.append(
            {
                "id": check_id,
                "type": check_type,
                "passed": passed,
                "detail": detail,
                "evidence": evidence,
                "required": required,
                "criterion": raw.get("title") or raw.get("description") or check_id,
            }
        )
        if not passed and required:
            blockers.append(f"acceptance_check_failed:{check_id}:{detail}")

    return {
        "passed": len(blockers) == 0 and len(results) > 0,
        "results": results,
        "blockers": blockers,
        "checked_at": utc_now(),
        "evidence_based": True,
        "check_count": len(results),
    }


def _iter_artifact_candidates(
    name: str,
    *,
    artifact_id: str | None,
    ver: dict[str, Any],
    mission: dict[str, Any],
    step_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    """Collect candidate artifact dicts (never treat a bare string as verified bytes)."""
    candidates: list[dict[str, Any]] = []

    def _push(item: Any) -> None:
        if isinstance(item, dict):
            candidates.append(dict(item))
        elif isinstance(item, str) and item.strip():
            # String refs are unresolved handles — keep as metadata only.
            candidates.append({"name": item.strip(), "unresolved_ref": True})

    if artifact_id:
        candidates.append({"id": artifact_id, "name": name})
    for item in ver.get("artifacts") or []:
        _push(item)
    for item in step_summary.get("artifacts") or []:
        _push(item)
    acceptance = ver.get("acceptance") if isinstance(ver.get("acceptance"), dict) else {}
    for item in acceptance.get("artifacts") or []:
        _push(item)
    for item in mission.get("artifacts") or []:
        _push(item)
    # evidence_refs may include artifact ids — still unresolved until service verifies.
    for ref in ver.get("evidence_refs") or []:
        text = str(ref).strip()
        if not text:
            continue
        if text == name or text.endswith(name) or (artifact_id and text == artifact_id):
            candidates.append({"name": name or text, "id": text if text.startswith("art_") or "-" in text else None, "unresolved_ref": True, "from_evidence_ref": text})
    return candidates


def _artifact_verified(
    name: str,
    *,
    artifact_id: str | None = None,
    ver: dict[str, Any],
    mission: dict[str, Any],
    step_summary: dict[str, Any],
    artifact_service: Any | None = None,
    min_bytes: int = 1,
    expect_schema: Any | None = None,
) -> dict[str, Any]:
    """Verify deliverable via ArtifactService identity/status/bytes — not name membership."""
    if not name and not artifact_id:
        return {"ok": False, "detail": "artifact_name_missing", "name": name, "found": False}

    candidates = _iter_artifact_candidates(
        name, artifact_id=artifact_id, ver=ver, mission=mission, step_summary=step_summary
    )
    # Prefer exact id / name matches.
    ranked: list[dict[str, Any]] = []
    for item in candidates:
        item_name = str(item.get("name") or item.get("path") or "").strip()
        item_id = str(item.get("id") or item.get("artifact_id") or "").strip()
        if artifact_id and item_id == artifact_id:
            ranked.insert(0, item)
        elif name and (item_name == name or item_name.endswith(name)):
            ranked.append(item)
        elif artifact_id and not item_id:
            continue
        else:
            ranked.append(item)

    if artifact_service is None:
        # Without a registry, only accept candidates that already carry a verified payload
        # from a prior verify_ready call bound to this run (explicit checks dict).
        for item in ranked:
            checks = item.get("checks") if isinstance(item.get("checks"), dict) else {}
            if (
                checks.get("ok")
                and checks.get("exists")
                and checks.get("checksum_ok")
                and checks.get("status_ready")
                and int(item.get("size_bytes") or item.get("bytes") or 0) >= min_bytes
                and not item.get("unresolved_ref")
            ):
                if name and str(item.get("name") or "") not in {name, ""} and not str(item.get("name") or "").endswith(name):
                    continue
                return {
                    "ok": True,
                    "detail": "artifact_preverified",
                    "name": name,
                    "artifact_id": item.get("id"),
                    "found": True,
                    "size_bytes": item.get("size_bytes") or item.get("bytes"),
                    "checks": checks,
                }
        return {
            "ok": False,
            "detail": "artifact_service_missing_or_unverified",
            "name": name,
            "found": False,
            "candidates": len(ranked),
            "note": "Bare evidence_refs/name strings are not proof of bytes on disk.",
        }

    errors: list[str] = []
    for item in ranked:
        item_id = str(item.get("id") or item.get("artifact_id") or "").strip()
        item_name = str(item.get("name") or "").strip()
        if name and item_name and item_name != name and not item_name.endswith(name):
            if not item_id:
                continue
        try:
            target_id = item_id
            if not target_id and name:
                # Resolve by listing / get-by-name when service supports it.
                getter = getattr(artifact_service, "find_by_name", None)
                if callable(getter):
                    found_item = getter(name)
                    if isinstance(found_item, dict):
                        target_id = str(found_item.get("id") or "")
                if not target_id:
                    lister = getattr(artifact_service, "list", None)
                    if callable(lister):
                        for art in lister(limit=200) or []:
                            if not isinstance(art, dict):
                                continue
                            if str(art.get("name") or "") == name:
                                # Bind to mission/task/run when declared.
                                mission_id = str(mission.get("id") or "")
                                task_id = str(mission.get("task_id") or ver.get("task_id") or "")
                                run_id = str(ver.get("run_id") or mission.get("execution_id") or "")
                                if task_id and art.get("task_id") and str(art.get("task_id")) != task_id:
                                    continue
                                if run_id and art.get("run_id") and str(art.get("run_id")) != run_id:
                                    continue
                                if mission_id and art.get("mission_id") and str(art.get("mission_id")) != mission_id:
                                    continue
                                target_id = str(art.get("id") or "")
                                break
            if not target_id:
                errors.append("unresolved_id")
                continue
            verified = artifact_service.verify_ready(target_id)
            checks = dict(verified.get("checks") or {})
            art = dict(verified.get("artifact") or {})
            size = int(art.get("size_bytes") or 0)
            if not checks.get("ok"):
                errors.append(f"verify_failed:{target_id}")
                continue
            if size < min_bytes:
                errors.append(f"empty_or_too_small:{target_id}:{size}<{min_bytes}")
                continue
            # Optional schema check for JSON deliverables.
            if expect_schema is not None and str(art.get("mime_type") or "").endswith("json"):
                try:
                    import json
                    from pathlib import Path as _Path

                    raw = _Path(art["storage_path"]).read_text(encoding="utf-8")
                    payload = json.loads(raw)
                    if isinstance(expect_schema, dict):
                        for key in expect_schema:
                            if key not in payload:
                                raise ValueError(f"missing_key:{key}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"schema_failed:{exc}")
                    continue
            return {
                "ok": True,
                "detail": "artifact_verified",
                "name": art.get("name") or name,
                "artifact_id": art.get("id") or target_id,
                "found": True,
                "size_bytes": size,
                "checksum_sha256": art.get("checksum_sha256"),
                "version": art.get("version"),
                "status": art.get("status"),
                "checks": checks,
                "task_id": art.get("task_id"),
                "conversation_id": art.get("conversation_id"),
            }
        except KeyError:
            errors.append(f"not_found:{item_id or name}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}:{exc}"[:200])

    return {
        "ok": False,
        "detail": "artifact_unverified",
        "name": name,
        "found": False,
        "errors": errors[:8],
        "candidates": len(ranked),
    }


def resource_plan_for_domain(domain: str, *, waves: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Attach a resource-aware scheduling stub from domain templates.

    Estimates only — ``host_measured`` is always False. Never invents live RAM/VRAM.
    """
    domain = (domain or "general").lower()
    step_count = sum(len(w.get("steps") or []) for w in (waves or []))
    templates: dict[str, dict[str, Any]] = {
        "finance": {
            "model_slots": {"planner": 1, "worker": 2, "critic": 1},
            "estimated_ram_mb": 6144,
            "tool_contention_groups": [
                {"id": "market_io", "tools": ["trading", "paper_trading", "fincept-data"], "max_parallel": 1},
                {"id": "news_io", "tools": ["financial-news-intelligence"], "max_parallel": 2},
            ],
        },
        "coding": {
            "model_slots": {"planner": 1, "worker": 1, "critic": 1},
            "estimated_ram_mb": 4096,
            "tool_contention_groups": [
                {"id": "workspace_mutate", "tools": ["terminal", "build_agent"], "max_parallel": 1},
                {"id": "workspace_read", "tools": ["workspace_symbols"], "max_parallel": 2},
            ],
        },
        "research": {
            "model_slots": {"planner": 1, "worker": 2, "critic": 1},
            "estimated_ram_mb": 5120,
            "tool_contention_groups": [
                {"id": "retrieval", "tools": ["knowledge_search", "web_research_optional"], "max_parallel": 2},
            ],
        },
        "osint": {
            "model_slots": {"planner": 1, "worker": 2, "critic": 1},
            "estimated_ram_mb": 5120,
            "tool_contention_groups": [
                {"id": "osint_tools", "tools": ["web_research_optional"], "max_parallel": 1},
            ],
        },
        "general": {
            "model_slots": {"planner": 1, "worker": 1, "critic": 1},
            "estimated_ram_mb": 3072,
            "tool_contention_groups": [
                {"id": "default_tools", "tools": ["knowledge_search"], "max_parallel": 2},
            ],
        },
    }
    base = dict(templates.get(domain) or templates["general"])
    # Scale estimate lightly by step count without claiming measurement.
    est = int(base.get("estimated_ram_mb") or 3072)
    if step_count > 6:
        est = int(est * 1.25)
    return {
        "source": "domain_template",
        "domain": domain,
        "host_measured": False,
        "model_slots": dict(base.get("model_slots") or {}),
        "estimated_ram_mb": est,
        "tool_contention_groups": list(base.get("tool_contention_groups") or []),
        "step_count": step_count,
        "note": "Template stub for scheduling; not live host RAM/VRAM/CPU measurements.",
    }


def _coalesce_int(*values: Any, default: int) -> int:
    """Return the first non-None value as int. Explicit ``0`` is preserved."""
    for value in values:
        if value is not None:
            return int(value)
    return int(default)


def _iter_wave_steps(waves: list[dict[str, Any]]) -> list[tuple[int, int, dict[str, Any]]]:
    out: list[tuple[int, int, dict[str, Any]]] = []
    for wi, wave in enumerate(waves):
        for si, step in enumerate(wave.get("steps") or []):
            out.append((wi, si, step))
    return out


def _clone_waves(waves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return copy.deepcopy(list(waves or []))


def _waves_signature(waves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Comparable structural signature (tools/profile/agent/deps) without ephemeral fields."""
    sig: list[dict[str, Any]] = []
    for wave in waves or []:
        steps = []
        for step in wave.get("steps") or []:
            steps.append(
                {
                    "id": step.get("id"),
                    "agent": step.get("agent"),
                    "title": step.get("title"),
                    "depends_on": list(step.get("depends_on") or []),
                    "tools": list(step.get("tools") or []),
                    "profile": step.get("profile"),
                    "optional": bool(step.get("optional")),
                    "replan_action": step.get("replan_action"),
                    "mode": step.get("mode"),
                    "context_tokens": step.get("context_tokens"),
                }
            )
        sig.append({"wave": wave.get("wave"), "steps": steps})
    return sig


def _diff_wave_steps(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    before_map = {
        str(s.get("id")): s
        for wave in before
        for s in (wave.get("steps") or [])
        if s.get("id")
    }
    after_map = {
        str(s.get("id")): s
        for wave in after
        for s in (wave.get("steps") or [])
        if s.get("id")
    }
    changes: list[dict[str, Any]] = []
    for sid in sorted(set(before_map) | set(after_map)):
        if sid not in before_map:
            changes.append({"step_id": sid, "change": "added", "before": None, "after": after_map[sid]})
        elif sid not in after_map:
            changes.append({"step_id": sid, "change": "removed", "before": before_map[sid], "after": None})
        else:
            b = _waves_signature([{"wave": 0, "steps": [before_map[sid]]}])[0]["steps"][0]
            a = _waves_signature([{"wave": 0, "steps": [after_map[sid]]}])[0]["steps"][0]
            if b != a:
                changes.append({"step_id": sid, "change": "modified", "before": before_map[sid], "after": after_map[sid]})
    return changes


def _completed_step_ids(mission: dict[str, Any]) -> set[str]:
    ver = dict(mission.get("verification") or {})
    summary = dict(ver.get("step_summary") or {})
    ids = {str(x) for x in (summary.get("completed_ids") or []) if str(x).strip()}
    preserved = dict(ver.get("preserved_results") or {})
    for sid, row in preserved.items():
        if isinstance(row, dict) and row.get("status") in {"completed", "passed", "ok"}:
            ids.add(str(sid))
    return ids


def _find_step_ref(
    waves: list[dict[str, Any]], step_id: str | None
) -> tuple[int, int, dict[str, Any]] | None:
    if not step_id:
        return None
    for wi, si, step in _iter_wave_steps(waves):
        if str(step.get("id") or "") == step_id:
            return wi, si, step
    return None


def _resolve_failed_step_id(
    mission: dict[str, Any], waves: list[dict[str, Any]], failed_step_id: str | None
) -> str | None:
    if failed_step_id and _find_step_ref(waves, failed_step_id):
        return str(failed_step_id)
    ver = dict(mission.get("verification") or {})
    summary = dict(ver.get("step_summary") or {})
    for key in ("failed_ids", "failed_step_ids"):
        for sid in summary.get(key) or []:
            sid_s = str(sid).strip()
            if sid_s and _find_step_ref(waves, sid_s):
                return sid_s
    hint = str(ver.get("failed_step_id") or mission.get("error") or "").strip()
    if hint and _find_step_ref(waves, hint):
        return hint
    completed = _completed_step_ids(mission)
    # Prefer a tool-bearing incomplete step, else first incomplete step.
    tool_candidate: str | None = None
    first_incomplete: str | None = None
    for _wi, _si, step in _iter_wave_steps(waves):
        sid = str(step.get("id") or "")
        if not sid or sid in completed:
            continue
        if first_incomplete is None:
            first_incomplete = sid
        if list(step.get("tools") or []) and tool_candidate is None:
            tool_candidate = sid
    return tool_candidate or first_incomplete


def _allowed_tools_for_mission(mission: dict[str, Any]) -> list[str]:
    ir = dict(mission.get("ir") or {})
    allowed: list[str] = []
    for name in list(ir.get("plugins_tools") or []) + _suggested_tools(str(ir.get("domain") or "general")):
        n = str(name or "").strip()
        if n and n not in allowed:
            allowed.append(n)
    plan = dict(ir.get("resource_plan") or {})
    for group in plan.get("tool_contention_groups") or []:
        for name in group.get("tools") or []:
            n = str(name or "").strip()
            if n and n not in allowed:
                allowed.append(n)
    return allowed


def _dependents_of(waves: list[dict[str, Any]], roots: set[str]) -> set[str]:
    """Return transitive dependents of ``roots`` (excluding roots themselves)."""
    deps_map: dict[str, list[str]] = {}
    for _wi, _si, step in _iter_wave_steps(waves):
        sid = str(step.get("id") or "")
        if not sid:
            continue
        deps_map[sid] = [str(d) for d in (step.get("depends_on") or [])]
    invalidated: set[str] = set()
    changed = True
    while changed:
        changed = False
        for sid, deps in deps_map.items():
            if sid in roots or sid in invalidated:
                continue
            if any(d in roots or d in invalidated for d in deps):
                invalidated.add(sid)
                changed = True
    return invalidated


def _gate_action_scope(waves: list[dict[str, Any]], before_wave: int) -> str:
    """Fingerprint of tools/actions covered by a gate at/after ``before_wave``."""
    parts: list[str] = []
    for wave in waves or []:
        wnum = int(wave.get("wave") or 0)
        if wnum + 1 < int(before_wave):  # before_wave is 1-indexed gate barrier
            continue
        for step in wave.get("steps") or []:
            tools = ",".join(str(t) for t in (step.get("tools") or []))
            parts.append(f"{step.get('id')}:{step.get('agent')}:{tools}:{step.get('mode') or ''}")
    material = "|".join(parts) or "empty"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _invalidate_stale_approvals(
    gates: list[dict[str, Any]],
    old_waves: list[dict[str, Any]],
    new_waves: list[dict[str, Any]],
    *,
    changed_step_ids: set[str],
) -> list[str]:
    """Reset approvals whose scoped actions no longer match; return invalidated gate ids."""
    invalidated: list[str] = []
    if not changed_step_ids:
        return invalidated
    for gate in gates:
        gid = str(gate.get("id") or "")
        if gate.get("status") != "approved":
            # Still refresh scope binding for pending gates when actions change.
            before_wave = int(gate.get("before_wave", 0) or 0)
            gate["approval_scope"] = _gate_action_scope(new_waves, before_wave)
            continue
        before_wave = int(gate.get("before_wave", 0) or 0)
        old_scope = str(gate.get("approval_scope") or _gate_action_scope(old_waves, before_wave))
        new_scope = _gate_action_scope(new_waves, before_wave)
        gate["approval_scope"] = new_scope
        # Tool/autonomy gates and any gate whose scope fingerprint drifted must re-approve.
        scope_covers_change = old_scope != new_scope
        if scope_covers_change or "tool" in gid or gate.get("kind") == "human_approval":
            if scope_covers_change:
                gate["status"] = "pending"
                gate["invalidated_reason"] = "action_scope_changed"
                gate.pop("decision_fingerprint", None)
                invalidated.append(gid)
    return invalidated


def _mark_result_preservation(
    waves: list[dict[str, Any]],
    completed: set[str],
    invalidated: set[str],
) -> tuple[list[str], list[str]]:
    preserved: list[str] = []
    cleared: list[str] = []
    for _wi, _si, step in _iter_wave_steps(waves):
        sid = str(step.get("id") or "")
        if not sid:
            continue
        if sid in completed and sid not in invalidated:
            step["result_status"] = "preserved"
            preserved.append(sid)
        elif sid in invalidated or (sid in completed and sid in invalidated):
            step["result_status"] = "invalidated"
            cleared.append(sid)
        elif sid in completed:
            step["result_status"] = "invalidated"
            cleared.append(sid)
    return preserved, cleared


def _insert_step_before(
    waves: list[dict[str, Any]], target_id: str, new_step: dict[str, Any]
) -> bool:
    ref = _find_step_ref(waves, target_id)
    if not ref:
        return False
    wi, si, target = ref
    deps = list(target.get("depends_on") or [])
    new_step = dict(new_step)
    new_step.setdefault("depends_on", list(deps))
    # Target now depends on the inserted repair step.
    target_deps = list(deps)
    nid = str(new_step.get("id") or "")
    if nid and nid not in target_deps:
        target_deps.append(nid)
    waves[wi]["steps"][si]["depends_on"] = target_deps
    waves[wi]["steps"].insert(si, new_step)
    return True


def _append_wave(waves: list[dict[str, Any]], steps: list[dict[str, Any]]) -> None:
    next_wave = 0
    if waves:
        next_wave = max(int(w.get("wave") or 0) for w in waves) + 1
    waves.append({"wave": next_wave, "steps": steps})


def rebuild_execution_waves_for_replan(
    mission: dict[str, Any],
    cause: str,
    note: str,
    failed_step_id: str | None = None,
) -> dict[str, Any]:
    """Build a contentful alternate subplan for ``cause``, or an honest stop signal.

    Permission failures never bypass via an alternate tool. Counter bumps alone are
    not a new approach — callers must inspect ``replan_kind``.
    """
    cause_clean = str(cause or "").strip().lower()
    ir = dict(mission.get("ir") or {})
    old_waves = _clone_waves(list(ir.get("execution_waves") or []))
    waves = _clone_waves(old_waves)
    plan_version_before = _coalesce_int(ir.get("version"), default=1)
    operational_reason = (note or "").strip()[:500] or f"replan due to {cause_clean}"
    no_valid_alternative = False
    blocked = False
    block_reason: str | None = None
    changed_roots: set[str] = set()
    completed = _completed_step_ids(mission)
    target_id = _resolve_failed_step_id(mission, waves, failed_step_id)

    if cause_clean == "permission":
        # Do not swap tools or invent bypass steps.
        blocked = True
        block_reason = operational_reason or "permission denied; awaiting approval"
        operational_reason = block_reason
    elif cause_clean == "tool":
        if not target_id:
            no_valid_alternative = True
            operational_reason = "tool failure but no failed step to replan"
        else:
            ref = _find_step_ref(waves, target_id)
            assert ref is not None
            _wi, _si, step = ref
            current_tools = [str(t) for t in (step.get("tools") or [])]
            allowed = _allowed_tools_for_mission(mission)
            alternate = next((t for t in allowed if t not in current_tools), None)
            if alternate:
                step["tools"] = [alternate]
                step["replan_action"] = "alternate_tool"
                step["previous_tools"] = current_tools
                step["result_status"] = "pending"
                operational_reason = f"tool failure on {target_id}; switched to alternate tool {alternate}"
                changed_roots.add(target_id)
            elif step.get("replan_action") == "manual_research_fallback":
                no_valid_alternative = True
                operational_reason = f"no valid alternate tool or fallback for {target_id}"
            else:
                # Research/manual fallback when no alternate tool is available.
                step["tools"] = []
                step["mode"] = "manual_or_research"
                step["agent"] = step.get("agent") or "research_worker"
                if str(step.get("agent") or "") in {"build", "trading_specialist", "executor"}:
                    step["agent"] = "research_worker"
                step["replan_action"] = "manual_research_fallback"
                step["previous_tools"] = current_tools
                step["title"] = f"{step.get('title') or target_id} (research/manual fallback)"
                step["result_status"] = "pending"
                operational_reason = (
                    f"tool failure on {target_id}; no alternate tool — research/manual fallback"
                )
                changed_roots.add(target_id)
    elif cause_clean == "model":
        if not target_id:
            # Apply to first incomplete model-ish step.
            target_id = _resolve_failed_step_id(mission, waves, None)
        if not target_id:
            no_valid_alternative = True
            operational_reason = "model failure but no step available to adjust"
        else:
            ref = _find_step_ref(waves, target_id)
            assert ref is not None
            _wi, _si, step = ref
            current_profile = str(step.get("profile") or "worker")
            next_profile = next(
                (p for p in _MODEL_REPLAN_PROFILES if p != current_profile),
                "critic_first",
            )
            step["profile"] = next_profile
            step["replan_action"] = "model_profile_switch"
            # Smaller context retry — respect explicit 0 if present on budgets.
            budgets = dict(mission.get("budgets") or {})
            ctx = budgets.get("context_tokens")
            if ctx is None:
                ctx = (ir.get("context_budgets") or {}).get("compiler_max_tokens")
            if ctx is None:
                shrink_to = 4096
            else:
                shrink_to = max(512, int(ctx) // 2) if int(ctx) > 0 else 0
            step["context_tokens"] = shrink_to
            if next_profile == "critic_first":
                step["critic_first"] = True
            step["result_status"] = "pending"
            operational_reason = (
                f"model failure on {target_id}; profile {current_profile}→{next_profile}, "
                f"context_tokens={shrink_to}"
            )
            changed_roots.add(target_id)
    elif cause_clean == "verification":
        # Append a repair + verify wave targeting failed acceptance checks.
        ver = dict(mission.get("verification") or {})
        evaled = dict(ver.get("acceptance_checks_eval") or {})
        failed_checks = [
            r.get("id") or r.get("check_id")
            for r in (evaled.get("results") or [])
            if isinstance(r, dict) and r.get("passed") is False
        ]
        failed_checks = [str(x) for x in failed_checks if x]
        anchor = target_id or (sorted(completed)[-1] if completed else None)
        deps = [anchor] if anchor else []
        repair_id = "s_repair_verify"
        existing_ids = {str(s.get("id")) for _w, _i, s in _iter_wave_steps(waves)}
        suffix = 1
        while repair_id in existing_ids:
            suffix += 1
            repair_id = f"s_repair_verify_{suffix}"
        verify_id = f"{repair_id}_check"
        while verify_id in existing_ids or verify_id == repair_id:
            suffix += 1
            verify_id = f"s_repair_verify_{suffix}_check"
        repair_step = {
            "id": repair_id,
            "title": "Repair failed acceptance",
            "agent": "executor",
            "depends_on": deps,
            "tools": [],
            "replan_action": "verification_repair",
            "failed_checks": failed_checks[:20],
            "result_status": "pending",
        }
        verify_step = {
            "id": verify_id,
            "title": "Re-verify acceptance checks",
            "agent": "critic",
            "depends_on": [repair_id],
            "tools": [],
            "replan_action": "verification_recheck",
            "failed_checks": failed_checks[:20],
            "result_status": "pending",
        }
        _append_wave(waves, [repair_step, verify_step])
        changed_roots.add(repair_id)
        changed_roots.add(verify_id)
        operational_reason = (
            f"verification failure; inserted repair/verify wave ({repair_id}, {verify_id})"
            + (f" for checks {failed_checks[:5]}" if failed_checks else "")
        )
    elif cause_clean == "budget":
        dropped: list[str] = []
        for wave in waves:
            kept = []
            for step in wave.get("steps") or []:
                sid = str(step.get("id") or "")
                optional = bool(step.get("optional")) or str(step.get("agent") or "") in _OPTIONAL_BUDGET_AGENTS
                title = str(step.get("title") or "").lower()
                if optional or "archive" in title or "knowledge/memory" in title:
                    if sid and sid not in completed:
                        dropped.append(sid)
                        changed_roots.add(sid)
                        continue
                kept.append(step)
            wave["steps"] = kept
        waves = [w for w in waves if w.get("steps")]
        if not dropped:
            # Shrink remaining incomplete work markers when nothing optional to drop.
            for _wi, _si, step in _iter_wave_steps(waves):
                sid = str(step.get("id") or "")
                if sid and sid not in completed:
                    step["budget_shrink"] = True
                    step["replan_action"] = "budget_shrink"
                    changed_roots.add(sid)
                    operational_reason = f"budget pressure; marked remaining work to shrink ({sid})"
                    break
            else:
                no_valid_alternative = True
                operational_reason = "budget pressure but no remaining work to shrink"
        else:
            operational_reason = f"budget pressure; dropped optional steps: {', '.join(dropped)}"
    elif cause_clean == "schema":
        if not target_id:
            target_id = _resolve_failed_step_id(mission, waves, None)
        if not target_id:
            no_valid_alternative = True
            operational_reason = "schema failure but no step to repair"
        else:
            existing_ids = {str(s.get("id")) for _w, _i, s in _iter_wave_steps(waves)}
            repair_id = f"{target_id}_schema_repair"
            n = 1
            while repair_id in existing_ids:
                n += 1
                repair_id = f"{target_id}_schema_repair_{n}"
            ref = _find_step_ref(waves, target_id)
            deps = list((ref[2].get("depends_on") if ref else None) or [])
            repair_step = {
                "id": repair_id,
                "title": f"Schema repair before {target_id}",
                "agent": "executor",
                "depends_on": deps,
                "tools": [],
                "replan_action": "schema_repair",
                "result_status": "pending",
            }
            if not _insert_step_before(waves, target_id, repair_step):
                no_valid_alternative = True
                operational_reason = f"schema repair could not be inserted before {target_id}"
            else:
                changed_roots.add(repair_id)
                changed_roots.add(target_id)
                operational_reason = f"schema failure; inserted {repair_id} before retry of {target_id}"
    else:
        raise ValueError(f"invalid_replan_cause:{cause_clean or 'empty'}")

    invalidated = _dependents_of(waves, changed_roots) | (changed_roots - completed)
    # Always invalidate the changed roots themselves for re-execution, but preserve
    # independent successes not in the dependency cone.
    preserve_candidates = set(completed) - changed_roots - _dependents_of(waves, changed_roots)
    # Recompute dependents against final wave graph from changed roots.
    dep_invalidated = _dependents_of(waves, changed_roots)
    invalidated_ids = sorted((changed_roots | dep_invalidated) - preserve_candidates)
    preserved_ids, cleared_ids = _mark_result_preservation(waves, completed, set(invalidated_ids))

    wave_changes = _diff_wave_steps(old_waves, waves)
    identical = _waves_signature(old_waves) == _waves_signature(waves)
    if identical:
        replan_kind = "identical_retry"
    else:
        replan_kind = "contentful"

    plan_version_after = plan_version_before + (0 if identical else 1)

    # Validate DAG / I/O / acceptance presence before resume.
    trial_ir = {
        **ir,
        "execution_waves": waves,
        "version": plan_version_after,
    }
    validation_errors = validate_mission_ir(trial_ir)
    if not list(ir.get("acceptance_checks") or ir.get("acceptance_criteria") or []):
        validation_errors.append("acceptance criteria missing")
    budgets = dict(mission.get("budgets") or {})
    # Budgets: None means unlimited; 0 is a hard stop — do not widen.
    for key in ("max_tool_calls", "max_tokens", "max_time_seconds", "max_replans"):
        if key in budgets and budgets[key] is not None:
            try:
                if int(budgets[key]) < 0:
                    validation_errors.append(f"budget {key} negative")
            except (TypeError, ValueError):
                validation_errors.append(f"budget {key} invalid")
    perms = ir.get("permissions")
    if perms is not None and not isinstance(perms, dict):
        validation_errors.append("permissions must be an object")

    if validation_errors and not blocked:
        no_valid_alternative = True
        operational_reason = f"replan validation failed: {'; '.join(validation_errors[:5])}"

    return {
        "waves": waves,
        "old_waves": old_waves,
        "replan_kind": replan_kind,
        "no_valid_alternative": bool(no_valid_alternative),
        "blocked": blocked,
        "block_reason": block_reason,
        "changed_steps": wave_changes,
        "changed_step_ids": sorted({c["step_id"] for c in wave_changes}),
        "operational_reason": operational_reason[:500],
        "preserved_step_ids": preserved_ids,
        "invalidated_step_ids": sorted(set(invalidated_ids) | set(cleared_ids)),
        "failed_step_id": target_id,
        "plan_version_before": plan_version_before,
        "plan_version_after": plan_version_after,
        "validation_errors": validation_errors,
        "cause": cause_clean,
    }


def replan_mission(
    store: Gen2Store,
    record: RecordFn,
    mission_id: str,
    cause: str,
    *,
    note: str = "",
    failed_step_id: str | None = None,
) -> dict[str, Any]:
    """Bounded replan with cause taxonomy, contentful wave rebuild, and ``max_replans``.

    Produces an alternate subplan when possible (tool/model/schema/verification/budget).
    Permission errors block without tool bypass. Identical justified retries are labeled
    ``identical_retry`` — a counter bump alone is not a new approach.
    """
    cause_clean = str(cause or "").strip().lower()
    if cause_clean not in REPLAN_CAUSES:
        raise ValueError(f"invalid_replan_cause:{cause_clean or 'empty'}")
    mission = store.get_mission(mission_id)
    if not mission:
        raise ValueError("mission not found")
    status = str(mission.get("status") or "")
    if status in {"completed", "cancelled"}:
        raise ValueError(f"cannot replan {status} mission")
    budgets = dict(mission.get("budgets") or {})
    ir = dict(mission.get("ir") or {})
    max_replans = _coalesce_int(
        budgets.get("max_replans"),
        (ir.get("retry_policies") or {}).get("max_replans"),
        default=3,
    )
    replan_count = _coalesce_int(
        budgets.get("replan_count"),
        ir.get("replan_count"),
        (mission.get("verification") or {}).get("replan_count"),
        default=0,
    )
    if replan_count >= max_replans:
        raise ValueError(f"max_replans_exceeded:{replan_count}>={max_replans}")

    rebuild = rebuild_execution_waves_for_replan(
        mission, cause_clean, note, failed_step_id=failed_step_id
    )

    replan_count += 1
    budgets["replan_count"] = replan_count
    budgets["max_replans"] = max_replans
    ir["replan_count"] = replan_count
    ir["version"] = rebuild["plan_version_after"]
    ir["execution_waves"] = rebuild["waves"]
    # Keep subtasks / dependencies aligned with waves (leases/checkpoints stay wave-based).
    ir["subtasks"] = [step for wave in rebuild["waves"] for step in (wave.get("steps") or [])]
    ir["dependencies"] = [
        {"from": dep, "to": step["id"]}
        for wave in rebuild["waves"]
        for step in (wave.get("steps") or [])
        for dep in step.get("depends_on") or []
    ]
    ir["checkpoints"] = [{"after_wave": w.get("wave"), "persist": True} for w in rebuild["waves"]]
    ir["agents"] = sorted(
        {
            str(step.get("agent"))
            for wave in rebuild["waves"]
            for step in (wave.get("steps") or [])
            if step.get("agent")
        }
    )
    retry = dict(ir.get("retry_policies") or {})
    retry["max_replans"] = max_replans
    retry["last_cause"] = cause_clean
    retry["last_replan_kind"] = rebuild["replan_kind"]
    ir["retry_policies"] = retry

    gates = list(mission.get("gates") or [])
    invalidated_approvals = _invalidate_stale_approvals(
        gates,
        rebuild["old_waves"],
        rebuild["waves"],
        changed_step_ids=set(rebuild.get("changed_step_ids") or []),
    )

    wave_diff = {
        "plan_version_before": rebuild["plan_version_before"],
        "plan_version_after": rebuild["plan_version_after"],
        "replan_kind": rebuild["replan_kind"],
        "changed_steps": [
            {
                "step_id": c["step_id"],
                "change": c["change"],
                "before_tools": list((c.get("before") or {}).get("tools") or []) if c.get("before") else None,
                "after_tools": list((c.get("after") or {}).get("tools") or []) if c.get("after") else None,
                "before_agent": (c.get("before") or {}).get("agent") if c.get("before") else None,
                "after_agent": (c.get("after") or {}).get("agent") if c.get("after") else None,
                "before_profile": (c.get("before") or {}).get("profile") if c.get("before") else None,
                "after_profile": (c.get("after") or {}).get("profile") if c.get("after") else None,
            }
            for c in rebuild["changed_steps"]
        ],
        "preserved_step_ids": rebuild["preserved_step_ids"],
        "invalidated_step_ids": rebuild["invalidated_step_ids"],
        "operational_reason": rebuild["operational_reason"],
        "invalidated_approvals": invalidated_approvals,
    }
    ir["last_replan_diff"] = wave_diff

    history = list(ir.get("replan_history") or [])
    entry = {
        "index": replan_count,
        "cause": cause_clean,
        "note": (note or "")[:2000],
        "at": utc_now(),
        "from_status": status,
        "replan_kind": rebuild["replan_kind"],
        "plan_version_before": rebuild["plan_version_before"],
        "plan_version_after": rebuild["plan_version_after"],
        "changed_step_ids": rebuild["changed_step_ids"],
        "operational_reason": rebuild["operational_reason"],
        "no_valid_alternative": rebuild["no_valid_alternative"],
        "failed_step_id": rebuild.get("failed_step_id"),
    }
    history.append(entry)
    ir["replan_history"] = history[-20:]

    # Status selection: permission / no alternative → honest block; else approval or ready.
    pending_start = [
        g
        for g in gates
        if g.get("required")
        and g.get("status") != "approved"
        and int(g.get("before_wave", 0) or 0) <= 1
    ]
    error_msg: str | None = None
    if rebuild["blocked"] or cause_clean == "permission":
        new_status = "awaiting_approval" if pending_start else "blocked"
        error_msg = rebuild.get("block_reason") or rebuild["operational_reason"]
    elif rebuild["no_valid_alternative"]:
        new_status = "blocked"
        error_msg = rebuild["operational_reason"] or "no_valid_alternative"
    elif pending_start or invalidated_approvals:
        new_status = "awaiting_approval"
    else:
        new_status = "ready"

    ver = dict(mission.get("verification") or {})
    ver["status"] = "pending"
    ver["replan_count"] = replan_count
    ver["last_replan_cause"] = cause_clean
    ver["last_replan_kind"] = rebuild["replan_kind"]
    ver["replan_diff"] = wave_diff
    # Preserve independent successes; drop invalidated results only.
    preserved_map = dict(ver.get("preserved_results") or {})
    summary = dict(ver.get("step_summary") or {})
    completed_ids = [str(x) for x in (summary.get("completed_ids") or [])]
    keep = [sid for sid in completed_ids if sid in set(rebuild["preserved_step_ids"])]
    for sid in list(preserved_map.keys()):
        if sid not in set(rebuild["preserved_step_ids"]):
            preserved_map.pop(sid, None)
    for sid in rebuild["preserved_step_ids"]:
        preserved_map.setdefault(sid, {"status": "completed", "preserved_across_replan": True})
    summary["completed_ids"] = keep
    summary["invalidated_ids"] = list(rebuild["invalidated_step_ids"])
    ver["step_summary"] = summary
    ver["preserved_results"] = preserved_map

    updated = store.update_mission(
        mission_id,
        status=new_status,
        budgets=budgets,
        ir=ir,
        gates=gates,
        verification=ver,
        error=error_msg,
    ) or mission
    revision = persist_mission_revision(
        store,
        updated,
        cause=f"replan:{cause_clean}:{rebuild['replan_kind']}",
        note=(rebuild["operational_reason"] or note or "")[:500],
    )
    links = mission_identity_links(updated)
    record(
        mission_id,
        "REPLAN",
        {
            "cause": cause_clean,
            "note": (note or "")[:2000],
            "replan_count": replan_count,
            "max_replans": max_replans,
            "from_status": status,
            "to_status": new_status,
            "identity_links": links,
            "revision": revision["version"],
            "replan_kind": rebuild["replan_kind"],
            "plan_version_before": rebuild["plan_version_before"],
            "plan_version_after": rebuild["plan_version_after"],
            "changed_step_ids": rebuild["changed_step_ids"],
            "operational_reason": rebuild["operational_reason"],
            "no_valid_alternative": rebuild["no_valid_alternative"],
            "wave_diff": wave_diff,
        },
        component="mission_control",
    )
    return {
        **(attach_identity_links(updated) or updated),
        "replan": entry,
        "replan_count": replan_count,
        "max_replans": max_replans,
        "revision": revision["version"],
        "replan_kind": rebuild["replan_kind"],
        "plan_version_before": rebuild["plan_version_before"],
        "plan_version_after": rebuild["plan_version_after"],
        "changed_steps": wave_diff["changed_steps"],
        "operational_reason": rebuild["operational_reason"],
        "no_valid_alternative": rebuild["no_valid_alternative"],
        "wave_diff": wave_diff,
    }


def sync_mission_from_task(
    store: Gen2Store,
    record: RecordFn,
    task_id: str,
    *,
    status: str,
    error: str | None = None,
    verification: dict[str, Any] | None = None,
    step_summary: dict[str, Any] | None = None,
    artifact_service: Any | None = None,
) -> dict[str, Any] | None:
    """Map Work Runtime terminal/blocked outcomes onto the linked mission.

    Completion is evidence-based: failed steps or failed verification cannot become
    ``completed`` even if the Work Runtime status string says completed.
    """
    mission = store.get_mission_by_task_id(task_id)
    if not mission:
        return None
    current = str(mission.get("status") or "")
    if current in {"completed", "failed", "cancelled"} and status != current:
        return mission
    allowed = MISSION_TRANSITIONS.get(current, set())
    # Work Runtime may finish from running/paused/awaiting_approval/blocked/dispatched.
    runtime_ok = current in {
        "running",
        "paused",
        "awaiting_approval",
        "blocked",
        "queued",
        "dispatched",
    } and status in {
        "completed",
        "failed",
        "blocked",
        "paused",
        "cancelled",
        "awaiting_approval",
        "running",
    }
    if status not in allowed and status != current and not runtime_ok:
        return mission

    step_summary = dict(step_summary or {})
    ver = {**(mission.get("verification") or {}), **(verification or {})}
    if step_summary:
        ver["step_summary"] = step_summary

    final_status = status
    final_error = error
    if status == "completed":
        failed_steps = int(step_summary.get("failed") or 0)
        pending_steps = int(step_summary.get("pending") or 0)
        skipped_steps = int(step_summary.get("skipped") or 0)
        unknown_steps = int(step_summary.get("unknown") or 0)
        total_steps = int(step_summary.get("total") or 0)
        completed_steps = int(step_summary.get("completed") or 0)
        ver_status = str(ver.get("status") or "").lower().strip()
        ver_required = bool(ver.get("required", True))
        acceptance = list(mission.get("acceptance_criteria") or [])
        ir = dict(mission.get("ir") or {})
        executable_checks = list(ir.get("acceptance_checks") or [])
        # Structured dicts in acceptance_criteria also count as executable checks.
        for item in acceptance:
            if isinstance(item, dict) and item.get("type") in ACCEPTANCE_CHECK_TYPES:
                if item not in executable_checks:
                    executable_checks.append(item)
        criteria_results = list(ver.get("criteria_results") or ver.get("criteria_checklist") or [])
        evidence_refs = list(ver.get("evidence_refs") or [])
        check_eval: dict[str, Any] | None = None
        if executable_checks:
            # For verification_passed during completion, treat an explicitly passed
            # verification payload as the evidence under test (do not invent pass).
            check_eval = evaluate_acceptance_checks(
                executable_checks,
                status=status,
                verification=ver,
                step_summary=step_summary,
                mission=mission,
                artifact_service=artifact_service,
            )
            # Executable evaluation supplies criteria_results (not prose-only).
            criteria_results = list(check_eval.get("results") or [])
            ver["criteria_results"] = criteria_results
            ver["acceptance_checks_eval"] = {
                "passed": check_eval.get("passed"),
                "blockers": check_eval.get("blockers"),
                "checked_at": check_eval.get("checked_at"),
                "check_count": check_eval.get("check_count"),
            }
        evidence = {
            "source": "work_runtime",
            "checked_at": utc_now(),
            "step_summary": step_summary,
            "verification_status": ver_status or None,
            "acceptance_criteria_count": len(acceptance),
            "acceptance_checks_count": len(executable_checks),
            "criteria_assessed": len(criteria_results),
            "evidence_refs": evidence_refs,
            "evidence_based": True,
            "executable_acceptance": True if executable_checks else False,
        }
        blockers: list[str] = []
        if failed_steps > 0:
            blockers.append("failed_steps")
        if pending_steps > 0:
            blockers.append("pending_steps")
        if unknown_steps > 0:
            blockers.append("unknown_steps")
        if total_steps > 0 and completed_steps + failed_steps + skipped_steps + pending_steps + unknown_steps < total_steps:
            blockers.append("incomplete_step_accounting")
        if ver_required and ver_status in _VERIFICATION_NON_PASS:
            blockers.append(f"verification_{ver_status or 'missing'}")
        if ver_required and ver_status != "passed":
            blockers.append("verification_not_explicitly_passed")
        if acceptance and not criteria_results and not executable_checks:
            blockers.append("acceptance_criteria_unassessed")
        if check_eval is not None and not check_eval.get("passed"):
            blockers.extend(list(check_eval.get("blockers") or []))
            blockers.append("executable_acceptance_failed")
        # Explicit evidence refs remain required for completion when verification is required —
        # executable checks assess structure, but do not invent provenance links.
        if ver_required and not evidence_refs:
            blockers.append("verification_missing_evidence_refs")
        if ver_required and ver_status == "passed" and not evidence_refs and not criteria_results:
            # Absence of error is insufficient: require explicit evidence or assessed criteria.
            if not ver.get("source"):
                blockers.append("verification_missing_evidence")
        if blockers or ver_status in {"failed", "rejected"}:
            final_status = "failed"
            final_error = error or (
                "acceptance_failed: " + ",".join(blockers)
                if blockers
                else "acceptance_failed: steps or verification did not pass"
            )
            evidence["passed"] = False
            evidence["reason"] = final_error
            evidence["blockers"] = blockers
            ver["status"] = "failed"
        else:
            evidence["passed"] = True
            evidence["reason"] = "Work Runtime completed with required verification passed"
            # Keep explicit passed; never upgrade pending/unknown here.
            ver["status"] = "passed"
        ver["acceptance"] = evidence
        ver["required"] = True

    payload: dict[str, Any] = {
        "status": final_status,
        "error": final_error,
        "verification": ver,
    }
    updated = store.update_mission(mission["id"], **payload)
    event = (
        "RUN_COMPLETED"
        if final_status == "completed"
        else "RUN_FAILED"
        if final_status in {"failed", "blocked"}
        else "RUN_CANCELLED"
        if final_status == "cancelled"
        else "APPROVAL_REQUESTED"
        if final_status == "awaiting_approval"
        else "RUN_PAUSED"
        if final_status == "paused"
        else "STATUS_SYNC"
    )
    record(
        mission["id"],
        event,
        {
            "task_id": task_id,
            "status": final_status,
            "requested_status": status,
            "error": final_error,
            "verification": ver,
            "step_summary": step_summary,
        },
        component="mission_control",
        severity="error" if final_status in {"failed", "blocked"} else "info",
    )
    # Package I: same confirmed outcome for Mission Control + Tasks.
    try:
        from reasoning.long_task_resume import confirmed_outcome_from_task_and_mission

        outcome = confirmed_outcome_from_task_and_mission(
            task={"id": task_id, "status": status, "verification": ver, "step_summary": step_summary},
            mission={**(updated or mission), "verification": ver},
        )
        ver = {**ver, "confirmed_outcome": outcome.to_dict()}
        if updated is not None:
            updated = store.update_mission(
                mission["id"],
                verification=ver,
            ) or updated
            if updated is not None:
                updated["confirmed_outcome"] = outcome.to_dict()
                updated = attach_identity_links(updated) or updated
        elif mission is not None:
            mission = dict(mission)
            mission["confirmed_outcome"] = outcome.to_dict()
            mission["verification"] = ver
            return attach_identity_links(mission) or mission
    except Exception as packaging_exc:
        # Status write already happened; surface packaging failure instead of silent pass.
        try:
            record(
                mission["id"],
                "CONFIRMED_OUTCOME_PACKAGING_FAILED",
                {"error": str(packaging_exc), "task_id": task_id},
                component="mission_control",
                severity="warning",
            )
        except Exception:
            pass
        ver = {**(ver or {}), "confirmed_outcome_error": str(packaging_exc)}
        if updated is not None and isinstance(updated, dict):
            try:
                updated = store.update_mission(mission["id"], verification=ver) or updated
            except Exception:
                pass
        elif isinstance(mission, dict):
            mission = dict(mission)
            mission["verification"] = ver
            return attach_identity_links(mission) or mission
    return attach_identity_links(updated) if updated else updated


def compile_mission(
    store: Gen2Store,
    record: RecordFn,
    goal: str,
    *,
    title: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    goal_clean = (goal or "").strip()
    if not goal_clean:
        raise ValueError("goal is required")
    domain = (domain or _infer_domain(goal_clean)).lower()
    waves = _mission_template(goal_clean, domain)
    artifact_names = ["mission_report.md", "evidence_index.json"]
    step_ids = [str(step["id"]) for wave in waves for step in wave["steps"]]
    acceptance_checks = default_acceptance_checks(
        domain=domain, artifacts=artifact_names, step_ids=step_ids
    )
    # Human-readable prose retained for UI; executable checks live alongside.
    acceptance = [
        "Alle missie-stappen voltooid of eerlijk gemarkeerd als incomplete",
        "Acceptance criteria checklist afgevinkt met bewijs",
        "Verificatie/critic pass of expliciete failure state",
        "Artifacts en provenance beschikbaar voor claims",
        *acceptance_checks,
    ]
    budgets = {
        "max_tokens": 120_000,
        "max_time_seconds": 1800,
        "max_tool_calls": 40,
        "max_replans": 3,
        "replan_count": 0,
        "context_tokens": 8192,
    }
    gates = [
        {
            "id": "gate_plan_review",
            "kind": "human_approval",
            "before_wave": 1,
            "required": True,
            "status": "pending",
        },
        {
            "id": "gate_tool_autonomy",
            "kind": "human_approval",
            "before_wave": 2,
            "required": domain in {"finance", "coding", "osint"},
            "status": "pending",
        },
    ]
    resource_plan = resource_plan_for_domain(domain, waves=waves)
    ir = {
        "version": 1,
        "goal": goal_clean,
        "domain": domain,
        "objectives": [{"id": "obj_primary", "text": goal_clean}],
        "subtasks": [step for wave in waves for step in wave["steps"]],
        "dependencies": [
            {"from": dep, "to": step["id"]}
            for wave in waves
            for step in wave["steps"]
            for dep in step.get("depends_on") or []
        ],
        "agents": sorted({step["agent"] for wave in waves for step in wave["steps"]}),
        "models": {"planner": "dynamic", "worker": "dynamic", "critic": "dynamic"},
        "plugins_tools": _suggested_tools(domain),
        "io_contracts": {
            "input": {"goal": "string", "constraints": "object?"},
            "output": {"report": "markdown", "artifacts": "list", "verification": "object"},
        },
        "context_budgets": {"compiler_max_tokens": budgets["context_tokens"]},
        "token_time_tool_budgets": budgets,
        "permissions": {"network": "ask", "filesystem": "ask", "subprocess": "ask"},
        "retry_policies": {"max_replans": 3, "backoff": "bounded"},
        "checkpoints": [{"after_wave": w["wave"], "persist": True} for w in waves],
        "human_approval_gates": gates,
        "acceptance_criteria": acceptance,
        "acceptance_checks": acceptance_checks,
        "verification_requirements": {"critic": True, "evidence_refs": True},
        "artifacts": artifact_names,
        "execution_waves": waves,
        "resource_plan": resource_plan,
        "replan_count": 0,
        "replan_history": [],
    }
    mission = store.create_mission(
        {
            "title": title or goal_clean[:80],
            "goal": goal_clean,
            "status": "compiled",
            "ir": ir,
            "acceptance_criteria": acceptance,
            "budgets": budgets,
            "gates": gates,
            "verification": {"required": True, "status": "pending"},
        }
    )
    revision = persist_mission_revision(store, mission, cause="compile", note="initial compile")
    links = mission_identity_links(mission)
    record(
        mission["id"],
        "RUN_CREATED",
        {"kind": "mission", "goal": goal_clean, "identity_links": links, "revision": revision["version"]},
        component="mission_control",
    )
    record(
        mission["id"],
        "PLAN_CREATED",
        {
            "waves": len(waves),
            "steps": len(ir["subtasks"]),
            "identity_links": links,
            "revision": revision["version"],
        },
        component="mission_control",
    )
    return attach_identity_links({**mission, "revision": revision["version"]}) or mission


def start_mission(
    store: Gen2Store,
    record: RecordFn,
    mission_id: str,
    *,
    create_task: Any | None = None,
    schedule_task: Any | None = None,
    force_retry: bool = False,
) -> dict[str, Any]:
    mission = store.get_mission(mission_id)
    if not mission:
        raise ValueError("mission not found")

    status = str(mission.get("status") or "")
    if status in {"completed", "failed", "cancelled"} and not force_retry:
        raise ValueError(f"mission is {status}; pass force_retry to start a new execution")
    # Already handed off (dispatched) or executing (running) — idempotent reuse.
    if status in {"running", "dispatched"} and mission.get("task_id") and not force_retry:
        return {**mission, "idempotent": True, "reused_execution_id": mission.get("execution_id")}

    gates = list(mission.get("gates") or [])
    blocked = [
        g
        for g in gates
        if g.get("required")
        and g.get("status") != "approved"
        and int(g.get("before_wave", 0) or 0) <= 1
    ]
    if blocked:
        if status != "awaiting_approval":
            mission = store.update_mission(mission_id, status="awaiting_approval") or mission
        record(
            mission_id,
            "APPROVAL_REQUESTED",
            {"gates": [g["id"] for g in blocked]},
            component="mission_control",
        )
        return {**mission, "blocked_gates": blocked}

    expected = {"compiled", "ready", "queued", "blocked", "awaiting_approval"}
    claimed = store.claim_mission_start(
        mission_id, expected_statuses=expected, force_new=force_retry
    )
    outcome = claimed.pop("_start_outcome", None)
    reject = claimed.pop("_reject_reason", None)
    execution_id = claimed.pop("_execution_id", None) or claimed.get("execution_id")
    if outcome == "reused":
        return {**claimed, "idempotent": True, "reused_execution_id": claimed.get("execution_id")}
    if outcome == "in_progress":
        # Another caller holds the claim; wait briefly for task_id attachment.
        import time as _time

        for _ in range(100):
            _time.sleep(0.01)
            current = store.get_mission(mission_id) or {}
            if current.get("task_id") and current.get("status") in {"running", "dispatched"}:
                return {
                    **current,
                    "idempotent": True,
                    "reused_execution_id": current.get("execution_id"),
                }
            if current.get("status") in {"blocked", "failed"}:
                return current
        return {
            **(store.get_mission(mission_id) or claimed),
            "idempotent": True,
            "error": "start_in_progress",
        }
    if outcome == "rejected":
        raise ValueError(reject or "invalid mission start transition")

    def _fail(reason: str, final_status: str = "blocked") -> dict[str, Any]:
        result = store.finalize_mission_execution(
            mission_id,
            execution_id=str(execution_id),
            task_id=None,
            status=final_status,
            error=reason,
        )
        record(
            mission_id,
            "RUN_FAILED",
            {"reason": reason, "execution_id": execution_id},
            component="mission_control",
        )
        return {**result, "error": reason}

    if not callable(create_task):
        return _fail("task_bridge_unavailable", "blocked")

    try:
        task = create_task(claimed)
    except Exception as exc:
        return _fail(f"task_create_failed:{exc}", "failed")

    task_id = None
    if isinstance(task, dict):
        raw_id = task.get("id")
        task_id = str(raw_id) if raw_id else None
        if task.get("note") == "task_bridge_unavailable" or raw_id in {None, "", "None"}:
            task_id = None
    elif task is not None:
        task_id = str(task)

    if not task_id:
        return _fail("task_bridge_unavailable", "blocked")

    # Honesty: task is created+queued, not yet executing — report dispatched, not running.
    result = store.finalize_mission_execution(
        mission_id,
        execution_id=str(execution_id),
        task_id=task_id,
        status="dispatched",
        error=None,
    )
    # Dispatch into Work Runtime after mission row is honest (avoids race with running sync).
    if callable(schedule_task):
        try:
            schedule_task(task_id)
        except Exception as exc:
            return _fail(f"task_schedule_failed:{exc}", "failed")
    record(
        mission_id,
        "RUN_CREATED",
        {"task_id": task_id, "execution_id": execution_id, "phase": "dispatched"},
        component="mission_control",
    )
    return result


def decide_mission_gate(
    store: Gen2Store,
    record: RecordFn,
    mission_id: str,
    gate_id: str,
    *,
    approve: bool,
    note: str = "",
) -> dict[str, Any]:
    import hashlib

    mission = store.get_mission(mission_id)
    if not mission:
        raise ValueError("mission not found")
    status = str(mission.get("status") or "compiled")
    if status in {"completed", "cancelled"}:
        raise ValueError(f"cannot decide gates on {status} mission")
    if status == "running" and not approve:
        # Rejection while running is allowed → failed.
        pass
    elif status == "failed" and approve:
        raise ValueError("cannot approve gates on a failed mission; compile or force_retry first")

    gates = list(mission.get("gates") or [])
    found = False
    fingerprint: str | None = None
    for gate in gates:
        if gate.get("id") == gate_id:
            if gate.get("status") == "rejected" and approve:
                raise ValueError("rejected gate cannot be flipped to approved")
            if gate.get("status") == "revoked":
                raise ValueError("revoked gate cannot be decided; recompile mission")
            material = (
                f"{mission_id}|{gate_id}|{approve}|{(note or '').strip()}|{mission.get('updated_at') or ''}"
            )
            fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
            gate["status"] = "approved" if approve else "rejected"
            gate["note"] = note
            gate["decision_fingerprint"] = fingerprint
            gate["decided_at"] = utc_now()
            found = True
    if not found:
        raise ValueError("gate not found")

    if not approve:
        new_status = "failed"
        record(
            mission_id,
            "RUN_FAILED",
            {"gate_id": gate_id, "note": note, "fingerprint": fingerprint},
            component="mission_control",
        )
    else:
        pending_start = [
            g
            for g in gates
            if g.get("required")
            and g.get("status") != "approved"
            and int(g.get("before_wave", 0) or 0) <= 1
        ]
        if pending_start:
            new_status = "awaiting_approval"
        elif status in {"running", "paused", "awaiting_approval", "dispatched"} and mission.get("task_id"):
            # Mid-wave gate cleared: resume Work Runtime rather than resetting to ready.
            new_status = "running"
        elif status == "running":
            new_status = "running"
        else:
            new_status = "ready"

    if new_status != status and new_status not in MISSION_TRANSITIONS.get(status, set()):
        # Allow gate-driven transitions including mid-wave resume.
        allowed_gate = status in {
            "compiled",
            "awaiting_approval",
            "ready",
            "blocked",
            "failed",
            "paused",
            "running",
            "dispatched",
        } and new_status in {"ready", "failed", "awaiting_approval", "running"}
        if not allowed_gate:
            raise ValueError(f"invalid_transition:{status}->{new_status}")

    mission = store.update_mission(mission_id, gates=gates, status=new_status) or mission
    revision = persist_mission_revision(
        store,
        mission,
        cause="gate_approve" if approve else "gate_reject",
        note=f"{gate_id}:{(note or '')[:200]}",
    )
    links = mission_identity_links(mission)
    record(
        mission_id,
        "APPROVAL",
        {
            "gate_id": gate_id,
            "approve": approve,
            "note": note,
            "fingerprint": fingerprint,
            "identity_links": links,
            "revision": revision["version"],
        },
        component="mission_control",
    )
    return attach_identity_links({**mission, "revision": revision["version"]}) or mission


def revoke_mission_gate(
    store: Gen2Store,
    record: RecordFn,
    mission_id: str,
    gate_id: str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Revoke a previously approved gate; mission returns to awaiting_approval when active."""
    mission = store.get_mission(mission_id)
    if not mission:
        raise ValueError("mission not found")
    status = str(mission.get("status") or "")
    if status in {"completed", "cancelled"}:
        raise ValueError(f"cannot revoke gates on {status} mission")
    gates = list(mission.get("gates") or [])
    found = False
    for gate in gates:
        if gate.get("id") == gate_id:
            if gate.get("status") != "approved":
                raise ValueError("only approved gates can be revoked")
            gate["status"] = "revoked"
            gate["revoke_reason"] = (reason or "")[:2000]
            gate["revoked_at"] = utc_now()
            found = True
    if not found:
        raise ValueError("gate not found")
    new_status = status
    if status in {"ready", "running", "paused", "queued"}:
        new_status = "awaiting_approval"
    mission = store.update_mission(mission_id, gates=gates, status=new_status) or mission
    revision = persist_mission_revision(
        store, mission, cause="gate_revoke", note=f"{gate_id}:{(reason or '')[:200]}"
    )
    links = mission_identity_links(mission)
    record(
        mission_id,
        "APPROVAL",
        {
            "gate_id": gate_id,
            "revoked": True,
            "reason": reason,
            "identity_links": links,
            "revision": revision["version"],
        },
        component="mission_control",
    )
    return attach_identity_links({**mission, "revision": revision["version"]}) or mission


def mission_revision_snapshot(mission: dict[str, Any]) -> dict[str, Any]:
    """Capture a comparable revision payload for mission IR/gates/acceptance."""
    return {
        "mission_id": mission.get("id"),
        "status": mission.get("status"),
        "ir": mission.get("ir") or {},
        "gates": mission.get("gates") or [],
        "acceptance_criteria": mission.get("acceptance_criteria") or [],
        "budgets": mission.get("budgets") or {},
        "verification": mission.get("verification") or {},
        "updated_at": mission.get("updated_at"),
    }


def persist_mission_revision(
    store: Gen2Store,
    mission: dict[str, Any],
    *,
    cause: str,
    note: str = "",
) -> dict[str, Any]:
    """Persist a revision snapshot for compile/replan/gate changes."""
    snap = mission_revision_snapshot(mission)
    return store.save_mission_revision(
        str(mission["id"]),
        snap,
        cause=cause,
        note=note,
    )


def list_mission_revisions(store: Gen2Store, mission_id: str, limit: int = 50) -> list[dict[str, Any]]:
    if not store.get_mission(mission_id):
        raise ValueError("mission not found")
    return store.list_mission_revisions(mission_id, limit=limit)


def diff_mission_revisions(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Shallow structural diff between two mission revision snapshots."""
    changes: list[dict[str, Any]] = []
    for key in ("status", "updated_at"):
        if before.get(key) != after.get(key):
            changes.append({"field": key, "before": before.get(key), "after": after.get(key)})
    before_steps = {
        str(s.get("id")): s
        for wave in ((before.get("ir") or {}).get("execution_waves") or [])
        for s in (wave.get("steps") or [])
    }
    after_steps = {
        str(s.get("id")): s
        for wave in ((after.get("ir") or {}).get("execution_waves") or [])
        for s in (wave.get("steps") or [])
    }
    for sid in sorted(set(before_steps) | set(after_steps)):
        if sid not in before_steps:
            changes.append({"field": f"step:{sid}", "before": None, "after": after_steps[sid]})
        elif sid not in after_steps:
            changes.append({"field": f"step:{sid}", "before": before_steps[sid], "after": None})
        elif before_steps[sid] != after_steps[sid]:
            changes.append({"field": f"step:{sid}", "before": before_steps[sid], "after": after_steps[sid]})
    before_gates = {str(g.get("id")): g for g in (before.get("gates") or [])}
    after_gates = {str(g.get("id")): g for g in (after.get("gates") or [])}
    for gid in sorted(set(before_gates) | set(after_gates)):
        if before_gates.get(gid) != after_gates.get(gid):
            changes.append(
                {
                    "field": f"gate:{gid}",
                    "before": before_gates.get(gid),
                    "after": after_gates.get(gid),
                }
            )
    before_budgets = before.get("budgets") or {}
    after_budgets = after.get("budgets") or {}
    if before_budgets != after_budgets:
        changes.append({"field": "budgets", "before": before_budgets, "after": after_budgets})
    return {
        "mission_id": after.get("mission_id") or before.get("mission_id"),
        "change_count": len(changes),
        "changes": changes,
    }


def diff_mission_revision_versions(
    store: Gen2Store,
    mission_id: str,
    from_version: int,
    to_version: int,
) -> dict[str, Any]:
    left = store.get_mission_revision(mission_id, int(from_version))
    right = store.get_mission_revision(mission_id, int(to_version))
    if not left or not right:
        raise ValueError("revision not found")
    diff = diff_mission_revisions(left["snapshot"], right["snapshot"])
    return {
        **diff,
        "from_version": int(from_version),
        "to_version": int(to_version),
        "from_cause": left.get("cause"),
        "to_cause": right.get("cause"),
    }


def mission_identity_links(
    mission: dict[str, Any] | None,
    *,
    step_summary: dict[str, Any] | None = None,
    artifacts: list[Any] | None = None,
) -> dict[str, Any]:
    """Structured Mission↔Task↔Run↔Step↔Artifact identity links (B1.8)."""
    mission = dict(mission or {})
    ir = dict(mission.get("ir") or {})
    ver = dict(mission.get("verification") or {})
    summary = dict(step_summary or ver.get("step_summary") or {})
    waves = list(ir.get("execution_waves") or [])
    steps: list[dict[str, Any]] = []
    for wave in waves:
        for step in wave.get("steps") or []:
            steps.append(
                {
                    "id": step.get("id"),
                    "agent": step.get("agent"),
                    "title": step.get("title"),
                    "wave": wave.get("wave"),
                    "depends_on": list(step.get("depends_on") or []),
                }
            )
    art_list: list[dict[str, Any]] = []
    planned = list(ir.get("artifacts") or [])
    for name in planned:
        art_list.append({"name": name, "role": "planned"})
    for item in artifacts or ver.get("artifacts") or summary.get("artifacts") or []:
        if isinstance(item, dict):
            art_list.append(
                {
                    "name": item.get("name") or item.get("id") or item.get("path"),
                    "id": item.get("id"),
                    "role": item.get("role") or "produced",
                }
            )
        elif item:
            art_list.append({"name": str(item), "role": "produced"})
    run_id = (
        mission.get("execution_id")
        or mission.get("run_id")
        or (mission.get("id") if mission.get("id") else None)
    )
    return {
        "mission_id": mission.get("id"),
        "task_id": mission.get("task_id"),
        "run_id": run_id,
        "execution_id": mission.get("execution_id"),
        "steps": steps,
        "step_ids": [s["id"] for s in steps if s.get("id")],
        "artifacts": art_list,
        "gates": [
            {"id": g.get("id"), "status": g.get("status"), "before_wave": g.get("before_wave")}
            for g in (mission.get("gates") or [])
        ],
        "domain": ir.get("domain"),
        "status": mission.get("status"),
    }


def attach_identity_links(mission: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return mission dict with ``links`` object attached (non-mutating copy)."""
    if not mission:
        return mission
    out = dict(mission)
    out["links"] = mission_identity_links(out)
    return out


def portfolio_view(
    store: Gen2Store,
    *,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Portfolio summary: missions with status/domain/budgets/gates (B1.5)."""
    status_filter = (status or "").strip() or None
    missions = store.list_missions(limit=limit, status=status_filter)
    rows: list[dict[str, Any]] = []
    by_status: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for mission in missions:
        ir = dict(mission.get("ir") or {})
        domain = str(ir.get("domain") or "unknown")
        gates = list(mission.get("gates") or [])
        pending_gates = [g for g in gates if g.get("required") and g.get("status") != "approved"]
        blocked = bool(pending_gates) or str(mission.get("status") or "") in {
            "blocked",
            "awaiting_approval",
        }
        st = str(mission.get("status") or "unknown")
        by_status[st] = by_status.get(st, 0) + 1
        by_domain[domain] = by_domain.get(domain, 0) + 1
        rows.append(
            {
                "id": mission.get("id"),
                "title": mission.get("title"),
                "goal": mission.get("goal"),
                "status": st,
                "domain": domain,
                "task_id": mission.get("task_id"),
                "execution_id": mission.get("execution_id"),
                "budgets": mission.get("budgets") or {},
                "gates_summary": {
                    "total": len(gates),
                    "pending_required": len(pending_gates),
                    "approved": sum(1 for g in gates if g.get("status") == "approved"),
                    "rejected": sum(1 for g in gates if g.get("status") == "rejected"),
                    "revoked": sum(1 for g in gates if g.get("status") == "revoked"),
                },
                "blocked_or_waiting": blocked,
                "updated_at": mission.get("updated_at"),
                "created_at": mission.get("created_at"),
                "links": mission_identity_links(mission),
            }
        )
    return {
        "missions": rows,
        "count": len(rows),
        "filter": {"status": status_filter, "limit": limit},
        "by_status": by_status,
        "by_domain": by_domain,
    }


def _infer_domain(goal: str) -> str:
    g = goal.lower()
    if any(k in g for k in ("nvidia", "aandelen", "crypto", "earnings", "trading", "markt")):
        return "finance"
    if any(k in g for k in ("code", "refactor", "bug", "test", "repo")):
        return "coding"
    if any(k in g for k in ("onderzoek", "research", "intelligence", "analyse")):
        return "research"
    return "general"


def _mission_template(goal: str, domain: str) -> list[dict[str, Any]]:
    if domain == "finance":
        return [
            {
                "wave": 0,
                "steps": [
                    {"id": "s_scope", "title": "Scope & acceptance", "agent": "research_planner", "depends_on": [], "tools": []},
                    {"id": "s_sources", "title": "Bronnen & entity map", "agent": "research_worker", "depends_on": ["s_scope"], "tools": ["financial-news-intelligence"]},
                ],
            },
            {
                "wave": 1,
                "steps": [
                    {"id": "s_events", "title": "Event extractie & verificatie", "agent": "evidence_auditor", "depends_on": ["s_sources"], "tools": []},
                    {"id": "s_market", "title": "PAPER markt/analogues", "agent": "trading_specialist", "depends_on": ["s_events"], "tools": ["trading"]},
                ],
            },
            {
                "wave": 2,
                "steps": [
                    {"id": "s_synth", "title": "Synthese rapport", "agent": "chat", "depends_on": ["s_events", "s_market"], "tools": []},
                    {"id": "s_critic", "title": "Onafhankelijke critic", "agent": "critic", "depends_on": ["s_synth"], "tools": []},
                ],
            },
        ]
    if domain == "coding":
        return [
            {
                "wave": 0,
                "steps": [
                    {"id": "s_plan", "title": "Plan & acceptance", "agent": "executor", "depends_on": [], "tools": []},
                    {"id": "s_index", "title": "Workspace index", "agent": "workspace", "depends_on": ["s_plan"], "tools": []},
                ],
            },
            {
                "wave": 1,
                "steps": [
                    {"id": "s_build", "title": "Implementatie + tests", "agent": "build", "depends_on": ["s_index"], "tools": ["terminal"]},
                    {"id": "s_critic", "title": "Critic / verify", "agent": "critic", "depends_on": ["s_build"], "tools": []},
                ],
            },
        ]
    # research / general
    return [
        {
            "wave": 0,
            "steps": [
                {"id": "s_scope", "title": "Doel & criteria", "agent": "research_planner", "depends_on": [], "tools": []},
                {"id": "s_retrieve", "title": "Context compiler + retrieval", "agent": "retrieval", "depends_on": ["s_scope"], "tools": []},
            ],
        },
        {
            "wave": 1,
            "steps": [
                {"id": "s_research", "title": "Primair onderzoek", "agent": "research_worker", "depends_on": ["s_retrieve"], "tools": []},
                {"id": "s_skeptic", "title": "Skeptic / contradictions", "agent": "evidence_auditor", "depends_on": ["s_research"], "tools": []},
            ],
        },
        {
            "wave": 2,
            "steps": [
                {"id": "s_synth", "title": "Synthese", "agent": "chat", "depends_on": ["s_research", "s_skeptic"], "tools": []},
                {"id": "s_critic", "title": "Critic", "agent": "critic", "depends_on": ["s_synth"], "tools": []},
                {"id": "s_archive", "title": "Knowledge/Memory update", "agent": "knowledge_builder", "depends_on": ["s_critic"], "tools": []},
            ],
        },
    ]


def _suggested_tools(domain: str) -> list[str]:
    if domain == "finance":
        return ["financial-news-intelligence", "fincept-data", "paper_trading"]
    if domain == "coding":
        return ["terminal", "workspace_symbols", "build_agent"]
    return ["knowledge_search", "web_research_optional"]
