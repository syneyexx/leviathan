#!/usr/bin/env python3
"""Offline verification harness for LEVIATHAN Trading Center Master Program v4.

Reads Data/backend/tests/trading_gates.json (declarative gate POLICY/manifest —
not runtime outcome authority), runs configured checks where possible, prints a
gate table, and writes a GENERATED machine report beside the gate manifest.

Human trading architecture/state is consolidated into
Data/docs/Leviathan_system_backend.md. Live LLM/feed/broker paths must remain
NOT_TESTED_IN_CI unless actually measured.

Modes:
  default / --allow-incomplete  — local diagnostics; incomplete is honest, not PASS
  --strict                      — institutional release mode; deferred pytest,
                                  documentary/file_exists-only, and FEATURE_GATED
                                  cannot produce strict_all_required_pass
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
    # Python pathlib.glob does not expand shell brace patterns — list extensions explicitly.
    "Data/frontend/src/pages/trading/**/*.ts",
    "Data/frontend/src/pages/trading/**/*.tsx",
)


def _load_gates() -> dict[str, Any]:
    with GATES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _run(cmd: list[str], *, timeout: int = 600) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, f"TIMEOUT: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _git_source_truth() -> dict[str, Any]:
    """Record current source commit/tree/dirty for report provenance."""
    out: dict[str, Any] = {
        "source_commit": None,
        "source_tree": None,
        "dirty": None,
        "branch": None,
        "error": None,
    }
    try:
        code, commit = _run(["git", "rev-parse", "HEAD"], timeout=30)
        if code == 0:
            out["source_commit"] = commit.strip()
        code, tree = _run(["git", "rev-parse", "HEAD^{tree}"], timeout=30)
        if code == 0:
            out["source_tree"] = tree.strip()
        code, dirty = _run(["git", "status", "--porcelain"], timeout=30)
        if code == 0:
            out["dirty"] = bool(dirty.strip())
        code, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=30)
        if code == 0:
            out["branch"] = branch.strip()
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def _anti_shortcut_scan() -> dict[str, Any]:
    findings: list[str] = []
    todo_rx = re.compile(r"(?<![\"'])\b(TODO|FIXME)\b(?![\"'])")
    skip_rx = re.compile(
        r"@(?:pytest\.mark\.(?:skip|xfail)|unittest\.(?:skip|expectedFailure))"
        r"(?![^\n]{0,120}(?:gate|G\d{2}|D\d{1,2}|Phase|T\d))"
    )
    ni_rx = re.compile(r"raise\s+NotImplementedError\b")
    allow_ni_context = re.compile(
        r"UNSUPPORTED|NOT_IMPLEMENTED|LIVE_TRADING_BLOCKED|LiveBroker"
    )
    pass_only_fn = re.compile(
        r"(?m)^(?P<indent>[ \t]*)def\s+\w+\([^)]*\).*:\n(?P=indent)[ \t]+pass\s*(?:#.*)?$"
    )
    skip_paths = {
        "scripts/verify_trading_100.py",
        "Data/backend/tests/test_market_sim_characterization.py",
    }

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
            for rx, label in (
                (todo_rx, "TODO/FIXME"),
                (skip_rx, "skip/xfail without gate justification"),
                (ni_rx, "raise NotImplementedError"),
                (pass_only_fn, "pass-only function body"),
            ):
                for match in rx.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    window = text[
                        max(0, match.start() - 120) : min(len(text), match.end() + 120)
                    ].replace("\n", " ")
                    if label == "raise NotImplementedError" and allow_ni_context.search(
                        window
                    ):
                        continue
                    snippet = text[match.start() : match.start() + 80].replace("\n", " ")
                    findings.append(f"{rel}:{line}: {label}: {snippet[:60]}")
    return {
        "ok": not findings,
        "finding_count": len(findings),
        "findings": findings[:50],
        "truncated": len(findings) > 50,
    }


def _evaluate_gate(
    gate_id: str,
    spec: dict[str, Any],
    *,
    run_tests: bool,
    strict: bool,
) -> dict[str, Any]:
    status = str(spec.get("status", "NOT_STARTED")).upper()
    evidence = list(spec.get("evidence") or [])
    checks = list(spec.get("checks") or [])
    notes = spec.get("notes", "")
    operating_envelope = spec.get("operating_envelope") or {}
    if status == "NOT_TESTED_IN_CI":
        return {
            "id": gate_id,
            "status": status,
            "evidence": evidence,
            "notes": notes or "External live dependency — never PASS offline",
            "strict_pass": False,
            "operating_envelope": operating_envelope,
        }
    if status in {"NOT_STARTED", "NOT_TESTED", "IN_PROGRESS", "FAIL", "FEATURE_GATED"}:
        node_ids = spec.get("test_node_ids") or []
        if run_tests and node_ids and status in {"IN_PROGRESS", "PASS", "FAIL"}:
            code, out = _run(
                [sys.executable, "-m", "pytest", *node_ids, "-q", "--tb=line"],
                timeout=int(spec.get("timeout_sec", 300)),
            )
            evidence.append(f"pytest exit={code}")
            if code != 0:
                return {
                    "id": gate_id,
                    "status": "FAIL",
                    "evidence": evidence,
                    "notes": out[-2000:] if out else notes,
                    "strict_pass": False,
                    "operating_envelope": operating_envelope,
                }
        return {
            "id": gate_id,
            "status": status,
            "evidence": evidence,
            "notes": notes,
            "strict_pass": False,
            "operating_envelope": operating_envelope,
        }
    if status == "PASS":
        if not evidence and not checks and not spec.get("test_node_ids"):
            return {
                "id": gate_id,
                "status": "FAIL",
                "evidence": [],
                "notes": "PASS claimed without evidence",
                "strict_pass": False,
                "operating_envelope": operating_envelope,
            }
        executable = 0
        documentary = 0
        deferred_pytest = False

        # Declared test_node_ids are first-class executable evidence (Wave 22).
        node_ids = [str(x) for x in (spec.get("test_node_ids") or []) if str(x).strip()]
        # Frontend vitest paths are not pytest — treat as documentary unless a
        # companion pytest/meta check is declared in checks.
        pytest_nodes = [n for n in node_ids if n.endswith(".py") or "::" in n]
        if pytest_nodes:
            executable += 1
            if run_tests:
                code, out = _run(
                    [sys.executable, "-m", "pytest", *pytest_nodes, "-q", "--tb=line"],
                    timeout=int(spec.get("timeout_sec", 300)),
                )
                evidence.append(f"pytest test_node_ids exit={code}")
                if code != 0:
                    return {
                        "id": gate_id,
                        "status": "FAIL",
                        "evidence": evidence,
                        "notes": out[-2000:] if out else notes,
                        "strict_pass": False,
                        "operating_envelope": operating_envelope,
                    }
            else:
                deferred_pytest = True
                evidence.append("pytest:deferred(--run-tests not set)")

        for check in checks:
            # Documentary string checks are notes only — never sufficient alone for PASS.
            if isinstance(check, str):
                documentary += 1
                evidence.append(f"documentary:{check}")
                continue
            if not isinstance(check, dict):
                continue
            kind = check.get("kind")
            if kind == "file_exists":
                # File presence is a weak check; record it but do not treat as product readiness.
                path = check["path"]
                exists = (ROOT / path).is_file()
                evidence.append(f"file_exists:{path}:{'ok' if exists else 'missing'}")
                if not exists:
                    return {
                        "id": gate_id,
                        "status": "FAIL",
                        "evidence": evidence,
                        "notes": f"missing file {path}",
                        "strict_pass": False,
                        "operating_envelope": operating_envelope,
                    }
                documentary += 1
                continue
            if kind == "pytest":
                executable += 1
                if run_tests:
                    node_ids = check.get("node_ids") or []
                    code, out = _run(
                        [sys.executable, "-m", "pytest", *node_ids, "-q", "--tb=line"],
                        timeout=int(check.get("timeout_sec", 300)),
                    )
                    evidence.append(f"pytest {node_ids} exit={code}")
                    if code != 0:
                        return {
                            "id": gate_id,
                            "status": "FAIL",
                            "evidence": evidence,
                            "notes": out[-2000:],
                            "strict_pass": False,
                            "operating_envelope": operating_envelope,
                        }
                else:
                    deferred_pytest = True
                    evidence.append("pytest:deferred(--run-tests not set)")
                continue
            if kind:
                executable += 1
                evidence.append(f"check_kind:{kind}")

        # Documentary / file_exists alone cannot PASS in any mode when checks exist.
        if checks and executable == 0 and documentary > 0:
            return {
                "id": gate_id,
                "status": "UNMEASURED",
                "evidence": evidence,
                "notes": "documentary/file_exists checks alone are not product readiness",
                "strict_pass": False,
                "operating_envelope": operating_envelope,
            }

        # Strict: deferred pytest can never produce PASS / strict_pass.
        if strict and deferred_pytest:
            return {
                "id": gate_id,
                "status": "UNMEASURED",
                "evidence": evidence,
                "notes": "strict mode: pytest:deferred cannot produce PASS",
                "strict_pass": False,
                "operating_envelope": operating_envelope,
            }

        return {
            "id": gate_id,
            "status": "PASS",
            "evidence": evidence,
            "notes": notes,
            "strict_pass": bool(executable > 0 and not deferred_pytest),
            "operating_envelope": operating_envelope,
        }
    return {
        "id": gate_id,
        "status": status,
        "evidence": evidence,
        "notes": notes or f"unknown status {status}",
        "strict_pass": False,
        "operating_envelope": operating_envelope,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Trading Center gates")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--anti-shortcut", action="store_true", default=True)
    parser.add_argument("--no-anti-shortcut", action="store_true")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help=(
            "Exit 0 when no gate is FAIL and anti-shortcut is clean, even if required "
            "gates remain NOT_STARTED/IN_PROGRESS/FEATURE_GATED/UNMEASURED/NOT_TESTED. "
            "Never upgrades those statuses to PASS. Forbidden for release evidence."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Institutional release mode: required gates must execute their tests; "
            "pytest:deferred cannot PASS; documentary/file_exists alone cannot PASS; "
            "FEATURE_GATED cannot count as all_required_pass; report source commit/tree."
        ),
    )
    parser.add_argument(
        "--expect-commit",
        default=None,
        help="If set, report is stale/non-authoritative when HEAD differs from this SHA.",
    )
    args = parser.parse_args(argv)
    if args.strict and args.allow_incomplete:
        print(
            "ERROR: --strict and --allow-incomplete are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    if not GATES_PATH.is_file():
        print(f"MISSING gate manifest: {GATES_PATH}", file=sys.stderr)
        return 2

    source = _git_source_truth()
    stale_commit = bool(
        args.expect_commit
        and source.get("source_commit")
        and source["source_commit"] != args.expect_commit
    )

    manifest = _load_gates()
    gates: dict[str, Any] = dict(manifest.get("gates") or {})
    results = [
        _evaluate_gate(gid, gates[gid], run_tests=args.run_tests, strict=args.strict)
        for gid in sorted(gates)
    ]
    anti = None if args.no_anti_shortcut else _anti_shortcut_scan()

    print("LEVIATHAN Trading Center — gate verification")
    print(f"manifest: {GATES_PATH.relative_to(ROOT)}")
    print(f"canonical docs: {SYSTEM_DOC.relative_to(ROOT)}")
    print(
        f"source: commit={source.get('source_commit')} tree={source.get('source_tree')} "
        f"dirty={source.get('dirty')} strict={args.strict}"
    )
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

    required = [
        r
        for r in results
        if gates[r["id"]].get("required", True) and r["status"] not in {"NOT_TESTED_IN_CI"}
    ]
    # FEATURE_GATED is an honest non-FAIL terminal for sandbox-gated features
    # (e.g. G16), but it is NOT a PASS claim — all_required_pass requires
    # literal PASS on every required gate.
    exit_acceptable = {"PASS", "FEATURE_GATED"}
    incomplete_statuses = {
        "NOT_STARTED",
        "IN_PROGRESS",
        "UNMEASURED",
        "NOT_TESTED",
        "FEATURE_GATED",
    }
    hard_fail = any(r["status"] == "FAIL" for r in required) or (
        anti is not None and not anti.get("ok")
    )
    all_pass = all(r["status"] == "PASS" for r in required) and (
        anti is None or anti.get("ok")
    )
    # Strict: every required gate must have executed (strict_pass) and be PASS.
    strict_all_required_pass = (
        args.strict
        and all(r.get("strict_pass") and r["status"] == "PASS" for r in required)
        and (anti is None or anti.get("ok"))
        and not stale_commit
        and not source.get("dirty")
    )
    no_hard_failures = not hard_fail
    exit_ok = all(r["status"] in exit_acceptable for r in required) and (
        anti is None or anti.get("ok")
    )

    if hard_fail:
        exit_code = 1
        reason = "FAIL status or anti-shortcut findings"
    elif stale_commit:
        exit_code = 1
        reason = "stale source_commit — report not release evidence"
    elif args.strict:
        if strict_all_required_pass and required:
            exit_code = 0
            reason = "strict: every required gate executed and PASS"
        elif source.get("dirty"):
            exit_code = 1
            reason = "strict: dirty working tree cannot be release evidence"
        else:
            exit_code = 1
            reason = "strict: required gates incomplete / deferred / FEATURE_GATED / not executed"
    elif all_pass and required:
        exit_code = 0
        reason = "every required offline gate is PASS"
    elif exit_ok and required and not args.allow_incomplete:
        # FEATURE_GATED present: honest non-green, not a PASS claim.
        exit_code = 1
        reason = "required gates incomplete (FEATURE_GATED is not PASS)"
    elif args.allow_incomplete:
        # Incomplete is honest — not PASS. Only refuse on FAIL/crash.
        open_gates = [
            r["id"]
            for r in required
            if r["status"] in incomplete_statuses or r["status"] not in exit_acceptable
        ]
        exit_code = 0
        reason = f"incomplete gates reported honestly ({len(open_gates)} open); no FAIL"
        print(
            f"allow-incomplete: open={open_gates[:12]}{'…' if len(open_gates) > 12 else ''}"
        )
    else:
        exit_code = 1
        reason = "required gates incomplete (not all PASS)"

    operating_envelope = {
        "live_trading": "BLOCKED",
        "canonical_databases": ["CONTROL", "KNOWLEDGE", "MARKET"],
        "excluded_trees": ["Data/HADES/", "editor/"],
        "strict": bool(args.strict),
        "allow_incomplete": bool(args.allow_incomplete),
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_commit": source.get("source_commit"),
        "source_tree": source.get("source_tree"),
        "dirty": source.get("dirty"),
        "branch": source.get("branch"),
        "strict": bool(args.strict),
        "phase": manifest.get("phase"),
        "program": manifest.get("program") or "Master Program v4.1",
        "all_required_pass": all_pass and not stale_commit,
        "strict_all_required_pass": bool(strict_all_required_pass),
        "no_hard_failures": no_hard_failures,
        "stale_source_commit": stale_commit,
        "allow_incomplete": bool(args.allow_incomplete),
        "operating_envelope": operating_envelope,
        "counts": counts,
        "gates": results,
        "anti_shortcut": anti,
        "explicitly_not_claimed": manifest.get("explicitly_not_claimed") or [],
        "canonical_system_doc": str(SYSTEM_DOC.relative_to(ROOT)),
        "truth": {
            "incomplete_is_not_pass": True,
            "feature_gated_is_not_pass_claim": True,
            "baseline_green_does_not_mark_trading_pass": True,
            "deferred_pytest_is_not_strict_pass": True,
            "file_exists_alone_is_not_pass": True,
            "report_is_generated_not_curated": True,
            "gates_manifest_is_policy_not_outcome": True,
            "stale_commit_is_not_release_evidence": True,
        },
        "exit_reason": reason,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {REPORT_JSON.relative_to(ROOT)}")
    print(f"exit={exit_code} ({reason})")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
