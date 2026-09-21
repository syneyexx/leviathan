"""Unified functional campaign runner — Wave 0 baseline + subsequent suites.

  python -m evals.functional.runner
  python -m evals.functional.runner --out /tmp/hades_functional_baseline.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from evals.functional.schema import BENCHMARK_SCHEMA_VERSION
from evals.functional.scoreboard import build_scoreboard
from evals.harness import git_start_commit, model_config_snapshot


def run_baseline(*, out_path: str | None = None, include_coding_agent: bool = True) -> dict[str, Any]:
    started = time.time()
    sha = git_start_commit()

    from evals.functional.intent_eval import run_intent_semantic_shadow, run_intent_suite
    from evals.functional.retrieval_eval import run_retrieval_suite
    from evals.functional.coding_portable import run_coding_portable_suite, write_manifest
    from evals.functional.verification_ablation import run_verification_ablation
    from evals.functional.specialist_audit import classify_specialists
    from evals.functional.tool_use_eval import run_tool_use_suite
    from evals.functional.windows_threat_matrix import build_threat_matrix
    from evals.functional.chat_pipeline import characterize_chat_pipeline

    suites: dict[str, Any] = {}
    suites["intent"] = run_intent_suite()
    suites["intent_shadow"] = run_intent_semantic_shadow()
    suites["retrieval"] = run_retrieval_suite()
    suites["coding"] = run_coding_portable_suite(use_agent=include_coding_agent)
    suites["verification_ablation"] = run_verification_ablation()
    suites["specialists"] = classify_specialists()
    suites["tool_use"] = run_tool_use_suite()
    suites["windows_sandbox"] = build_threat_matrix()
    suites["chat_pipeline"] = characterize_chat_pipeline()

    all_records: list[dict[str, Any]] = []
    for key in ("intent", "retrieval", "coding", "verification_ablation", "tool_use"):
        all_records.extend(suites[key].get("records") or [])

    scoreboard = build_scoreboard(
        all_records,
        git_sha=sha,
        benchmark_version=BENCHMARK_SCHEMA_VERSION,
        generated_at=time.time(),
        model_label="HADES + deterministic/fixture (Layer B primary)",
    ).to_dict()

    report = {
        "campaign": "frontier_functional_hardening",
        "wave": 0,
        "benchmark_version": BENCHMARK_SCHEMA_VERSION,
        "git_sha": sha,
        "generated_at": time.time(),
        "duration_seconds": round(time.time() - started, 3),
        "model_config_snapshot": model_config_snapshot(),
        "scoreboard": scoreboard,
        "suites": {
            k: {kk: vv for kk, vv in v.items() if kk != "records"} | {"record_count": len(v.get("records") or [])}
            if isinstance(v, dict) and "records" in v
            else v
            for k, v in suites.items()
        },
        "records": all_records,
        "layer_c": {
            "status": "BLOCKED_MODEL_UNAVAILABLE",
            "note": "No live LM Studio model assumed in baseline; do not substitute fixtures.",
        },
        "layer_d": {
            "status": "NOT_RUN",
            "note": "Competitor runs not imported. Portable coding manifest written for external use.",
        },
        "exit_gate": {
            "baseline_numbers_known": True,
            "intent_suite": suites["intent"]["metrics"],
            "coding_metrics": suites["coding"]["metrics"],
            "retrieval_best": suites["retrieval"].get("recommended_metrics"),
            "verification_gate": suites["verification_ablation"].get("gate"),
            "tool_use_metrics": suites["tool_use"]["metrics"],
        },
    }

    if out_path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Compact: drop full records from file if huge — keep metrics; write records JSONL beside
        compact = dict(report)
        records = compact.pop("records", [])
        path.write_text(json.dumps(compact, indent=2, default=str), encoding="utf-8")
        jsonl = path.with_suffix(".jsonl")
        with jsonl.open("w", encoding="utf-8") as fh:
            for row in records:
                fh.write(json.dumps(row, default=str) + "\n")
        manifest_path = path.parent / "coding_portable_manifest.json"
        write_manifest(manifest_path)
        report["written"] = {"summary": str(path), "records_jsonl": str(jsonl), "coding_manifest": str(manifest_path)}

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HADES functional campaign runner")
    parser.add_argument("--out", default=None, help="Write summary JSON (+ JSONL records)")
    parser.add_argument("--skip-coding-agent", action="store_true")
    args = parser.parse_args(argv)
    report = run_baseline(out_path=args.out, include_coding_agent=not args.skip_coding_agent)
    print(json.dumps({
        "git_sha": report["git_sha"],
        "duration_seconds": report["duration_seconds"],
        "exit_gate": report["exit_gate"],
        "layer_c": report["layer_c"],
        "written": report.get("written"),
    }, indent=2, default=str))
    ver = report["suites"]["verification_ablation"]
    if ver.get("status") == "FAIL":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
