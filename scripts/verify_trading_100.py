#!/usr/bin/env python3
"""Offline verification harness for LEVIATHAN Trading Center Master Program v4.

Reads Data/backend/tests/trading_gates.json, runs configured checks where possible,
prints a gate table, writes its machine report beside the gate manifest, and exits
non-zero unless every required offline gate is PASS.

Human trading architecture/state is consolidated into
Data/docs/Leviathan_system_backend.md. Live LLM/feed/broker paths must remain
NOT_TESTED_IN_CI unless actually measured.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GATES_PATH = ROOT / "Data" / "backend" / "tests" / "trading_gates.json"
SYSTEM_DOC = ROOT / "Data" / "docs" / "Leviathan_system_backend.md"
REPORT_JSON = ROOT / "Data" / "backend" / "tests" / "trading_completion_report.json"
TRADING_OWNED_GLOBS = (
    "Data/modules/market_sim/**/*.py",
    "Data/backend/routes/market_sim.py",
    "Data/modules/trading/**/*.py",
    "scripts/market_sim_worker.py",
    "scripts/verify_trading_100.py",
    "Data/frontend/src/pages/trading/**/*.{ts,tsx}",
)


def _load_gates() -> dict[str, Any]:
    with GATES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _run(cmd: list[str], *, timeout: int = 600) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return 124, f"TIMEOUT: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _anti_shortcut_scan() -> dict[str, Any]:
    findings: list[str] = []
    todo_rx = re.compile(r"(?<![\"'])\b(TODO|FIXME)\b(?![\"'])")
    skip_rx = re.compile(r"@(?:pytest\.mark\.(?:skip|xfail)|unittest\.(?:skip|expectedFailure))(?![^\n]{0,120}(?:gate|G\d{2}|D\d{1,2}|Phase|T\d))")
    ni_rx = re.compile(r"raise\s+NotImplementedError\b")
    allow_ni_context = re.compile(r"UNSUPPORTED|NOT_IMPLEMENTED|LIVE_TRADING_BLOCKED|LiveBroker")
    pass_only_fn = re.compile(r"(?m)^(?P<indent>[ \t]*)def\s+\w+\([^)]*\).*:\n(?P=indent)[ \t]+pass\s*(?:#.*)?$")
    skip_paths = {"scripts/verify_trading_100.py", "Data/backend/tests/test_market_sim_characterization.py"}

    for glob in TRADING_OWNED_GLOBS:
        for path in ROOT.glob(glob):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if rel in skip_paths:
                continue
            for rx, label in ((todo_rx, "TODO/FIXME"), (skip_rx, "skip/xfail without gate justification"),
                              (ni_rx, "raise NotImplementedError"), (pass_only_fn, "pass-only function body")):
                for match in rx.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    window = text[max(0, match.start()-120):min(len(text), match.end()+120)].replace("\n", " ")
                    if label == "raise NotImplementedError" and allow_ni_context.search(window):
                        continue
                    snippet = text[match.start():match.start()+80].replace("\n", " ")
                    findings.append(f"{rel}:{line}: {label}: {snippet[:60]}")
    return {"ok": not findings, "finding_count": len(findings), "findings": findings[:50],
            "truncated": len(findings) > 50}


def _evaluate_gate(gate_id: str, spec: dict[str, Any], *, run_tests: bool) -> dict[str, Any]:
    status = str(spec.get("status", "NOT_STARTED")).upper()
    evidence = list(spec.get("evidence") or [])
    checks = list(spec.get("checks") or [])
    notes = spec.get("notes", "")
    if status == "NOT_TESTED_IN_CI":
        return {"id": gate_id, "status": status, "evidence": evidence,
                "notes": notes or "External live dependency — never PASS offline"}
    if status == "DEFERRED":
        return {
            "id": gate_id,
            "status": status,
            "evidence": evidence,
            "notes": notes or "Deferred beyond current Master Program delivery stack",
        }
    if status in {"NOT_STARTED", "NOT_TESTED", "IN_PROGRESS", "FAIL"}:
        node_ids = spec.get("test_node_ids") or []
        if run_tests and node_ids and status in {"IN_PROGRESS", "PASS", "FAIL"}:
            code, out = _run([sys.executable, "-m", "pytest", *node_ids, "-q", "--tb=line"],
                             timeout=int(spec.get("timeout_sec", 300)))
            evidence.append(f"pytest exit={code}")
            if code != 0:
                return {"id": gate_id, "status": "FAIL", "evidence": evidence,
                        "notes": out[-2000:] if out else notes}
        return {"id": gate_id, "status": status, "evidence": evidence, "notes": notes}
    if status == "PASS":
        if not evidence and not checks:
            return {"id": gate_id, "status": "FAIL", "evidence": [], "notes": "PASS claimed without evidence"}
        for check in checks:
            kind = check.get("kind")
            if kind == "file_exists" and not (ROOT / check["path"]).is_file():
                return {"id": gate_id, "status": "FAIL", "evidence": evidence,
                        "notes": f"missing file {check['path']}"}
            if kind == "pytest" and run_tests:
                node_ids = check.get("node_ids") or []
                code, out = _run([sys.executable, "-m", "pytest", *node_ids, "-q", "--tb=line"],
                                 timeout=int(check.get("timeout_sec", 300)))
                evidence.append(f"pytest {node_ids} exit={code}")
                if code != 0:
                    return {"id": gate_id, "status": "FAIL", "evidence": evidence, "notes": out[-2000:]}
        return {"id": gate_id, "status": "PASS", "evidence": evidence, "notes": notes}
    return {"id": gate_id, "status": status, "evidence": evidence,
            "notes": notes or f"unknown status {status}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Trading Center gates")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--anti-shortcut", action="store_true", default=True)
    parser.add_argument("--no-anti-shortcut", action="store_true")
    args = parser.parse_args(argv)
    if not GATES_PATH.is_file():
        print(f"MISSING gate manifest: {GATES_PATH}", file=sys.stderr)
        return 2

    manifest = _load_gates()
    gates: dict[str, Any] = dict(manifest.get("gates") or {})
    results = [_evaluate_gate(gid, gates[gid], run_tests=args.run_tests) for gid in sorted(gates)]
    anti = None if args.no_anti_shortcut else _anti_shortcut_scan()

    print("LEVIATHAN Trading Center — gate verification")
    print(f"manifest: {GATES_PATH.relative_to(ROOT)}")
    print(f"canonical docs: {SYSTEM_DOC.relative_to(ROOT)}")
    print("-" * 88)
    print(f"{'GATE':<6} {'STATUS':<18} EVIDENCE")
    print("-" * 88)
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        ev = "; ".join(str(x) for x in (row.get("evidence") or [])[:2]) or "-"
        print(f"{row['id']:<6} {row['status']:<18} {ev[:60]}")
    print("-" * 88)
    print("counts:", counts)
    if anti is not None:
        print(f"anti-shortcut: ok={anti['ok']} findings={anti['finding_count']}")
        for finding in anti.get("findings") or []:
            print(f"  ! {finding}")

    required_pass = [
        r
        for r in results
        if r["status"] not in {"NOT_TESTED_IN_CI", "DEFERRED"}
        and gates[r["id"]].get("required", True)
    ]
    all_pass = all(r["status"] == "PASS" for r in required_pass) and (anti is None or anti.get("ok"))
    exit_code = 0 if all_pass and required_pass else 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phase": manifest.get("phase"),
        "program": "Master Program v4",
        "all_required_pass": all_pass,
        "counts": counts,
        "deferred_gates": [r["id"] for r in results if r["status"] == "DEFERRED"],
        "gates": results,
        "anti_shortcut": anti,
        "explicitly_not_claimed": manifest.get("explicitly_not_claimed") or [],
        "canonical_system_doc": str(SYSTEM_DOC.relative_to(ROOT)),
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {REPORT_JSON.relative_to(ROOT)}")
    print(f"exit={exit_code} (0 only when every required offline gate is PASS)")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
