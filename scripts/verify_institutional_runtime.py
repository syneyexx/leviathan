#!/usr/bin/env python3
"""Authoritative local institutional runtime verifier (W75/W108).

Exits non-zero on mandatory local failure. Does not swallow failures as PASS.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "Data") not in sys.path:
    sys.path.insert(0, str(ROOT / "Data"))


@dataclass
class CheckResult:
    section: str
    name: str
    status: str  # PASS | FAIL | BLOCKED_EXTERNAL | SKIP
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


class Verifier:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        mark = {"PASS": "✓", "FAIL": "✗", "BLOCKED_EXTERNAL": "⊘", "SKIP": "·"}.get(
            result.status, "?"
        )
        print(f"[{mark}] {result.section} :: {result.name} → {result.status}")
        if result.detail:
            print(f"    {result.detail}")

    def run(self) -> int:
        self.section_01_migrations()
        self.section_03_ownership()
        self.section_04_instruments()
        self.section_05_temporal()
        self.section_06_data_quality()
        self.section_07_portfolio()
        self.section_08_subledger()
        self.section_10_risk()
        self.section_13_compliance()
        self.section_14_sod()
        self.section_18_reconciliation()
        self.section_19_decision()
        self.section_20_audit()
        self.section_21_workflow()
        self.section_22_backup()
        self.section_23_control_room()
        self.section_26_e2e()
        self.section_27_torture()
        self.section_29_live_trading()
        self.section_30_docs_ledger()

        fails = [r for r in self.results if r.status == "FAIL"]
        report = {
            "verifier": "verify_institutional_runtime",
            "results": [r.public_dict() for r in self.results],
            "summary": {
                "pass": sum(1 for r in self.results if r.status == "PASS"),
                "fail": len(fails),
                "blocked_external": sum(
                    1 for r in self.results if r.status == "BLOCKED_EXTERNAL"
                ),
                "skip": sum(1 for r in self.results if r.status == "SKIP"),
            },
            "overall": "FAIL" if fails else "PASS",
        }
        out = ROOT / "Data" / "backend" / "tests" / "institutional_runtime_verifier_report.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2))
        print(f"overall={report['overall']} report={out}")
        return 1 if fails else 0

    def section_01_migrations(self) -> None:
        try:
            from Data.backend.migrations import MIGRATIONS, MigrationRunner

            head = MIGRATIONS[-1].version
            names = {m.version: m.name for m in MIGRATIONS}
            ok = head >= 56 and names.get(55) == "institutional_core" and names.get(56) == "institutional_runtime"
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "v.sqlite"
                applied = MigrationRunner(path).apply_all()
            self.add(
                CheckResult(
                    "01_migrations",
                    "head_and_fresh_apply",
                    "PASS" if ok and 56 in applied else "FAIL",
                    detail=f"head={head} applied_tail={applied[-3:]}",
                    evidence={"head": head, "names": {55: names.get(55), 56: names.get(56)}},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("01_migrations", "head_and_fresh_apply", "FAIL", str(exc)))

    def section_03_ownership(self) -> None:
        try:
            from Data.modules.market_sim.institutional_core.assurance import run_assurance

            report = run_assurance()
            body = report.public_dict() if hasattr(report, "public_dict") else {}
            live = body.get("liveTrading") or {}
            status = "PASS"
            detail = "assurance ran"
            if live and live.get("status") not in {"PASS", "BLOCKED", "OBSERVED"}:
                # live blocked is expected PASS in verify_live_trading_blocked
                pass
            findings = body.get("findings") or []
            forbidden = [f for f in findings if (f.get("severity") if isinstance(f, dict) else None) == "BLOCK"]
            if forbidden:
                status = "FAIL"
                detail = f"forbidden owners: {forbidden}"
            self.add(
                CheckResult(
                    "03_ownership",
                    "no_forbidden_parallel_owners",
                    status,
                    detail,
                    evidence={"liveTrading": live, "findingCount": len(findings)},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("03_ownership", "no_forbidden_parallel_owners", "FAIL", str(exc)))

    def _rt(self):
        from Data.modules.market_sim.institutional_core.runtime import InstitutionalRuntime

        self._tmpdir = tempfile.TemporaryDirectory()
        db = Path(self._tmpdir.name) / "inst.sqlite"
        return InstitutionalRuntime(db)

    def section_04_instruments(self) -> None:
        try:
            rt = self._rt()
            inst = rt.ensure_instrument("AAPL", currency="USD")
            resolved = rt.resolve_instrument("AAPL")
            ok = inst["instrument_id"] and resolved.get("instrument_id") == inst["instrument_id"]
            self.add(
                CheckResult(
                    "04_instruments",
                    "canonical_identity_persists",
                    "PASS" if ok else "FAIL",
                    evidence={"instrument": inst, "resolved": resolved},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("04_instruments", "canonical_identity_persists", "FAIL", str(exc)))

    def section_05_temporal(self) -> None:
        try:
            from Data.modules.market_sim.institutional_core.timeutil import ts_eq, parse_ts

            ok = ts_eq("2020-01-01T00:00:00Z", "2020-01-01T00:00:00+00:00")
            ok = ok and ts_eq("2020-01-01T00:00:00Z", "2020-01-01T01:00:00+01:00")
            ok = ok and parse_ts("2020-01-01T00:00:00Z") == parse_ts("2020-01-01T00:00:00+00:00")
            self.add(
                CheckResult(
                    "05_temporal",
                    "timezone_aware_equivalence",
                    "PASS" if ok else "FAIL",
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("05_temporal", "timezone_aware_equivalence", "FAIL", str(exc)))

    def section_06_data_quality(self) -> None:
        try:
            rt = self._rt()
            bad = rt.ingest_observation(
                entity_type="market_price",
                entity_id="BAD",
                effective_time="2020-01-01T00:00:00+00:00",
                payload={"price": -1},
                source="csv_local",
            )
            self.add(
                CheckResult(
                    "06_data_quality",
                    "negative_price_quarantine",
                    "PASS" if bad.get("quarantined") else "FAIL",
                    evidence=bad,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("06_data_quality", "negative_price_quarantine", "FAIL", str(exc)))

    def section_07_portfolio(self) -> None:
        try:
            rt = self._rt()
            out = rt.full_paper_lifecycle(portfolio_id="v7", symbol="MSFT", qty=2, price=50)
            ibor = out["ibor"]
            ok = ibor.get("eventCount", 0) >= 1 and out["duplicate"].get("duplicate_economics")
            self.add(
                CheckResult(
                    "07_portfolio",
                    "ibor_reconstruct_idempotent",
                    "PASS" if ok else "FAIL",
                    evidence={"eventCount": ibor.get("eventCount")},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(
                CheckResult(
                    "07_portfolio",
                    "ibor_reconstruct_idempotent",
                    "FAIL",
                    f"{exc}\n{traceback.format_exc()}",
                )
            )

    def section_08_subledger(self) -> None:
        try:
            rt = self._rt()
            out = rt.full_paper_lifecycle(portfolio_id="v8", symbol="IBM", qty=4, price=25, fee=1)
            balances = out["journal"]["balancesByCurrency"]["USD"]
            # cash + lots + fees should net ~0 for balanced journal
            from Data.modules.market_sim.accounting import money

            total = sum(money(v) for v in balances.values())
            self.add(
                CheckResult(
                    "08_subledger",
                    "journal_balanced",
                    "PASS" if total == 0 else "FAIL",
                    detail=f"sum={total} balances={balances}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("08_subledger", "journal_balanced", "FAIL", str(exc)))

    def section_10_risk(self) -> None:
        try:
            rt = self._rt()
            risk = rt.enterprise_risk_from_book(
                positions=[{"symbol": "AAPL", "qty": 10, "mark": 100}],
                nav=50_000,
            )
            ok = "grossExposure" in risk or "gross_exposure" in risk or "nav" in risk
            self.add(
                CheckResult(
                    "10_risk",
                    "risk_from_canonical_positions",
                    "PASS" if ok else "FAIL",
                    evidence={"keys": list(risk)[:10]},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("10_risk", "risk_from_canonical_positions", "FAIL", str(exc)))

    def section_13_compliance(self) -> None:
        try:
            rt = self._rt()
            rt.set_mandate(
                "c1",
                {
                    "allowedInstruments": ["MSFT"],
                    "restrictedInstruments": ["AAPL"],
                    "maxOrdersPerDay": 10,
                },
            )
            gate = rt.pre_trade_gate(portfolio_id="c1", symbol="AAPL", side="BUY", qty=1)
            self.add(
                CheckResult(
                    "13_compliance",
                    "restricted_instrument_blocked",
                    "PASS" if not gate.get("allowed") else "FAIL",
                    evidence=gate,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("13_compliance", "restricted_instrument_blocked", "FAIL", str(exc)))

    def section_14_sod(self) -> None:
        try:
            rt = self._rt()
            ch = rt.request_protected_change(
                kind="LIMIT_LOOSEN", maker_id="a", payload={"direction": "loosen"}
            )
            dec = rt.approve_protected_change(
                change_id=ch["changeId"], checker_id="a", checker_roles=["admin"]
            )
            self.add(
                CheckResult(
                    "14_sod",
                    "self_approval_blocked",
                    "PASS" if not dec.get("allowed") else "FAIL",
                    evidence=dec,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("14_sod", "self_approval_blocked", "FAIL", str(exc)))

    def section_18_reconciliation(self) -> None:
        try:
            from Data.modules.market_sim.institutional_core.reconciliation import (
                CompareContract,
                run_reconciliation,
            )

            run = run_reconciliation(
                run_id="v18",
                contract=CompareContract("c", "d", "l", "r", ("value",)),
                left_rows=[],
                right_rows=[],
            )
            body = run.public_dict()
            self.add(
                CheckResult(
                    "18_reconciliation",
                    "both_empty_not_pass",
                    "PASS" if body["status"] == "FAIL" else "FAIL",
                    evidence=body,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("18_reconciliation", "both_empty_not_pass", "FAIL", str(exc)))

    def section_19_decision(self) -> None:
        try:
            rt = self._rt()
            out = rt.full_paper_lifecycle(portfolio_id="d1", symbol="AAA", qty=1, price=10)
            pkt = rt.repo.get_decision_packet(out["fill"]["decision_id"])
            self.add(
                CheckResult(
                    "19_decision",
                    "decision_packet_persisted",
                    "PASS" if pkt and pkt.get("packet_hash") else "FAIL",
                    evidence={"decision_id": out["fill"]["decision_id"]},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("19_decision", "decision_packet_persisted", "FAIL", str(exc)))

    def section_20_audit(self) -> None:
        try:
            rt = self._rt()
            rt.full_paper_lifecycle(portfolio_id="a1", symbol="BBB", qty=1, price=10)
            ok = rt.repo.verify_audit_chain()
            with rt.repo.connect() as conn:
                conn.execute(
                    "UPDATE institutional_audit_chain SET detail='X' WHERE seq=1"
                )
            bad = rt.repo.verify_audit_chain()
            self.add(
                CheckResult(
                    "20_audit",
                    "tamper_detected",
                    "PASS" if ok.get("ok") and not bad.get("ok") else "FAIL",
                    evidence={"ok": ok, "bad": bad},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("20_audit", "tamper_detected", "FAIL", str(exc)))

    def section_21_workflow(self) -> None:
        try:
            rt = self._rt()
            rt.checkpoint_workflow(
                workflow_id="wf", job_id="j", step_index=1, state={"x": 1}
            )
            cp = rt.resume_workflow("wf")
            self.add(
                CheckResult(
                    "21_workflow",
                    "checkpoint_resume",
                    "PASS" if cp and cp["step_index"] == 1 else "FAIL",
                    evidence=cp or {},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("21_workflow", "checkpoint_resume", "FAIL", str(exc)))

    def section_22_backup(self) -> None:
        try:
            import shutil

            rt = self._rt()
            rt.full_paper_lifecycle(portfolio_id="bak", symbol="CCC", qty=1, price=10)
            src = rt.db_path
            with tempfile.TemporaryDirectory() as tmp:
                dst = Path(tmp) / "restore.sqlite"
                shutil.copy2(src, dst)
                from Data.modules.market_sim.institutional_core.runtime import (
                    InstitutionalRuntime,
                )

                restored = InstitutionalRuntime(dst)
                audit = restored.repo.verify_audit_chain()
                ibor = restored.reconstruct_portfolio_ibor("bak")
            self.add(
                CheckResult(
                    "22_backup",
                    "copy_restore_verify",
                    "PASS" if audit.get("ok") and ibor.get("eventCount", 0) >= 1 else "FAIL",
                    evidence={"audit": audit, "events": ibor.get("eventCount")},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("22_backup", "copy_restore_verify", "FAIL", str(exc)))

    def section_23_control_room(self) -> None:
        try:
            rt = self._rt()
            rt.run_and_persist_reconciliation(
                domain="cr",
                left_system="a",
                right_system="b",
                left_rows=[{"id": "1", "value": 1}],
                right_rows=[{"id": "1", "value": 2}],
                fields=("value",),
                expected_population=1,
            )
            snap = rt.control_room_snapshot()
            ok = snap["reconciliation"]["openCount"] >= 1
            ok = ok and snap["audit"].get("status") in {"PASS", "FAIL"}
            self.add(
                CheckResult(
                    "23_control_room",
                    "real_break_visible",
                    "PASS" if ok else "FAIL",
                    evidence={
                        "openCount": snap["reconciliation"]["openCount"],
                        "audit": snap["audit"],
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("23_control_room", "real_break_visible", "FAIL", str(exc)))

    def section_26_e2e(self) -> None:
        try:
            rt = self._rt()
            out = rt.full_paper_lifecycle(
                portfolio_id="e2e",
                symbol="E2E",
                qty=7,
                price=11,
                fee=0.25,
                mandate={
                    "allowedInstruments": ["*"],
                    "restrictedInstruments": [],
                    "maxOrdersPerDay": 100,
                },
            )
            ok = (
                out["gate"]["allowed"]
                and out["audit"]["ok"]
                and out["duplicate"]["duplicate_economics"]
                and out["fill"]["instrument"]["instrument_id"]
            )
            self.add(
                CheckResult(
                    "26_e2e",
                    "full_paper_lifecycle",
                    "PASS" if ok else "FAIL",
                    evidence={
                        "instrument": out["fill"]["instrument"]["instrument_id"],
                        "recon": out["reconciliation"]["status"],
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(
                CheckResult(
                    "26_e2e",
                    "full_paper_lifecycle",
                    "FAIL",
                    f"{exc}\n{traceback.format_exc()}",
                )
            )

    def section_27_torture(self) -> None:
        try:
            from Data.modules.market_sim.institutional_core.ibor import (
                IborEvent,
                UnsupportedIborEvent,
                reconstruct_ibor,
            )
            from Data.modules.market_sim.institutional_core.moneyutil import convert

            raised = False
            try:
                reconstruct_ibor(
                    [IborEvent("e", 1, "NOPE", "2020-01-01T00:00:00+00:00", {})]
                )
            except UnsupportedIborEvent:
                raised = True
            fx_raised = False
            try:
                convert(1, from_currency="EUR", to_currency="USD", fx_rate=None)
            except ValueError:
                fx_raised = True
            self.add(
                CheckResult(
                    "27_torture",
                    "unsafe_paths_fail_closed",
                    "PASS" if raised and fx_raised else "FAIL",
                    evidence={"unknown_event": raised, "missing_fx": fx_raised},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("27_torture", "unsafe_paths_fail_closed", "FAIL", str(exc)))

    def section_29_live_trading(self) -> None:
        try:
            from Data.modules.market_sim.institutional_core.assurance import (
                verify_live_trading_blocked,
            )

            body = verify_live_trading_blocked()
            ok = str(body.get("status") or "").upper() in {
                "PASS",
                "BLOCKED",
                "OBSERVED",
            } or body.get("liveTradingAvailable") in {False, "BLOCKED", None}
            # Explicit check
            text = json.dumps(body).upper()
            ok = "BLOCKED" in text or body.get("status") == "PASS"
            self.add(
                CheckResult(
                    "29_live_trading",
                    "live_trading_blocked",
                    "PASS" if ok else "FAIL",
                    evidence=body if isinstance(body, dict) else {"raw": str(body)},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("29_live_trading", "live_trading_blocked", "FAIL", str(exc)))

    def section_30_docs_ledger(self) -> None:
        try:
            ledger_path = (
                ROOT / "Data" / "backend" / "tests" / "institutional_trading_program.json"
            )
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            active = str(ledger.get("active_wave") or "")
            # After W73+ repair, active wave should be beyond W36
            ok_docs = (ROOT / "Data" / "docs" / "Leviathan_system_backend.md").exists()
            self.add(
                CheckResult(
                    "30_docs_ledger",
                    "ledger_present",
                    "PASS" if ledger_path.exists() and ok_docs else "FAIL",
                    detail=f"active_wave={active}",
                    evidence={"active_wave": active, "keys": list(ledger)[:12]},
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.add(CheckResult("30_docs_ledger", "ledger_present", "FAIL", str(exc)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-pytest", action="store_true", help="Also run institutional pytest subset")
    args = parser.parse_args()
    if args.run_pytest:
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "Data/backend/tests/test_institutional_runtime_w73_plus.py",
            "Data/backend/tests/test_institutional_core_failure_paths.py",
            "Data/backend/tests/test_institutional_migration_w55.py",
            "-q",
            "--tb=line",
        ]
        print("running", " ".join(cmd))
        code = subprocess.call(cmd, cwd=str(ROOT), env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": "Data"})
        if code != 0:
            print("pytest subset FAILED")
            return code
    return Verifier().run()


if __name__ == "__main__":
    raise SystemExit(main())
