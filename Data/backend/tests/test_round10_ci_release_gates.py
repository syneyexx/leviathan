"""Round 10 — CI and release gates exit suite."""

from __future__ import annotations

import unittest

from Data.modules.release import (
    GateCheck,
    GateMeasurement,
    GateSeverity,
    ReleaseGateRunner,
    default_leviathan_ci_plan,
    evaluation_relevance_gate,
    interpret_command_result,
    measurement_counts_as_success,
)


class CiPlanHonestyTests(unittest.TestCase):
    def test_hades_and_editor_are_not_applicable(self) -> None:
        plan = default_leviathan_ci_plan()
        by_id = {s.suite_id: s for s in plan.suites}
        self.assertEqual(by_id["hades"].measurement, GateMeasurement.NOT_APPLICABLE)
        self.assertEqual(by_id["editor"].measurement, GateMeasurement.NOT_APPLICABLE)
        payload = plan.public_dict()
        self.assertTrue(payload["truth"]["hades_and_editor_out_of_scope"])
        self.assertTrue(payload["truth"]["skipped_unavailable_is_not_success"])
        self.assertTrue(payload["policy"]["exclude_hades"])
        self.assertTrue(payload["policy"]["exclude_editor"])

    def test_unavailable_suite_is_unmeasured_not_pass(self) -> None:
        result = interpret_command_result(
            suite_id="frontend_build",
            name="Frontend build",
            command="npm run build",
            exit_code=None,
            available=False,
        )
        self.assertEqual(result.measurement, GateMeasurement.UNMEASURED)
        self.assertFalse(measurement_counts_as_success(result.measurement))
        self.assertTrue(result.public_dict()["truth"]["unmeasured_is_not_pass"])

    def test_not_applicable_is_not_pass(self) -> None:
        result = interpret_command_result(
            suite_id="hades",
            name="HADES",
            command="",
            exit_code=None,
            applicable=False,
        )
        self.assertEqual(result.measurement, GateMeasurement.NOT_APPLICABLE)
        self.assertFalse(measurement_counts_as_success(result.measurement))

    def test_release_ok_false_when_any_unmeasured(self) -> None:
        plan = default_leviathan_ci_plan(backend_exit=0)  # others still UNMEASURED
        summary = plan.public_dict()["summary"]
        self.assertGreater(summary["unmeasured"], 0)
        self.assertFalse(summary["release_ok"])

    def test_release_ok_when_required_suites_pass(self) -> None:
        plan = default_leviathan_ci_plan(
            backend_exit=0,
            frontend_typecheck_exit=0,
            frontend_lint_exit=0,
            frontend_test_exit=0,
            frontend_build_exit=0,
            security_exit=0,
            migration_exit=0,
            integrity_exit=0,
            fixture_separation_exit=0,
            round_exit=0,
        )
        summary = plan.public_dict()["summary"]
        self.assertEqual(summary["fail"], 0)
        self.assertEqual(summary["unmeasured"], 0)
        self.assertGreater(summary["not_applicable"], 0)
        self.assertTrue(summary["release_ok"])

    def test_failed_exit_is_fail(self) -> None:
        result = interpret_command_result(
            suite_id="backend_unit",
            name="Backend",
            command="pytest",
            exit_code=1,
        )
        self.assertEqual(result.measurement, GateMeasurement.FAIL)


class ReleaseGateMeasurementTests(unittest.TestCase):
    def test_feature_off_eval_gate_is_not_applicable(self) -> None:
        # Simulate the Round 10 main.py posture for eval_platform OFF.
        gate = GateCheck(
            gate_id="evaluation_relevance",
            name="Relevant evaluation recorded",
            severity=GateSeverity.INFO,
            passed=True,
            detail="eval_platform flag OFF — NOT_APPLICABLE",
            measurement=GateMeasurement.NOT_APPLICABLE,
        )
        payload = gate.public_dict()
        self.assertEqual(payload["measurement"], "NOT_APPLICABLE")
        self.assertTrue(payload["truth"]["not_applicable_is_not_pass"])
        self.assertFalse(measurement_counts_as_success(GateMeasurement.NOT_APPLICABLE))

    def test_unmeasured_eval_with_require_pass_is_not_pass(self) -> None:
        gate = evaluation_relevance_gate(
            {"recorded": True, "measurement": "UNMEASURED", "promotable": False, "detail": "soft"},
            require_pass=True,
            severity=GateSeverity.BLOCK,
        )
        self.assertFalse(gate.passed)
        self.assertEqual(gate.measurement, GateMeasurement.UNMEASURED)

    def test_skipped_unavailable_cannot_make_release_all_pass(self) -> None:
        runner = ReleaseGateRunner(
            checks=[
                lambda: GateCheck(
                    "core",
                    "core",
                    GateSeverity.BLOCK,
                    True,
                    "ok",
                    measurement=GateMeasurement.PASS,
                ),
                lambda: GateCheck(
                    "optional_gpu",
                    "GPU suite",
                    GateSeverity.INFO,
                    True,
                    "unavailable",
                    measurement=GateMeasurement.NOT_APPLICABLE,
                ),
                lambda: GateCheck(
                    "probe",
                    "Cancellation probe",
                    GateSeverity.WARN,
                    True,
                    "not run",
                    measurement=GateMeasurement.UNMEASURED,
                ),
            ]
        )
        report = runner.run()
        payload = report.public_dict()
        self.assertTrue(payload["truth"]["skipped_unavailable_is_not_success"])
        self.assertEqual(payload["metadata"]["not_applicable_count"], 1)
        self.assertEqual(payload["metadata"]["unmeasured_count"], 1)
        self.assertEqual(payload["metadata"]["pass_count"], 1)
        # ready may still be true (no BLOCK fail), but PASS count ≠ total suites
        self.assertTrue(report.ready)
        self.assertNotEqual(
            payload["metadata"]["pass_count"],
            payload["metadata"]["check_count"] if "check_count" in payload["metadata"] else 3,
        )


class WorkflowPresenceTests(unittest.TestCase):
    def test_github_workflow_exists_and_excludes_hades_editor(self) -> None:
        from pathlib import Path

        wf = Path(".github/workflows/leviathan-ci.yml")
        self.assertTrue(wf.is_file(), "Round 10 requires reproducible CI workflow")
        text = wf.read_text(encoding="utf-8")
        self.assertIn("leviathan-ci", text)
        self.assertIn("NOT_APPLICABLE", text)
        self.assertIn("HADES", text)
        self.assertIn("editor", text)
        self.assertIn("Data/backend/tests", text)
        self.assertIn("npm run build", text)
        self.assertIn("Data/frontend", text)
        # Must not invoke HADES or editor test commands as required green checks.
        self.assertNotIn("pytest HADES", text)
        self.assertNotIn("pytest editor", text)
        self.assertNotIn("cd editor", text)
        self.assertNotIn("cd HADES", text)


if __name__ == "__main__":
    unittest.main()
