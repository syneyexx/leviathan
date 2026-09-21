"""Gen2 readiness dashboard — honest capability status aggregation.

``phase`` is implemented-only (back-compat). Use ``capability_status`` for
available / operationally_tested / quality_evaluated / simulated / degraded /
blocked / unverified_on_host. Host-only claims stay UNVERIFIED until proven.
"""

from __future__ import annotations

from typing import Any

from gen2.sandbox import detect_host_sandbox_capabilities
from gen2.store import Gen2Store


def capability_status_fields(
    *,
    implemented: bool,
    available: bool,
    tested: bool,
    quality: bool,
    note: str = "",
    simulated: bool = False,
    degraded: bool = False,
    blocked: bool = False,
    unverified_on_host: bool = False,
) -> dict[str, Any]:
    # Promotion rules: never claim operationally_tested from import/API presence alone.
    if simulated and tested:
        tested = False
        note = (note + " " if note else "") + "simulated_runs_do_not_count_as_operationally_tested"
    return {
        "implemented": implemented,
        "available_on_host": available,
        "operationally_tested": tested,
        "quality_evaluated": quality,
        "simulated": simulated,
        "degraded": degraded,
        "blocked": blocked,
        "unverified_on_host": unverified_on_host,
        "note": note,
    }


def build_dashboard(store: Gen2Store, data_root: Any | None = None) -> dict[str, Any]:
    """Aggregate Gen2 store state into the Mission Control dashboard payload."""
    from pathlib import Path

    missions = store.list_missions(limit=10)
    eval_runs = store.list_eval_runs(limit=5)
    matrix = store.capability_matrix()
    skills = store.list_skills(limit=10)
    committees = store.list_committees(limit=5)
    nodes = store.list_nodes()
    envelopes = store.list_envelopes()
    edges = store.list_graph_edges(limit=5000)
    workflows = store.list_workflows(limit=10)
    workflow_tested = any(str(w.get("status") or "") in {"tested", "promoted"} for w in workflows)
    workflow_promoted = any(str(w.get("status") or "") == "promoted" for w in workflows)
    paired = 0
    if data_root is not None:
        try:
            from gen2.compute_fabric import list_pairings

            paired = len(list_pairings(Path(data_root)))
        except Exception:
            paired = 0

    live_invoked = any(
        bool((r.get("summary") or {}).get("model_invoked"))
        and str(r.get("mode") or "") == "live_model"
        and str(r.get("status") or "") == "completed"
        for r in eval_runs
    )
    live_quality = any(
        bool((r.get("summary") or {}).get("model_invoked"))
        and not bool((r.get("summary") or {}).get("not_model_quality", True))
        for r in eval_runs
    )
    committee_live = any(
        str((c.get("consensus") or {}).get("mode") or "").startswith("live")
        or any(p.get("model_invoked") for p in (c.get("positions") or []))
        for c in committees
    )
    promoted = any(str(s.get("status") or "") == "promoted" for s in skills)
    host_sandbox = detect_host_sandbox_capabilities()
    job_api = bool(host_sandbox.get("job_objects"))
    sandbox_host = {
        **capability_status_fields(
            implemented=True,
            available=True,  # tiers 0/1
            tested=False,  # envelope rows ≠ OS isolation proof
            quality=False,
            unverified_on_host=not job_api,
            note=(
                "Tiers 0/1 application envelopes always available. "
                + (
                    "Tier 2 Job Object enforcement implemented; operational host proof still required "
                    "(API presence ≠ operationally_tested)."
                    if job_api
                    else "Tier 2 Job Objects unavailable on this host — UNVERIFIED_ON_HOST / fail-closed."
                )
            ),
        ),
        "os_isolation_enforced": False,  # never from probe alone
        "available_tiers": host_sandbox.get("available_tiers"),
        "job_objects": job_api,
        "job_object_enforcement_implemented": host_sandbox.get("job_object_enforcement_implemented"),
        "docker": host_sandbox.get("docker"),
        "wsl": host_sandbox.get("wsl"),
        "verification_status": host_sandbox.get("verification_status"),
    }

    capability_status = {
        "1_eval_lab": capability_status_fields(
            implemented=True,
            available=True,
            tested=bool(eval_runs) and live_invoked,
            quality=live_quality,
            unverified_on_host=not live_invoked,
            note=(
                "Deterministic software suite available. Live LM smoke/quality only when model_invoked evidence exists."
                if not live_quality
                else "Live quality samples present."
            ),
        ),
        "1_context_compiler": capability_status_fields(
            implemented=True,
            available=True,
            tested=False,
            quality=False,
            note="Implemented + unit-characterized; operationally_tested requires host run evidence, not import success.",
        ),
        "1_flight_recorder": capability_status_fields(
            implemented=True,
            available=True,
            tested=False,
            quality=False,
            note="Inspect/compare implemented; side-effect replay blocked by default; not auto operationally_tested.",
        ),
        "2_mission_control": capability_status_fields(
            implemented=True,
            available=True,
            tested=bool(missions),
            quality=False,
            note="Compile/start/gates/budgets wired; tested only when missions exist in store.",
        ),
        "2_committee": capability_status_fields(
            implemented=True,
            available=True,
            tested=bool(committees),
            quality=committee_live,
            unverified_on_host=not committee_live,
            note="Heuristic always available; live specialist quality only when LM invoked.",
        ),
        "2_agent_factory": capability_status_fields(
            implemented=True,
            available=True,
            tested=bool(skills),
            quality=promoted,
            note="Executable handler benchmark required; free-text workflows fail.",
        ),
        "2_workflows": capability_status_fields(
            implemented=True,
            available=True,
            tested=workflow_tested,
            quality=workflow_promoted,
            note=(
                "Workflow IR + dry-run/sandbox-run + promotion implemented. "
                "operationally_tested only when a workflow reaches tested/promoted with run evidence; "
                "dry-run is not live execution."
                if not workflow_tested
                else (
                    "Promoted workflows present."
                    if workflow_promoted
                    else "Tested workflows present; promotion requires human_approved."
                )
            ),
        ),
        "3_sandbox": sandbox_host,
        "4_temporal_graph": capability_status_fields(
            implemented=True,
            available=True,
            tested=bool(edges),
            quality=False,
            note="Valid-time + observed-time queries available; not a full graph DB engine.",
        ),
        "4_finance_fusion": capability_status_fields(
            implemented=True,
            available=True,
            tested=False,
            quality=False,
            note="PAPER-only event fusion implemented; operationally_tested requires real fuse evidence.",
        ),
        "5_compute_fabric": capability_status_fields(
            implemented=True,
            available=True,
            tested=bool(nodes),
            quality=False,
            note=(
                "Local + LAN worker MVP (trusted pairing, typed jobs). "
                f"Paired workers: {paired}. "
                "Unreachable/unpaired remotes return blocked/unavailable — not endless queue. "
                "Physical multi-machine unverified; same-host process pair is the tested path. "
                "No unbounded remote shell."
            ),
        ),
    }
    # Back-compat boolean map = implemented only (not "ready/quality").
    phase = {key: bool(val.get("implemented")) for key, val in capability_status.items()}
    return {
        "missions": missions,
        "eval_runs": eval_runs,
        "matrix_rows": len(matrix),
        "skills": skills,
        "workflows": workflows,
        "committees": committees,
        "market_events": store.list_market_events(limit=5),
        "nodes": nodes,
        "envelopes": len(envelopes),
        "graph_edges": len(edges),
        "phase": phase,
        "capability_status": capability_status,
        "live_model_smoke_seen": live_invoked,
        "live_model_quality_seen": live_quality,
        "readiness_note": (
            "phase = implemented only. capability_status separates available_on_host / "
            "operationally_tested / quality_evaluated / unverified_on_host. "
            "Import success, binary presence, or mock tests never promote operationally_tested."
        ),
    }
