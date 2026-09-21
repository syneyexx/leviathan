"""Fast offline Gen2 eval release gate for verify_hades --quick.

Runs deterministic reasoning + red-team software suites and fails when
pass_rate regresses below the embedded baseline. No network / LM required.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

# Embedded baseline — update only when intentional suite changes land.
EMBEDDED_BASELINE: dict[str, Any] = {
    "version": "gen2_release_gate_v2_frontier",
    "suites": {
        "reasoning": {"min_pass_rate": 1.0, "min_total": 10},
        "red_team_v1": {"min_pass_rate": 1.0, "min_total": 3},
        "frontier_adversarial_v1": {"min_pass_rate": 1.0, "min_total": 109},
    },
    "note": "Software-only gate; not live model quality.",
}


def run_gate(*, db_path: str | None = None) -> dict[str, Any]:
    from evals.adversarial_corpus import run_adversarial_suite
    from gen2.eval_lab import run_eval_lab, run_red_team_suite
    from gen2.store import Gen2Store

    tmp: tempfile.TemporaryDirectory[str] | None = None
    if db_path:
        store = Gen2Store(db_path)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="gen2_gate_")
        store = Gen2Store(str(Path(tmp.name) / "gate.db"))

    try:
        reasoning = run_eval_lab(store, model_id="release-gate", suite="reasoning", mode="deterministic_software")
        red = run_red_team_suite()
        # Persist red-team via store for auditability of the gate run.
        from gen2.eval_lab import run_eval_lab as _run

        red_saved = _run(store, model_id="release-gate", suite="red_team_v1", mode="red_team_software")
        adversarial = run_adversarial_suite()

        results = {
            "reasoning": {
                "pass_rate": float((reasoning.get("summary") or {}).get("pass_rate") or 0.0),
                "total": int((reasoning.get("summary") or {}).get("total") or 0),
                "passed": int((reasoning.get("summary") or {}).get("passed") or 0),
                "run_id": reasoning.get("id"),
            },
            "red_team_v1": {
                "pass_rate": float((red_saved.get("summary") or {}).get("pass_rate") or red.get("pass_rate") or 0.0),
                "total": int((red_saved.get("summary") or {}).get("total") or red.get("total") or 0),
                "passed": int((red_saved.get("summary") or {}).get("passed") or red.get("passed") or 0),
                "run_id": red_saved.get("id"),
            },
            "frontier_adversarial_v1": {
                "pass_rate": float(adversarial.get("pass_rate") or 0.0),
                "total": int(adversarial.get("total") or 0),
                "passed": int(adversarial.get("passed") or 0),
                "failed": int(adversarial.get("failed") or 0),
                "not_model_quality": True,
            },
        }

        regressions: list[str] = []
        for suite_id, baseline in EMBEDDED_BASELINE["suites"].items():
            got = results.get(suite_id) or {}
            if got.get("total", 0) < int(baseline["min_total"]):
                regressions.append(f"{suite_id}:total<{baseline['min_total']}")
            if float(got.get("pass_rate") or 0.0) + 1e-9 < float(baseline["min_pass_rate"]):
                regressions.append(
                    f"{suite_id}:pass_rate={got.get('pass_rate')}<baseline={baseline['min_pass_rate']}"
                )

        ok = not regressions
        return {
            "ok": ok,
            "baseline": EMBEDDED_BASELINE,
            "results": results,
            "regressions": regressions,
            "offline": True,
            "model_invoked": False,
            "not_model_quality": True,
            "note": EMBEDDED_BASELINE["note"],
        }
    finally:
        if tmp is not None:
            tmp.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HADES Gen2 deterministic eval release gate")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args(argv)
    report = run_gate()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(f"[gen2_release_gate] {status}")
        for suite_id, row in (report.get("results") or {}).items():
            print(f"  {suite_id}: pass_rate={row.get('pass_rate')} total={row.get('total')}")
        for reg in report.get("regressions") or []:
            print(f"  regression: {reg}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
