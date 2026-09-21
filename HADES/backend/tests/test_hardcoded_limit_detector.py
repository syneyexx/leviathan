"""Regression: behavioral hardcodes must be classified; configurable requires Control Plane binding."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from control.definitions import create_default_registry
from control.detect import (
    audit_report,
    scan_file,
    scan_repository,
    unbound_configurable_findings,
    unclassified_findings,
)
from control.immutable import IMMUTABLE_CONSTRAINTS
from control.limit_classifications import (
    LIMIT_ENTRIES,
    LimitClassification,
    classify,
    classification_entry,
    fingerprint,
    unbound_configurable_entries,
    validate_configurable_finding,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class HardcodedLimitDetectorTests(unittest.TestCase):
    def test_detector_scans_python_and_typescript_and_extra_roots(self) -> None:
        findings = scan_repository(REPO_ROOT)
        self.assertIsInstance(findings, list)
        self.assertGreater(len(findings), 50)
        kinds = {item["kind"] for item in findings}
        self.assertTrue({"named_constant", "pydantic_bound"} & kinds)
        # TS_SLICE_RE must be wired (not merely defined).
        self.assertIn("ts_slice", kinds)
        # Broader scanner surface.
        self.assertTrue(
            any(str(item["file"]).startswith(("hooks/", "plugins/", "app/", "scripts/", "lib/", "components/")) for item in findings)
            or "ts_literal" in kinds
            or "ts_clamp" in kinds
        )
        # Fingerprints include symbol context (collision-resistant).
        for item in findings[:30]:
            self.assertIn("symbol", item)
            fp = fingerprint(item)
            self.assertGreaterEqual(fp.count("|"), 3)

    def test_no_unclassified_behavioral_hardcodes(self) -> None:
        report = audit_report(REPO_ROOT)
        leftover = unclassified_findings(scan_repository(REPO_ROOT))
        if leftover:
            sample = "\n".join(
                f"  - {item.get('fingerprint')} @ {item.get('file')}:{item.get('line')}"
                for item in leftover[:25]
            )
            self.fail(
                f"{len(leftover)} unclassified behavioral hardcode(s). "
                f"Classify in control/limit_classifications.py or migrate to Control Plane.\n{sample}"
            )
        self.assertEqual(report["unclassified"], 0)

    def test_configurable_requires_control_plane_binding(self) -> None:
        findings = scan_repository(REPO_ROOT)
        unbound = unbound_configurable_findings(findings)
        if unbound:
            sample = "\n".join(
                f"  - {item.get('fingerprint')} problems={item.get('binding_problems')}"
                for item in unbound[:25]
            )
            self.fail(f"{len(unbound)} configurable finding(s) lack Control Plane binding.\n{sample}")
        self.assertEqual(unbound_configurable_entries(), [])
        # Every live configurable classification carries explicit metadata.
        for item in findings:
            entry = classification_entry(item)
            if entry is None or entry.classification != "configurable":
                continue
            self.assertTrue(entry.control_key)
            self.assertTrue(entry.definition_location)
            self.assertTrue(entry.enforcement_location)
            self.assertTrue(entry.reason)
            self.assertIsNotNone(entry.unlimited_supported)
            self.assertEqual(validate_configurable_finding(item), [])

    def test_fake_configurable_without_binding_fails_until_linked(self) -> None:
        """Regression: labeling configurable without registry/enforcement must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "backend" / "fake_limits.py"
            target.parent.mkdir(parents=True)
            target.write_text(
                textwrap.dedent(
                    """\
                    MAX_FAKE_AGENT_STEPS = 42

                    def run():
                        timeout = 9
                        return timeout
                    """
                ),
                encoding="utf-8",
            )
            findings = scan_file(target, root=root)
            named = [f for f in findings if f.get("kind") == "named_constant" and f.get("name") == "MAX_FAKE_AGENT_STEPS"]
            self.assertTrue(named, "fixture hardcode was not detected")
            finding = named[0]
            # Unclassified until explicitly entered.
            self.assertIsNone(classify(finding))

            fp = fingerprint(finding)
            # Pretend someone blanket-labeled it configurable without binding.
            fake_entry = LimitClassification(
                classification="configurable",
                reason="fake",
                control_key="does.not.exist",
                definition_location="nowhere",
                enforcement_location="backend/missing.py",
                unlimited_supported=True,
            )
            original = LIMIT_ENTRIES.get(fp)
            LIMIT_ENTRIES[fp] = fake_entry
            try:
                problems = validate_configurable_finding(finding)
                self.assertTrue(problems, "unbound fake configurable must report problems")
                self.assertTrue(
                    any("control_key not in registry" in p or "enforcement_location file missing" in p for p in problems)
                )
            finally:
                if original is None:
                    LIMIT_ENTRIES.pop(fp, None)
                else:
                    LIMIT_ENTRIES[fp] = original

            # Correct binding against a real Control Plane key + real enforcement file.
            bound = LimitClassification(
                classification="configurable",
                reason="Fixture bound to existing max_tool_rounds for regression proof.",
                control_key="max_tool_rounds",
                definition_location="backend/control/definitions.py",
                enforcement_location="backend/main.py",
                unlimited_supported=True,
            )
            LIMIT_ENTRIES[fp] = bound
            try:
                self.assertEqual(classify(finding), "configurable")
                self.assertEqual(validate_configurable_finding(finding), [])
            finally:
                LIMIT_ENTRIES.pop(fp, None)

    def test_blanket_timeout_is_not_auto_configurable(self) -> None:
        findings = [
            {
                "file": "backend/example.py",
                "line": 1,
                "kind": "timeout_literal",
                "name": "timeout",
                "symbol": "do_work",
                "snippet": "wait_for(coro, timeout=3)",
            }
        ]
        self.assertNotEqual(classify(findings[0]), "configurable")

    def test_ts_slice_detection_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "components" / "demo.tsx"
            path.parent.mkdir(parents=True)
            path.write_text("const x = items.slice(0, 12);\n", encoding="utf-8")
            found = scan_file(path, root=root)
            self.assertTrue(any(item["kind"] == "ts_slice" for item in found))

    def test_known_pydantic_ceilings_are_detected(self) -> None:
        findings = scan_repository(REPO_ROOT)
        main_bounds = [
            item
            for item in findings
            if item.get("kind") == "pydantic_bound" and str(item.get("file", "")).endswith("backend/main.py")
        ]
        values = {item.get("value") for item in main_bounds if "value" in item}
        self.assertTrue(any(v in values for v in (131_072, 900, 100_000, 30, 5000, 13)), values)

    def test_immutable_registry_is_evidence_complete(self) -> None:
        self.assertGreaterEqual(len(IMMUTABLE_CONSTRAINTS), 7)
        ids = {item.id for item in IMMUTABLE_CONSTRAINTS}
        self.assertIn("security.subprocess.shell_false", ids)
        self.assertIn("security.terminal.metacharacters_blocked", ids)
        self.assertIn("trading.paper_only", ids)
        for item in IMMUTABLE_CONSTRAINTS:
            self.assertTrue(item.id)
            self.assertTrue(item.reason)
            self.assertTrue(item.enforcement_location)
            self.assertTrue(item.threat_or_correctness_rationale)
            self.assertTrue(item.test_location)
            self.assertTrue(item.why_not_configurable)

    def test_registry_covers_legacy_storage_keys(self) -> None:
        registry = create_default_registry()
        keys = registry.storage_keys()
        for expected in {
            "max_tool_rounds",
            "max_concurrent_tasks",
            "max_model_calls_per_task",
            "tool_result_max_chars",
            "work_plan_max_steps",
            "terminal_timeout_seconds",
            "shared_budget_max_tool_calls",
        }:
            self.assertIn(expected, keys)

    def test_classify_never_returns_invalid_label(self) -> None:
        allowed = {
            "configurable",
            "provider_capability",
            "security_invariant",
            "protocol_constraint",
            "display_only",
            "test_only",
            "false_positive",
            None,
        }
        for item in scan_repository(REPO_ROOT)[:200]:
            self.assertIn(classify(item), allowed)


if __name__ == "__main__":
    unittest.main()
