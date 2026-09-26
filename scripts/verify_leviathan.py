#!/usr/bin/env python3
"""Top-level LEVIATHAN verification runner.

Runs frontier + trading offline verifiers and reports incomplete gates honestly.
Does NOT coerce NOT_STARTED / IN_PROGRESS / FEATURE_GATED / UNMEASURED into PASS.

Exit codes:
  0 — structural/smoke checks OK (with --allow-incomplete when program gates open)
  1 — verifier reported FAIL, structural failure, or incomplete without --allow-incomplete
  2 — missing manifests / runner crash

CI should invoke with --allow-incomplete so open program gates do not false-green
or false-block the baseline CI. Full program completion still requires exit 0
without --allow-incomplete.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRONTIER = ROOT / "scripts" / "verify_frontier_reasoning.py"
TRADING = ROOT / "scripts" / "verify_trading_100.py"
REPORT = ROOT / "Data" / "backend" / "tests" / "leviathan_verification_report.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help=(
            "Exit 0 when verifiers complete without FAIL/crash even if required "
            "program gates remain NOT_STARTED/IN_PROGRESS/FEATURE_GATED/UNMEASURED. "
            "Never upgrades those statuses to PASS."
        ),
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help=f"Write aggregate report to {REPORT.relative_to(ROOT)}",
    )
    args = parser.parse_args(argv)

    if not FRONTIER.is_file() or not TRADING.is_file():
        print("FAIL: missing verifier scripts", file=sys.stderr)
        return 2

    results: dict[str, Any] = {
        "program": "leviathan_verification",
        "generated_at": _utcnow(),
        "allow_incomplete": bool(args.allow_incomplete),
        "truth": {
            "incomplete_is_not_pass": True,
            "baseline_green_does_not_mark_frontier_pass": True,
            "not_started_is_not_pass": True,
            "unmeasured_is_not_pass": True,
            "feature_gated_is_not_pass": True,
        },
        "runs": {},
    }

    # Frontier: always require F0 structural; allow open R-gates when incomplete permitted.
    frontier_cmd = [sys.executable, str(FRONTIER), "--write-report"]
    if args.allow_incomplete:
        frontier_cmd.append("--allow-f0-skeleton-only")
    f_code, f_out = _run(frontier_cmd)
    print(f_out, end="" if f_out.endswith("\n") else "\n")
    results["runs"]["frontier"] = {"exit_code": f_code, "cmd": frontier_cmd[2:]}

    # Trading: allow incomplete via dedicated flag (does not mark gates PASS).
    trading_cmd = [sys.executable, str(TRADING)]
    if args.allow_incomplete:
        trading_cmd.append("--allow-incomplete")
    t_code, t_out = _run(trading_cmd)
    print(t_out, end="" if t_out.endswith("\n") else "\n")
    results["runs"]["trading"] = {"exit_code": t_code, "cmd": trading_cmd[2:]}

    hard_fail = f_code not in {0, 1} or t_code not in {0, 1}
    incomplete_ok = args.allow_incomplete and f_code in {0, 1} and t_code in {0, 1}
    # With allow-incomplete: frontier exits 0 (skeleton), trading exits 0 (incomplete allowed).
    # Without: both must be 0 (all required gates PASS).
    if hard_fail:
        exit_code = 2
        reason = "verifier crash or missing manifests"
    elif args.allow_incomplete:
        # Fail CI only on structural FAIL (frontier exit 1 without skeleton allow handled above)
        # or trading FAIL statuses. With --allow-incomplete trading returns 0 unless FAIL.
        exit_code = 0 if f_code == 0 and t_code == 0 else 1
        reason = (
            "incomplete gates reported honestly; structural/smoke OK"
            if exit_code == 0
            else "verifier reported FAIL under allow-incomplete"
        )
    else:
        exit_code = 0 if f_code == 0 and t_code == 0 else 1
        reason = (
            "all required offline gates PASS"
            if exit_code == 0
            else "required gates incomplete or FAIL"
        )

    results["exit_code"] = exit_code
    results["reason"] = reason
    results["incomplete_ok"] = incomplete_ok

    print("=" * 72)
    print(f"LEVIATHAN verify: exit={exit_code} — {reason}")
    print(
        "truth: incomplete≠PASS · baseline green≠frontier PASS · "
        f"allow_incomplete={bool(args.allow_incomplete)}"
    )

    if args.write_report:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {REPORT.relative_to(ROOT)}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
