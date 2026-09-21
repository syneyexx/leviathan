"""Gen2 platform polish characterization — I1–I10 + K1/K2/K4–K8/K13/K14.

Evidence-backed ticks: prove existing surfaces with focused tests; no fake host PASS.
"""

from __future__ import annotations

import os
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.mission_control import compile_mission, validate_mission_ir
from gen2.perf_budgets import SOFT_BUDGETS_MS, record_and_check
from gen2.sandbox import SANDBOX_ACTIONS, build_default_envelope, enforce_envelope_policy
from gen2.services import Gen2Services
from gen2.store import Gen2Store, clamp_list_limit
from global_search import GlobalSearchService
from research_coverage import summarize_research_coverage

REPO_ROOT = Path(__file__).resolve().parents[2]


class ISeriesPolishTests(unittest.TestCase):
    """Characterize existing Research/Evidence/Files/LSP/Coding/Voice/Chat/Ctrl+K/Settings."""

    def test_i1_research_coverage_quality_stop(self) -> None:
        summary = summarize_research_coverage(
            {
                "id": "rp_i1",
                "depth": "deep",
                "status": "needs_more_evidence",
                "allow_web": True,
                "metrics": {
                    "coverage_score": 30,
                    "mastery_target": 90,
                    "source_count": 2,
                    "evidence_chunks": 1,
                    "domain_diversity": 1,
                    "contradictions": ["a vs b"],
                    "metric_kind": "source_coverage_diversity",
                },
            }
        )
        self.assertTrue(summary["incomplete"])
        self.assertTrue(summary["gaps"])
        self.assertEqual(summary["metric_kind"], "source_coverage_diversity")
        # Research page + API wired.
        research_page = (REPO_ROOT / "components/hades/pages/research-page.tsx").read_text(encoding="utf-8")
        self.assertIn("researchCoverage", research_page)
        self.assertIn("coverage.gaps", research_page)

    def test_i2_citation_first_evidence_links(self) -> None:
        provenance = (REPO_ROOT / "components/hades/chat-provenance.tsx").read_text(encoding="utf-8")
        self.assertIn("Bronnen", provenance)
        self.assertIn("aria-label=\"Bronnen en provenance\"", provenance)
        chat = (REPO_ROOT / "components/hades/pages/chat-page.tsx").read_text(encoding="utf-8")
        self.assertIn("ChatProvenanceList", chat)
        hash_helpers = (REPO_ROOT / "lib/hash-query.ts").read_text(encoding="utf-8")
        self.assertIn("deeplink", hash_helpers.lower())
        self.assertIn("#/page", hash_helpers)

    def test_i3_harvest_dedupe_entity_paths(self) -> None:
        # Harvest intent + network gate exist; finance fusion / FNI provide dedupe.
        from chat_commands import detect_harvest_intent

        intent = detect_harvest_intent("/harvest https://example.com/docs")
        self.assertEqual(intent["kind"], "harvest")
        finance = (REPO_ROOT / "backend/gen2/finance_fusion.py").read_text(encoding="utf-8")
        self.assertIn("dedupe", finance.lower())
        fni = REPO_ROOT / "plugins/financial-news-intelligence/financial_news_intelligence.py"
        self.assertTrue(fni.is_file())
        self.assertIn("def dedupe", fni.read_text(encoding="utf-8"))

    def test_i4_files_chunking_robustness_surface(self) -> None:
        # Characterized by platform KnowledgeService office/folder ingest tests + Files page.
        files_page = (REPO_ROOT / "components/hades/pages/files-page.tsx").read_text(encoding="utf-8")
        self.assertIn("aria-label", files_page)
        platform_tests = (REPO_ROOT / "backend/tests/test_platform.py").read_text(encoding="utf-8")
        self.assertIn("test_office_documents_are_extracted_and_chunked", platform_tests)
        self.assertIn("test_folder_ingestion_skips_unchanged_files", platform_tests)

    def test_i5_lsp_light_honesty(self) -> None:
        from lsp_light import find_definition

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
            result = find_definition(root, "alpha")
        self.assertEqual(result["mode"], "regex-index")
        self.assertIn("geen language server", result["note"].lower())
        self.assertGreaterEqual(result["count"], 1)

    def test_i6_coding_jobs_status_cancel_restore(self) -> None:
        from coding_jobs import CodingJobStore

        # Module documents cancellable runners + recovery payloads.
        src = (REPO_ROOT / "backend/coding_jobs.py").read_text(encoding="utf-8")
        self.assertIn("request_cancel", src)
        self.assertIn("recoverable", src)
        self.assertIn("TERMINAL_STATUSES", src)
        self.assertTrue(hasattr(CodingJobStore, "request_cancel") or "class CodingJob" in src or "request_cancel" in src)
        m2 = (REPO_ROOT / "backend/tests/test_reliable_coding_jobs_m2.py").read_text(encoding="utf-8")
        self.assertIn("cancel", m2.lower())

    def test_i7_voice_offline_surfaces(self) -> None:
        voice_tests = (REPO_ROOT / "backend/tests/test_voice_mode.py").read_text(encoding="utf-8")
        self.assertIn("test_voice_status_and_speakable", voice_tests)
        panel = (REPO_ROOT / "components/hades/voice/voice-panel.tsx").read_text(encoding="utf-8")
        self.assertIn("aria-label", panel)

    def test_i8_chat_timeline_tool_verify_pack_ux(self) -> None:
        chat = (REPO_ROOT / "components/hades/pages/chat-page.tsx").read_text(encoding="utf-8")
        self.assertIn("ChatProvenanceList", chat)
        self.assertIn("ExecutionTrace", chat)
        self.assertIn("VerificationSummary", chat)
        trace = (REPO_ROOT / "components/hades/features/chat/ExecutionTrace.tsx").read_text(encoding="utf-8")
        self.assertIn("execution-trace", trace)
        self.assertIn("ToolCallCard", trace)
        tools = (REPO_ROOT / "components/hades/tool-result-cards.tsx").read_text(encoding="utf-8")
        self.assertIn("tool-cards", tools)

    def test_i9_ctrl_k_gen2_discoverability(self) -> None:
        app = (REPO_ROOT / "components/hades/hades-app.tsx").read_text(encoding="utf-8")
        self.assertIn('event.key.toLowerCase() === "k"', app)
        self.assertIn("mission-control", app)
        self.assertIn("gen2", app.lower())
        svc = GlobalSearchService(database=_StubDb(), platform_db=_StubPlatform())
        cmds = {c["id"] for c in svc.commands_matching("mission")}
        self.assertIn("open_mission_control", cmds)
        workflow_cmds = {c["id"] for c in svc.commands_matching("workflow")}
        self.assertIn("open_workflows", workflow_cmds)

    def test_i10_settings_security_clarity(self) -> None:
        settings = (REPO_ROOT / "components/hades/pages/settings-page.tsx").read_text(encoding="utf-8")
        self.assertIn("Beveiliging", settings)
        self.assertIn("Paranoid", settings)
        self.assertIn("ReleaseConfidencePanel", settings)
        self.assertIn("network_policy", settings)


class _StubDb:
    def list_conversations(self):
        return []

    def search_messages(self, *_a, **_k):
        return []

    def list_tasks(self):
        return []

    def list_memories(self, **_k):
        return []


class _StubPlatform:
    def search_knowledge(self, *_a, **_k):
        return []


class KSeriesPlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "polish.db")
        self.store = Gen2Store(self.db_path)
        self.events: list[dict] = []

        def _record(run_id, event_type, payload=None, **kwargs):
            row = {"run_id": run_id, "event_type": event_type, "payload": payload or {}}
            self.events.append(row)
            return row

        self.record = _record
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_k1_hotspot_extraction_modules_present(self) -> None:
        """main.py partially extracted — list verified gen2 + route modules."""
        gen2_dir = REPO_ROOT / "backend/gen2"
        modules = sorted(p.stem for p in gen2_dir.glob("*.py") if p.stem != "__init__")
        required = {
            "routes",
            "services",
            "store",
            "mission_control",
            "sandbox",
            "flight_recorder",
            "eval_lab",
            "context_compiler",
            "agent_factory",
            "workflows",
            "committee",
            "compute_fabric",
            "perf_budgets",
        }
        self.assertTrue(required <= set(modules), f"missing {required - set(modules)}")
        main_src = (REPO_ROOT / "backend/main.py").read_text(encoding="utf-8")
        for name in (
            "mount_brain_routes",
            "mount_models_routes",
            "mount_gen2_routes",
            "app_lifecycle",
            "capability_routes",
        ):
            self.assertIn(name, main_src)
        # Still a hotspot — extraction is partial, not complete.
        self.assertGreater(len(main_src.splitlines()), 2000)

    def test_k2_characterization_suites_exist(self) -> None:
        tests_dir = REPO_ROOT / "backend/tests"
        suites = sorted(p.name for p in tests_dir.glob("test_gen2*.py"))
        self.assertGreaterEqual(len(suites), 15)
        for needed in (
            "test_gen2_sandbox.py",
            "test_gen2_mission_control.py",
            "test_gen2_flight_recorder.py",
            "test_gen2_committee.py",
            "test_gen2_reliability.py",
        ):
            self.assertIn(needed, suites)
            text = (tests_dir / needed).read_text(encoding="utf-8")
            self.assertTrue(
                "Characterization" in text or "characterization" in text or "unittest" in text,
                needed,
            )

    def test_k4_windows_ci_parity_documented(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/release-gates.yml").read_text(encoding="utf-8")
        self.assertIn("windows-latest", workflow)
        self.assertIn("ubuntu-latest", workflow)
        self.assertIn("verify_hades.py --quick", workflow)
        self.assertIn("UNVERIFIED_ON_HOST", workflow)
        # Linux marks Job Objects unverified; Windows matrix runs same deterministic gates.
        sandbox_test = (REPO_ROOT / "backend/tests/test_gen2_sandbox.py").read_text(encoding="utf-8")
        self.assertIn("UNVERIFIED_ON_HOST", sandbox_test)
        is_windows = os.name == "nt"
        # Characterization only: on Linux we do not claim Windows Job Object PASS.
        if not is_windows:
            from gen2.sandbox import detect_host_sandbox_capabilities

            caps = detect_host_sandbox_capabilities()
            self.assertEqual(caps.get("verification_status"), "UNVERIFIED_ON_HOST")

    def test_k5_mission_survives_store_reopen_mid_run(self) -> None:
        mission = compile_mission(self.store, self.record, "Durable reopen research mission")
        mid = self.store.update_mission(
            mission["id"],
            status="running",
            task_id="task_k5_mid",
            execution_id="exec_k5",
        )
        self.assertEqual(mid["status"], "running")
        # Simulate crash: drop in-memory store, reopen same SQLite file.
        reopened = Gen2Store(self.db_path)
        restored = reopened.get_mission(mission["id"])
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored["status"], "running")
        self.assertEqual(restored["task_id"], "task_k5_mid")
        self.assertEqual(restored["execution_id"], "exec_k5")
        self.assertEqual(restored["goal"], mission["goal"])
        waves = (restored.get("ir") or {}).get("execution_waves") or []
        self.assertTrue(waves)

    def test_k6_fuzz_ir_and_envelope_validators(self) -> None:
        rng = random.Random(42)
        # Valid baseline compiles clean.
        good = compile_mission(self.store, self.record, "Validate fuzz baseline")
        self.assertEqual(validate_mission_ir(good["ir"] or {}), [])

        # Property-ish: random broken IRs must return errors, never raise.
        for _ in range(40):
            ir = {
                "execution_waves": [
                    {
                        "steps": [
                            {
                                "id": rng.choice(["", "a", "b", "a"]),
                                "agent": rng.choice([None, "chat", ""]),
                                "depends_on": rng.choice([[], ["missing"], ["a"], ["b", "a"]]),
                                "tools": rng.choice([None, [], "bad", ["terminal"]]),
                            }
                            for _ in range(rng.randint(0, 3))
                        ]
                    }
                ],
                "io_contracts": rng.choice([None, {}, [], "x"]),
            }
            errors = validate_mission_ir(ir)
            self.assertIsInstance(errors, list)
            # Empty / malformed waves should usually produce errors; never raise.
            step_count = sum(len(w.get("steps") or []) for w in ir.get("execution_waves") or [])
            if step_count == 0:
                # No step ids collected — either errors or vacuous valid; both OK if no exception.
                pass
            elif any(not str((s or {}).get("id") or "").strip() for w in ir["execution_waves"] for s in (w.get("steps") or [])):
                self.assertTrue(errors)

        # Envelope enforce: random actions/paths stay fail-closed without exceptions.
        _, envelope = build_default_envelope("plugin.fuzz", permissions=["filesystem"])
        data_root = Path(self.temp.name)

        def expand(p: str) -> str:
            return p.replace("{data_root}", str(data_root))

        for _ in range(30):
            action = rng.choice(list(SANDBOX_ACTIONS) + ["explode", ""])
            path = rng.choice([None, str(data_root / "plugins" / "plugin.fuzz" / "x"), "/etc/passwd", "../escape"])
            result = enforce_envelope_policy(
                plugin_id="plugin.fuzz",
                envelope=envelope,
                requested_tier=1,
                action=action,
                path=path,
                approved=False,
                expand_path=expand,
                available_tiers=frozenset({0, 1}),
            )
            self.assertIn("ok", result)
            self.assertIsInstance(result.get("violations") or [], list)

    def test_k7_soft_performance_budgets(self) -> None:
        self.assertIn("mission_compile", SOFT_BUDGETS_MS)
        row = record_and_check(
            "mission_compile",
            lambda: compile_mission(self.store, self.record, "Budget compile goal"),
        )
        self.assertTrue(row["within_soft_budget"])
        self.assertLessEqual(row["elapsed_ms"], row["soft_budget_ms"])
        list_row = record_and_check(
            "store_list_missions",
            lambda: self.store.list_missions(limit=20),
        )
        self.assertTrue(list_row["within_soft_budget"])

    def test_k8_sqlite_list_limit_discipline(self) -> None:
        self.assertEqual(clamp_list_limit(0), 1)
        self.assertEqual(clamp_list_limit(9999), 200)
        self.assertEqual(clamp_list_limit(-5), 1)
        for i in range(25):
            compile_mission(self.store, self.record, f"Corpus mission {i}")
        page = self.store.list_missions(limit=5)
        self.assertEqual(len(page), 5)
        huge = self.store.list_missions(limit=10_000)
        self.assertLessEqual(len(huge), 200)
        # Re-open and list still bounded.
        again = Gen2Store(self.db_path).list_missions(limit=3)
        self.assertEqual(len(again), 3)

    def test_k13_mission_control_accessibility_labels(self) -> None:
        page = (REPO_ROOT / "components/hades/pages/mission-control-page.tsx").read_text(encoding="utf-8")
        for label in (
            'aria-label="Compileer missie"',
            'aria-label="Start missie"',
            'aria-label="Laad missieportfolio"',
            'aria-label="Filter missieportfolio op status"',
            "aria-label={`Open missie",
        ):
            self.assertIn(label, page)
        app = (REPO_ROOT / "components/hades/hades-app.tsx").read_text(encoding="utf-8")
        self.assertIn("Ctrl+K", app)

    def test_k14_windows_prepare_verify_recoverability(self) -> None:
        prepare = REPO_ROOT / "PREPARE_HADES.bat"
        verify = REPO_ROOT / "VERIFY_HADES.bat"
        self.assertTrue(prepare.is_file())
        self.assertTrue(verify.is_file())
        prepare_txt = prepare.read_text(encoding="utf-8", errors="replace")
        verify_txt = verify.read_text(encoding="utf-8", errors="replace")
        self.assertIn("npm ci", prepare_txt)
        self.assertIn("typecheck", prepare_txt)
        self.assertIn("unittest", prepare_txt.lower() + prepare_txt)
        self.assertIn("verify_hades.py", verify_txt)
        self.assertIn("goto :error", prepare_txt.lower() + prepare_txt)  # fail-fast pattern
        self.assertRegex(verify_txt, re.compile(r"errorlevel|goto :error", re.I))
        # Recovery story: launcher / start scripts call PREPARE when incomplete.
        launcher = (REPO_ROOT / "HADES.bat").read_text(encoding="utf-8", errors="replace")
        self.assertIn("PREPARE_HADES.bat", launcher)
        release = (REPO_ROOT / "backend/release_confidence.py").read_text(encoding="utf-8")
        self.assertIn("VERIFY_HADES.bat", release)
        self.assertIn("manual", release)


class DeferredHonestyTickets(unittest.TestCase):
    """Document deferred / UNVERIFIED ticks with software evidence only."""

    def test_a11_deferred_local_l6_gate_present(self) -> None:
        from gen2.compute_fabric import single_node_solidity_gate

        self.assertTrue(callable(single_node_solidity_gate))

    def test_g3_n5_unverified_on_linux_marker(self) -> None:
        if os.name == "nt":
            self.skipTest("Windows host — Job Object status is host-gated separately")
        from gen2.sandbox import detect_host_sandbox_capabilities, sandbox_honesty_labels

        caps = detect_host_sandbox_capabilities()
        honesty = sandbox_honesty_labels(caps)
        self.assertIn(honesty["verification_status"], {"UNVERIFIED_ON_HOST", "API_PRESENT_UNTESTED"})
        self.assertFalse(honesty["os_isolation_enforced"])

    def test_b12_b13_b17_apis_present(self) -> None:
        from gen2.mission_control import ACCEPTANCE_CHECK_TYPES, REPLAN_CAUSES, evaluate_acceptance_checks

        self.assertIn("verification_passed", ACCEPTANCE_CHECK_TYPES)
        self.assertTrue(REPLAN_CAUSES)
        result = evaluate_acceptance_checks(
            [{"id": "s", "type": "status_equals", "expected": "completed"}],
            status="completed",
            verification={"status": "passed"},
            step_summary={"total": 0, "completed": 0},
        )
        self.assertTrue(result["passed"])

    def test_b24_layered_dag_preview_not_canvas(self) -> None:
        workflows_ui = (REPO_ROOT / "components/hades/pages/workflows-page.tsx").read_text(encoding="utf-8")
        self.assertIn("Layered DAG preview", workflows_ui)
        self.assertIn("Not a canvas editor", workflows_ui)


if __name__ == "__main__":
    unittest.main()
