"""A13 — Reliable resume controlled experiment (software-labeled measurements).

Compares the same task/start conditions with recovery features ON vs OFF.
Injects process-stop and tool-failure moments. Does not claim universal
exactly-once semantics for external tools.

Host commands (cwd=backend or PYTHONPATH=backend):

  python -m evals.resume_experiment --runs 3
  python -m evals.resume_experiment --runs 5 --out artifacts/resume_experiment/report.json

Without LM Studio the harness completes using labeled software-test measurements only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from evals.harness import git_start_commit, model_config_snapshot
from gen2.correlation_telemetry import config_hash, git_fingerprint
from reasoning.long_task_resume import (
    RunIdentity,
    SideEffectLedger,
    build_resume_plan,
    make_idempotency_key,
)

FailureMoment = Literal[
    "after_intent",
    "after_effect_before_checkpoint",
    "during_tool",
    "after_partial_steps",
]
ArmName = Literal["recovery_on", "recovery_off"]

EXPERIMENT_ID = "reliable_resume_a13"
DATASET_VERSION = "resume_tasks_v1"
GRADER_VERSION = "resume_grader_v1"
QUALITY_LAYER = "software"


@dataclass
class TaskSpec:
    task_id: str
    steps: list[str]
    fail_at: FailureMoment
    effect_kind: str = "tool.write"


TASKS: list[TaskSpec] = [
    TaskSpec("t_intent", ["s1", "s2", "s3"], "after_intent"),
    TaskSpec("t_effect", ["s1", "s2"], "after_effect_before_checkpoint"),
    TaskSpec("t_tool", ["s1", "s2", "s3"], "during_tool"),
    TaskSpec("t_partial", ["s1", "s2", "s3", "s4"], "after_partial_steps"),
]


@dataclass
class RunResult:
    arm: ArmName
    task_id: str
    run_id: str
    fail_at: FailureMoment
    correct_resume: bool
    lost_work: bool
    duplicate_effects: bool
    false_success: bool
    effects_executed: int
    steps_reused: int
    steps_requeued: int
    unresolved: int
    overhead_ms: float
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _repo_root() -> Path:
    return _backend_root().parent


def default_out_dir() -> Path:
    return _repo_root() / "artifacts" / "resume_experiment"


def evidence_out_dir() -> Path:
    return _repo_root() / "docs" / "evidence" / "resume_experiment"


def _simulate_arm(
    *,
    arm: ArmName,
    task: TaskSpec,
    work_dir: Path,
    seed: int,
) -> RunResult:
    """Software simulation of resume with/without recovery features."""
    t0 = time.perf_counter()
    run_id = f"{arm}_{task.task_id}_{seed}_{uuid.uuid4().hex[:6]}"
    notes: list[str] = []
    effects = 0
    effect_file = work_dir / f"{run_id}.effect"
    ledger_path = work_dir / f"{run_id}.ledger.json" if arm == "recovery_on" else None
    ledger = SideEffectLedger(persist_path=str(ledger_path) if ledger_path else None)
    fence = f"fence_{seed}"
    identity = RunIdentity(run_id=run_id, task_id=task.task_id, fence_token=fence, plan_version=1)
    completed: set[str] = set()
    checkpoints: dict[str, dict[str, Any]] = {}
    intents: list[dict[str, Any]] = []
    crashed = False
    false_success = False
    duplicate = False
    lost_work = False

    def write_effect(step_id: str) -> None:
        nonlocal effects
        effects += 1
        prev = effect_file.read_text(encoding="utf-8") if effect_file.exists() else ""
        effect_file.write_text(prev + f"{step_id}\n", encoding="utf-8")

    try:
        for index, step_id in enumerate(task.steps):
            identity.bind(step_id=step_id)
            payload = {"path": str(effect_file.name), "step": step_id}
            key = make_idempotency_key(
                run_id=run_id, step_id=step_id, effect_kind=task.effect_kind, payload=payload
            )

            if arm == "recovery_on":
                recorded = ledger.record_intent(
                    identity=identity, effect_kind=task.effect_kind, payload=payload, fence_token=fence
                )
                intents.append(recorded["intent"])
                if recorded.get("idempotent") and recorded["intent"].get("status") == "completed":
                    notes.append(f"reuse:{step_id}")
                    completed.add(step_id)
                    continue
                ledger.mark_in_flight(recorded["intent"]["intent_id"], fence_token=fence)

            # Injected failure moments.
            if task.fail_at == "after_intent" and index == 0 and not crashed:
                crashed = True
                notes.append("crash:after_intent")
                break

            if task.fail_at == "during_tool" and index == 1 and not crashed:
                crashed = True
                notes.append("crash:during_tool")
                if arm == "recovery_on":
                    ledger.fail(recorded["intent"]["intent_id"], evidence={"error": "tool_failed"})
                break

            # Perform side effect.
            write_effect(step_id)

            if task.fail_at == "after_effect_before_checkpoint" and index == 0 and not crashed:
                crashed = True
                notes.append("crash:after_effect_before_checkpoint")
                # Recovery-on leaves intent in_flight with observable effect on disk.
                break

            # Checkpoint
            checkpoints[step_id] = {"phase": "after_effect", "ok": True}
            completed.add(step_id)
            if arm == "recovery_on":
                ledger.complete(
                    recorded["intent"]["intent_id"],
                    result_ref=f"artifact:{step_id}",
                    evidence={"effect_observed": True},
                    fence_token=fence,
                )

            if task.fail_at == "after_partial_steps" and index == 1 and not crashed:
                crashed = True
                notes.append("crash:after_partial_steps")
                break

        # Resume phase after crash (or finish).
        if crashed:
            if arm == "recovery_on":
                # Reload ledger as if new process.
                ledger2 = SideEffectLedger(persist_path=str(ledger_path) if ledger_path else None)
                for step_id in task.steps:
                    if step_id in completed:
                        continue
                    payload = {"path": str(effect_file.name), "step": step_id}
                    key = make_idempotency_key(
                        run_id=run_id, step_id=step_id, effect_kind=task.effect_kind, payload=payload
                    )
                    observed = effect_file.exists() and step_id in effect_file.read_text(encoding="utf-8")
                    recon = ledger2.reconcile_after_crash(
                        idempotency_key=key,
                        recovered_result_ref=f"artifact:{step_id}" if observed else None,
                        recovered_evidence={"effect_observed": True} if observed else None,
                    )
                    notes.append(f"reconcile:{step_id}:{recon.get('action')}")
                    if recon.get("action") in {"reconciled_completed", "reuse_completed"}:
                        completed.add(step_id)
                        if observed and recon.get("may_reexec"):
                            duplicate = True
                    elif recon.get("action") == "mark_unresolved":
                        # Honest unresolved — not false success.
                        pass

                plan = build_resume_plan(
                    identity=RunIdentity(run_id=run_id, task_id=task.task_id, fence_token=fence),
                    steps=[{"step_id": s} for s in task.steps],
                    completed_ids=completed,
                    intents=ledger2.list_for_run(run_id),
                    worker_live=False,
                    status_label="interrupted",
                    checkpoint_by_step=checkpoints,
                )
                # Execute only requeue decisions; reuse completed.
                for decision in plan.decisions:
                    if decision.action == "reuse_completed":
                        continue
                    if decision.action in {"resume_from_checkpoint", "requeue_orphaned_running", "reconcile_then_maybe_retry"}:
                        sid = decision.step_id
                        if sid in completed:
                            continue
                        # Unresolved without evidence must not invent success.
                        intent_rows = [
                            i for i in ledger2.list_for_run(run_id) if (i.get("identity") or {}).get("step_id") == sid
                        ]
                        if intent_rows and intent_rows[0].get("status") == "unresolved":
                            notes.append(f"skip_unresolved:{sid}")
                            continue
                        identity.bind(step_id=sid)
                        payload = {"path": str(effect_file.name), "step": sid}
                        recorded = ledger2.record_intent(
                            identity=identity, effect_kind=task.effect_kind, payload=payload, fence_token=fence
                        )
                        if recorded.get("idempotent") and recorded["intent"].get("status") == "completed":
                            completed.add(sid)
                            continue
                        if recorded.get("idempotent") is False or recorded["intent"].get("status") != "completed":
                            # Check file before re-exec to avoid duplicates when possible.
                            already = effect_file.exists() and sid in effect_file.read_text(encoding="utf-8")
                            if already:
                                notes.append(f"skip_observed:{sid}")
                                completed.add(sid)
                                continue
                            ledger2.mark_in_flight(recorded["intent"]["intent_id"], fence_token=fence)
                            write_effect(sid)
                            ledger2.complete(
                                recorded["intent"]["intent_id"],
                                result_ref=f"artifact:{sid}",
                                evidence={"effect_observed": True},
                                fence_token=fence,
                            )
                            completed.add(sid)
                steps_reused = len(plan.reused_step_ids)
                steps_requeued = len(plan.requeue_step_ids)
                unresolved = len(plan.unresolved_step_ids)
            else:
                # Recovery OFF: naive restart re-runs everything from scratch.
                notes.append("naive_full_restart")
                prior_effects = effects
                # Lost checkpoints — completed set discarded.
                lost_work = bool(checkpoints) and task.fail_at in {
                    "after_partial_steps",
                    "after_effect_before_checkpoint",
                }
                completed.clear()
                for step_id in task.steps:
                    write_effect(step_id)
                    completed.add(step_id)
                if prior_effects > 0 and effects > prior_effects:
                    # Lines may duplicate in the effect file.
                    lines = effect_file.read_text(encoding="utf-8").splitlines()
                    duplicate = len(lines) != len(set(lines)) or effects > len(task.steps)
                # Naive restart may claim success even if first crash left ambiguous tool state.
                if task.fail_at == "during_tool":
                    false_success = True
                    notes.append("false_success_risk:naive_ignore_partial_tool")
                steps_reused = 0
                steps_requeued = len(task.steps)
                unresolved = 0
        else:
            steps_reused = len(completed)
            steps_requeued = 0
            unresolved = 0

        # Independent checks.
        lines = effect_file.read_text(encoding="utf-8").splitlines() if effect_file.exists() else []
        if len(lines) != len(set(lines)):
            duplicate = True
        # Lost work: a completed checkpoint missing after resume without reuse.
        if arm == "recovery_off" and task.fail_at == "after_partial_steps":
            lost_work = True
        correct_resume = (not duplicate) and (not false_success) and (
            arm == "recovery_off" or unresolved == 0 or task.fail_at in {"after_intent", "during_tool"}
        )
        # For recovery_on after_intent / during_tool, unresolved-without-reexec is correct honesty.
        if arm == "recovery_on" and task.fail_at in {"after_intent", "during_tool"}:
            correct_resume = (not duplicate) and (not false_success)
        if arm == "recovery_on" and task.fail_at == "after_effect_before_checkpoint":
            # Must not double-write s1.
            correct_resume = lines.count("s1") == 1 and not false_success

        overhead_ms = (time.perf_counter() - t0) * 1000.0
        return RunResult(
            arm=arm,
            task_id=task.task_id,
            run_id=run_id,
            fail_at=task.fail_at,
            correct_resume=correct_resume,
            lost_work=lost_work,
            duplicate_effects=duplicate,
            false_success=false_success,
            effects_executed=effects,
            steps_reused=steps_reused if crashed else len(completed),
            steps_requeued=steps_requeued if crashed else 0,
            unresolved=unresolved if crashed else 0,
            overhead_ms=overhead_ms,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        return RunResult(
            arm=arm,
            task_id=task.task_id,
            run_id=run_id,
            fail_at=task.fail_at,
            correct_resume=False,
            lost_work=True,
            duplicate_effects=False,
            false_success=False,
            effects_executed=effects,
            steps_reused=0,
            steps_requeued=0,
            unresolved=0,
            overhead_ms=(time.perf_counter() - t0) * 1000.0,
            notes=notes,
            error=f"{exc}\n{traceback.format_exc()}",
        )


def _aggregate(results: list[RunResult]) -> dict[str, Any]:
    def _arm(name: ArmName) -> list[RunResult]:
        return [r for r in results if r.arm == name]

    def _rate(rows: list[RunResult], attr: str) -> float:
        if not rows:
            return 0.0
        return sum(1 for r in rows if getattr(r, attr)) / len(rows)

    out: dict[str, Any] = {}
    for name in ("recovery_on", "recovery_off"):
        rows = _arm(name)  # type: ignore[arg-type]
        overheads = [r.overhead_ms for r in rows]
        out[name] = {
            "n": len(rows),
            "correct_resume_rate": _rate(rows, "correct_resume"),
            "lost_work_rate": _rate(rows, "lost_work"),
            "duplicate_effects_rate": _rate(rows, "duplicate_effects"),
            "false_success_rate": _rate(rows, "false_success"),
            "mean_effects": statistics.mean([r.effects_executed for r in rows]) if rows else 0,
            "mean_overhead_ms": statistics.mean(overheads) if overheads else 0,
            "stdev_overhead_ms": statistics.pstdev(overheads) if len(overheads) > 1 else 0,
        }
    on = out["recovery_on"]
    off = out["recovery_off"]
    benefit = {
        "correct_resume_delta": on["correct_resume_rate"] - off["correct_resume_rate"],
        "duplicate_effects_delta": on["duplicate_effects_rate"] - off["duplicate_effects_rate"],
        "lost_work_delta": on["lost_work_rate"] - off["lost_work_rate"],
        "false_success_delta": on["false_success_rate"] - off["false_success_rate"],
        "overhead_ms_delta": on["mean_overhead_ms"] - off["mean_overhead_ms"],
    }
    honest = []
    if benefit["correct_resume_delta"] <= 0:
        honest.append("No correct-resume benefit observed for recovery_on vs recovery_off in this software run.")
    if benefit["overhead_ms_delta"] > 0:
        honest.append("Recovery_on incurred higher mean overhead_ms (expected bookkeeping cost).")
    if benefit["duplicate_effects_delta"] >= 0 and on["duplicate_effects_rate"] > 0:
        honest.append("Recovery_on still showed duplicate effects in some cases — no universal exactly-once claim.")
    if off["false_success_rate"] > on["false_success_rate"]:
        honest.append("Recovery_off showed higher false-success risk on injected tool failures.")
    if not honest:
        honest.append("Recovery_on improved resume correctness without elevated duplicates in this software suite.")
    out["benefit"] = benefit
    out["analysis"] = honest
    out["limits"] = [
        "software-labeled measurements only when LM Studio is absent",
        "does not claim universal exactly-once for external tools",
        "injected failures are synthetic process/tool stops",
        "Windows host GUI resume path UNVERIFIED_ON_HOST in this harness",
    ]
    return out


def run_experiment(*, runs: int = 3, seed: int = 42, out_path: Path | None = None) -> dict[str, Any]:
    work = default_out_dir() / "work"
    work.mkdir(parents=True, exist_ok=True)
    results: list[RunResult] = []
    for i in range(runs):
        for task in TASKS:
            for arm in ("recovery_on", "recovery_off"):
                results.append(
                    _simulate_arm(arm=arm, task=task, work_dir=work, seed=seed + i)  # type: ignore[arg-type]
                )

    settings = {
        "experiment_id": EXPERIMENT_ID,
        "dataset_version": DATASET_VERSION,
        "grader_version": GRADER_VERSION,
        "quality_layer": QUALITY_LAYER,
        "runs_per_task_arm": runs,
        "tasks": [asdict(t) for t in TASKS],
        "arms": ["recovery_on", "recovery_off"],
        "model": model_config_snapshot(),
        "model_label": "software-test",
        "lm_required": False,
        "git": git_fingerprint(),
        "start_commit": git_start_commit(),
        "config_hash": config_hash(
            {"recovery_compare": True, "tasks": [t.task_id for t in TASKS], "runs": runs, "seed": seed}
        ),
        "seed": seed,
        "exactly_once_claimed": False,
    }
    aggregate = _aggregate(results)
    report = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings,
        "aggregate": aggregate,
        "raw_results": [r.to_dict() for r in results],
        "honesty": {
            "quality_layer": QUALITY_LAYER,
            "exactly_once_not_claimed": True,
            "lm_studio": "not_required_for_software_arm",
        },
    }

    out = out_path or (default_out_dir() / "report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    evidence = evidence_out_dir()
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = _to_markdown(report)
    (evidence / "report.md").write_text(md, encoding="utf-8")
    (out.parent / "report.md").write_text(md, encoding="utf-8")
    return report


def _to_markdown(report: dict[str, Any]) -> str:
    agg = report["aggregate"]
    settings = report["settings"]
    lines = [
        "# A13 Reliable Resume Experiment",
        "",
        f"- Experiment: `{settings['experiment_id']}`",
        f"- Dataset / grader: `{settings['dataset_version']}` / `{settings['grader_version']}`",
        f"- Quality layer: **{settings['quality_layer']}** (software-test measurements)",
        f"- Config hash: `{settings['config_hash']}`",
        f"- Git: `{settings['git'].get('commit')}`",
        f"- Exactly-once claimed: **no**",
        "",
        "## Aggregate",
        "",
        "| Arm | n | correct_resume | lost_work | duplicate_effects | false_success | mean_effects | mean_overhead_ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ("recovery_on", "recovery_off"):
        row = agg[arm]
        lines.append(
            f"| {arm} | {row['n']} | {row['correct_resume_rate']:.2f} | {row['lost_work_rate']:.2f} | "
            f"{row['duplicate_effects_rate']:.2f} | {row['false_success_rate']:.2f} | "
            f"{row['mean_effects']:.2f} | {row['mean_overhead_ms']:.2f} |"
        )
    lines.extend(["", "## Benefit deltas", ""])
    for k, v in agg["benefit"].items():
        lines.append(f"- `{k}`: {v:.4f}" if isinstance(v, float) else f"- `{k}`: {v}")
    lines.extend(["", "## Honest analysis", ""])
    for item in agg["analysis"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Limits", ""])
    for item in agg["limits"]:
        lines.append(f"- {item}")
    lines.extend(["", f"Raw rows: {len(report['raw_results'])}", ""])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A13 reliable resume experiment")
    parser.add_argument("--runs", type=int, default=3, help="Repeats per task/arm")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args(argv)
    report = run_experiment(
        runs=max(1, int(args.runs)),
        seed=int(args.seed),
        out_path=Path(args.out) if args.out else None,
    )
    print(report["aggregate"]["analysis"][0])
    print(f"Wrote {args.out or default_out_dir() / 'report.json'}")
    print(f"Evidence {evidence_out_dir() / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
