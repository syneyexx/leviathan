"""Runnable evaluation harness for independent / generalization / A01 agent evals.

Records dataset version, seed, task fingerprint hash, start commit, model
config, and per-task results. Honesty/dry-run work without a live model.
Executable mode invokes the real HADES production route (see evals.agent_eval).

Host command (from repository root, with backend on PYTHONPATH or cwd=backend):

  python -m evals.harness --dataset generalization_v1 --seed 42
  python -m evals.harness --dataset independent_fixtures_v1 --mode honesty
  python -m evals.harness --dataset generalization_v1 --mode honesty --out /tmp/eval_report.json
  python -m evals.harness --dataset agent_tasks_v1 --mode executable --limit 5
  python -m evals.agent_eval --mode executable --split holdout --repeats 2

Exit code 0 when honesty fixtures are red (or dry-run metadata written).
Agent quality PASS is never implied by honesty-only runs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _repo_root() -> Path:
    return _backend_root().parent


def git_start_commit(cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd or _repo_root()),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"unavailable:{exc}"
    return "unavailable"


def model_config_snapshot() -> dict[str, Any]:
    """Record configured model endpoints without requiring a live model."""
    try:
        from database import DEFAULT_SETTINGS

        keys = (
            "lm_studio_base_url",
            "lm_studio_model",
            "chat_model",
            "coding_model",
            "reasoning_profile",
        )
        return {k: DEFAULT_SETTINGS.get(k) for k in keys if k in DEFAULT_SETTINGS or True}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "lm_studio_base_url": os.environ.get("LM_STUDIO_BASE_URL")}


def run_harness(
    *,
    dataset: str = "generalization_v1",
    seed: int = 42,
    mode: str = "honesty",
    limit: int | None = None,
    out_path: str | None = None,
    repeats: int = 1,
    compare_baseline: bool = False,
) -> dict[str, Any]:
    started = time.time()
    start_commit = git_start_commit()
    model_cfg = model_config_snapshot()

    if mode in {"executable", "agent_task", "software", "infra_smoke", "model_answer"} or dataset in {
        "agent_tasks_v1",
        "agent_tasks",
        "a01",
    }:
        from evals.agent_eval import run_agent_eval

        eval_mode = mode if mode in {"executable", "agent_task", "software", "infra_smoke", "model_answer", "all"} else "executable"
        if dataset in {"agent_tasks_v1", "agent_tasks", "a01"} and mode == "honesty":
            eval_mode = "software"
        report = run_agent_eval(
            mode=eval_mode,
            split="holdout",
            limit=limit,
            repeats=repeats,
            out_path=out_path,
            compare_baseline=compare_baseline,
            seed=seed,
        )
        report["harness"] = "evals.harness->evals.agent_eval"
        report["dataset_requested"] = dataset
        report["duration_seconds"] = round(time.time() - started, 3)
        return report

    if dataset in {"generalization_v1", "generalization"}:
        from evals.generalization_dataset import (
            GENERALIZATION_DATASET_VERSION,
            GENERALIZATION_TASKS,
            categories_covered,
            dataset_task_fingerprint,
            list_holdout_tasks,
        )
        from evals.holdout_judges import HOLDOUT_JUDGE_VERSION, run_holdout_honesty_suite

        tasks = list_holdout_tasks()
        fingerprint = dataset_task_fingerprint(tasks)
        if mode == "honesty":
            suite = run_holdout_honesty_suite(limit=limit)
        elif mode == "dry-run":
            suite = {
                "suite": "generalization_dry_run",
                "total": min(limit or len(tasks), len(tasks)),
                "task_ids": [t["id"] for t in tasks[: limit or None]],
                "note": "Metadata only; no agent invocation.",
            }
        else:
            raise ValueError(f"Unsupported mode for generalization without model: {mode}")
        report = {
            "harness": "evals.harness",
            "dataset": GENERALIZATION_DATASET_VERSION,
            "dataset_requested": dataset,
            "seed": seed,
            "task_fingerprint_sha256": fingerprint,
            "start_commit": start_commit,
            "model_config": model_cfg,
            "judge_version": HOLDOUT_JUDGE_VERSION,
            "mode": mode,
            "categories": categories_covered(),
            "task_count": len(GENERALIZATION_TASKS),
            "holdout_count": len(tasks),
            "results": suite,
            "duration_seconds": round(time.time() - started, 3),
            "claimed_agent_quality_pass": False,
            "host_command": (
                f"python -m evals.harness --dataset {GENERALIZATION_DATASET_VERSION} "
                f"--seed {seed} --mode {mode}"
            ),
        }
    elif dataset in {"independent_fixtures_v1", "independent", "E01-E08"}:
        from evals.independent_tasks import (
            EVAL_DATASET_VERSION,
            INDEPENDENT_TASKS,
            run_independent_eval_honesty_suite,
        )

        suite = run_independent_eval_honesty_suite(limit=limit)
        report = {
            "harness": "evals.harness",
            "dataset": EVAL_DATASET_VERSION,
            "dataset_requested": dataset,
            "seed": seed,
            "task_fingerprint_sha256": None,
            "start_commit": start_commit,
            "model_config": model_cfg,
            "mode": mode,
            "task_count": len(INDEPENDENT_TASKS),
            "results": suite,
            "duration_seconds": round(time.time() - started, 3),
            "claimed_agent_quality_pass": False,
            "note": (
                "E01–E08 are known regression fixtures, not independent quality proof. "
                "Use generalization_v1 / agent_tasks_v1 for holdout / production-route scoring."
            ),
            "host_command": (
                f"python -m evals.harness --dataset independent_fixtures_v1 --seed {seed} --mode honesty"
            ),
        }
    elif dataset in {"dev_partner_v1", "dev_partner", "development_partner"}:
        from evals.dev_partner_harness import run_dev_partner_suite

        run_mode = mode if mode in {"honesty", "software", "baseline_compare", "executable"} else "honesty"
        report = run_dev_partner_suite(
            mode=run_mode,
            split="holdout",
            limit=limit,
            seed=seed,
            out_path=out_path,
            compare_baseline=compare_baseline or mode == "baseline_compare",
        )
        report["harness"] = "evals.harness->evals.dev_partner_harness"
        report["dataset_requested"] = dataset
        report["start_commit"] = start_commit
        report["model_config"] = model_cfg
        report["duration_seconds"] = round(time.time() - started, 3)
        return report
    else:
        raise ValueError(f"Unknown dataset: {dataset}")

    if out_path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        report["wrote"] = str(path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HADES independent/generalization/A01 eval harness")
    parser.add_argument(
        "--dataset",
        default="generalization_v1",
        help="generalization_v1 | independent_fixtures_v1 | agent_tasks_v1 | dev_partner_v1",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--mode",
        default="honesty",
        choices=["honesty", "dry-run", "executable", "agent_task", "software", "infra_smoke", "model_answer"],
        help="honesty=fixtures must start red; executable=production-route agent eval",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--compare-baseline", action="store_true")
    parser.add_argument("--out", default="", help="Optional JSON report path")
    args = parser.parse_args(argv)

    backend = str(_backend_root())
    if backend not in sys.path:
        sys.path.insert(0, backend)

    report = run_harness(
        dataset=args.dataset,
        seed=args.seed,
        mode=args.mode,
        limit=args.limit,
        out_path=args.out or None,
        repeats=args.repeats,
        compare_baseline=args.compare_baseline,
    )
    printable = {k: v for k, v in report.items() if k != "human_report_markdown"}
    print(json.dumps(printable, indent=2, default=str))
    results = report.get("results") or {}
    if args.mode == "honesty" and results.get("all_fixtures_honest") is False:
        return 1
    layers = report.get("layers") or {}
    if args.mode in {"executable", "software"} and (layers.get("software") or {}).get("passed") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
