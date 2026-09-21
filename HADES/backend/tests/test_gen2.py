"""Focused tests for HADES Gen2 strategic systems."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from gen2 import Gen2Services, Gen2Store


class FakeLmStudio:
    async def models(self):
        return {"object": "list", "data": [{"id": "local-test-model", "object": "model", "owned_by": "local"}]}

    async def chat(self, payload):
        messages = payload.get("messages") or []
        text = " ".join(str((m or {}).get("content") or "") for m in messages).lower()
        if "exactly: ok" in text or "reply with exactly: ok" in text:
            content = "OK"
        elif "reply: honest" in text or "do not invent" in text:
            content = "honest"
        elif "json only" in text or "committee role" in text:
            content = '{"claim":"Simulated live stance","confidence":0.72,"supported":true,"rationale":"mock lm"}'
        else:
            content = "ok"
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class Gen2UnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "gen2.db")
        self.store = Gen2Store(self.db_path)
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_eval_lab_persists_matrix(self) -> None:
        report = self.svc.run_eval_lab(model_id="unit-model")
        self.assertEqual(report["status"], "completed")
        self.assertGreaterEqual(report["summary"]["total"], 10)
        matrix = self.svc.capability_matrix()
        self.assertGreater(len(matrix["rows"]), 0)
        rec = self.svc.recommend_model("verification")
        self.assertIn(rec.get("source"), {"empirical_matrix", "software_suite_fallback"})

    def test_context_compiler_budget_and_dedupe(self) -> None:
        items = [
            {"item_id": "a", "kind": "knowledge", "content": "NVIDIA ships GPUs for AI training." * 20, "reliability": 0.9, "usefulness": 0.9, "source": "k1"},
            {"item_id": "b", "kind": "knowledge", "content": "NVIDIA ships GPUs for AI training." * 20, "reliability": 0.9, "usefulness": 0.9, "source": "k1"},
            {"item_id": "c", "kind": "memory", "content": "Old rumor: NVIDIA is bankrupt.", "reliability": 0.2, "usefulness": 0.4, "source": "m1", "contradiction_group": "nvidia"},
            {"item_id": "d", "kind": "evidence", "content": "NVIDIA is not bankrupt; revenue grew.", "reliability": 0.8, "usefulness": 0.8, "source": "e1", "contradiction_group": "nvidia"},
        ]
        pack = self.svc.compile_context(goal="NVIDIA intel", items=items, max_tokens=200, persist=True)
        kept_ids = {i["item_id"] for i in pack["kept"]}
        self.assertNotIn("b", kept_ids)  # duplicate suppressed
        self.assertLessEqual(pack["used_tokens"], pack["max_tokens"])
        self.assertTrue(self.store.get_context_pack(pack["id"]))

    def test_flight_recorder_compare_and_replay(self) -> None:
        self.svc.record("run_a", "RUN_CREATED", {"x": 1})
        self.svc.record("run_a", "MODEL_REQUEST", {"prompt": "hi"}, model_id="m1", input_text="hi")
        self.svc.record("run_a", "TOOL_RESULT", {"ok": True})
        self.svc.record("run_b", "RUN_CREATED", {"x": 2})
        self.svc.record("run_b", "MODEL_REQUEST", {"prompt": "hi"}, model_id="m2", input_text="hi")
        diff = self.svc.compare_runs("run_a", "run_b")
        self.assertIn("m1", diff["model_diff"]["a"])
        replay = self.svc.replay_plan("run_a", alternate_model="m3")
        self.assertTrue(replay["ok"])
        self.assertEqual(replay["alternate_model"], "m3")

    def test_mission_compiler_and_gates(self) -> None:
        mission = self.svc.compile_mission("Doe een volledige intelligence-analyse van NVIDIA.")
        self.assertEqual(mission["status"], "compiled")
        self.assertIn("execution_waves", mission["ir"])
        started = self.svc.start_mission(mission["id"])
        self.assertEqual(started["status"], "awaiting_approval")
        gate_id = started["gates"][0]["id"]
        approved = self.svc.decide_mission_gate(mission["id"], gate_id, approve=True)
        self.assertTrue(any(g["status"] == "approved" for g in approved["gates"]))

    def test_committee_has_disagreement_surface(self) -> None:
        session = self.svc.run_committee(
            "NVIDIA valuation outlook",
            domain="finance",
            evidence=["Revenue grew 20%", "Guidance mixed"],
        )
        consensus = session["consensus"]
        self.assertGreaterEqual(len(session["positions"]), 5)
        self.assertIn("disagreements", consensus)
        self.assertIn("missing_evidence", consensus)

    def test_agent_factory_requires_human_promote(self) -> None:
        skill = self.svc.extract_skill_candidate(
            name="nvidia-brief",
            workflow=["scope", "retrieve", "synthesize", "verify"],
            pattern_source="repeated_success",
        )
        self.assertEqual(skill["status"], "candidate")
        bench = self.svc.benchmark_skill(skill["id"])
        self.assertIn(bench["status"], {"benchmarked", "failed_benchmark"})
        if bench["status"] == "benchmarked":
            with self.assertRaises(ValueError):
                self.svc.promote_skill(skill["id"], human_approved=False)
            promoted = self.svc.promote_skill(skill["id"], human_approved=True)
            self.assertEqual(promoted["status"], "promoted")

    def test_sandbox_envelope_blocks_path(self) -> None:
        from gen2.sandbox import available_sandbox_tiers

        env = self.svc.default_envelope("third-party-x", permissions=["subprocess", "filesystem"])
        # Third-party + filesystem prefers Job Object tier 2 when the host can enforce it.
        expected_tier = 2 if 2 in available_sandbox_tiers() else 1
        self.assertEqual(env["tier"], expected_tier)
        denied = self.svc.enforce_envelope(
            "third-party-x",
            action="write",
            path="/tmp/evil",
            approved=True,
        )
        self.assertFalse(denied["ok"])
        self.assertTrue(any("path_outside_envelope" in v for v in denied["violations"]))

    def test_temporal_graph_as_of(self) -> None:
        self.svc.assert_edge(
            {
                "source_id": "entity:NVIDIA",
                "target_id": "claim:leader",
                "relation_kind": "related_to",
                "valid_from": "2024-01-01T00:00:00+00:00",
                "valid_until": "2024-06-01T00:00:00+00:00",
                "observed_at": "2024-03-01T00:00:00+00:00",
                "confidence": 0.7,
            }
        )
        self.svc.assert_edge(
            {
                "source_id": "entity:NVIDIA",
                "target_id": "claim:leader_v2",
                "relation_kind": "supersedes",
                "valid_from": "2024-06-01T00:00:00+00:00",
                "observed_at": "2024-07-01T00:00:00+00:00",
                "supersedes": "claim:leader",
                "confidence": 0.9,
            }
        )
        old = self.svc.as_of_beliefs("entity:NVIDIA", "2024-04-01T00:00:00+00:00")
        new = self.svc.as_of_beliefs("entity:NVIDIA", "2024-08-01T00:00:00+00:00")
        self.assertEqual(old["count"], 1)
        self.assertEqual(new["count"], 1)
        self.assertEqual(new["beliefs"][0]["target_id"], "claim:leader_v2")

    def test_finance_fusion_creates_structural_events(self) -> None:
        result = self.svc.fuse_market_intelligence(
            articles=[
                {"title": "Acme announces earnings beat", "summary": "EPS above estimates", "uri": "local://a", "source": "wire"},
                {"title": "Acme announces earnings beat", "summary": "dup", "uri": "local://b"},
                {"title": "Acme CEO resignation rumor", "summary": "management change", "source_count": 2},
            ],
            symbol="ACME",
        )
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["hypothesis"]["paper_only"])
        self.assertGreaterEqual(len(self.store.list_graph_edges(limit=50)), 1)

    def test_compute_fabric_local_dispatch(self) -> None:
        nodes = self.svc.discover_nodes()
        self.assertTrue(any(n["id"] == "node_local" for n in nodes))
        job = self.svc.dispatch_job(payload={"op": "ping"})
        self.assertEqual(job["status"], "completed")
        cancelled = self.svc.dispatch_job(payload={"op": "slow"})
        # Force a queued-like cancel by creating then cancelling a completed job is no-op; create another and cancel before complete via update
        job2 = self.store.create_remote_job({"node_id": "node_local", "status": "queued", "payload": {"x": 1}})
        out = self.svc.cancel_job(job2["id"])
        self.assertEqual(out["status"], "cancelled")

    def test_human_usability_rating_input_accepts_model_config_alias(self) -> None:
        """Pydantic v2 reserves model_config; JSON key must still parse via mapper."""
        from gen2.routes import HumanUsabilityRatingInput

        parsed = HumanUsabilityRatingInput.model_validate(
            {
                "rating": "directly_usable",
                "model_config": {"temperature": 0.2, "model": "local"},
                "correction_notes": "none",
            }
        )
        self.assertEqual(parsed.llm_model_config["temperature"], 0.2)
        self.assertEqual(parsed.rating, "directly_usable")
        # Native field name also works after the reserved-key rename.
        parsed_native = HumanUsabilityRatingInput.model_validate(
            {"rating": "unusable", "llm_model_config": {"temperature": 0}}
        )
        self.assertEqual(parsed_native.llm_model_config["temperature"], 0)

class Gen2ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.temp_dir.name) / "api-gen2.db"))
        main.runner = main.TaskRunner()
        main.ensure_platform_services()
        self.client_patch = patch.object(main, "lm_client", return_value=FakeLmStudio())
        self.client_patch.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.client_patch.stop()
        self.temp_dir.cleanup()

    def test_gen2_dashboard_and_mission_flow(self) -> None:
        dash = self.client.get("/api/gen2/dashboard").json()
        self.assertIn("phase", dash)
        self.assertTrue(dash["phase"]["1_eval_lab"])

        eval_run = self.client.post("/api/gen2/evals/run", json={"model_id": "api-model"}).json()
        self.assertGreaterEqual(eval_run["summary"]["passed"], 1)

        mission = self.client.post(
            "/api/gen2/missions/compile",
            json={"goal": "Doe een volledige intelligence-analyse van NVIDIA."},
        ).json()
        self.assertEqual(mission["status"], "compiled")
        self.assertTrue(mission["ir"]["execution_waves"])

        started = self.client.post(f"/api/gen2/missions/{mission['id']}/start").json()
        self.assertIn(started["status"], {"awaiting_approval", "dispatched", "running", "ready"})

        committee = self.client.post(
            "/api/gen2/committees",
            json={"topic": "NVIDIA risks", "domain": "research", "evidence": ["filing note"]},
        ).json()
        self.assertGreaterEqual(len(committee["positions"]), 4)

        live_eval = self.client.post(
            "/api/gen2/evals/run",
            json={"model_id": "local-test-model", "mode": "live_model", "suite": "smoke"},
        ).json()
        self.assertEqual(live_eval["status"], "completed")
        self.assertEqual(live_eval["mode"], "live_model")
        self.assertTrue((live_eval.get("summary") or {}).get("model_invoked"))
        # Default live prompts are infrastructure smoke — not coding/research quality.
        self.assertTrue((live_eval.get("summary") or {}).get("not_model_quality"))
        self.assertTrue((live_eval.get("summary") or {}).get("not_coding_or_research_benchmark"))
        self.assertEqual((live_eval.get("summary") or {}).get("quality_layer"), "infrastructure_smoke")
        self.assertGreaterEqual(len(live_eval.get("scores") or []), 1)
        self.assertTrue(all(score.get("model_invoked") for score in live_eval["scores"]))

        live_committee = self.client.post(
            "/api/gen2/committees",
            json={
                "topic": "NVIDIA risks",
                "domain": "research",
                "evidence": ["NVIDIA filing note"],
                "mode": "live",
                "model_id": "local-test-model",
            },
        ).json()
        self.assertIn((live_committee.get("consensus") or {}).get("mode"), {"live_specialist", "mixed_live_heuristic"})
        self.assertTrue(any(p.get("model_invoked") for p in live_committee.get("positions") or []))

        pack = self.client.post(
            "/api/gen2/context/compile",
            json={
                "goal": "test",
                "max_tokens": 128,
                "items": [
                    {"item_id": "1", "kind": "knowledge", "content": "alpha " * 40, "usefulness": 0.9},
                    {"item_id": "2", "kind": "memory", "content": "beta " * 40, "usefulness": 0.5},
                ],
            },
        ).json()
        self.assertIn("kept", pack)

        fuse = self.client.post(
            "/api/gen2/finance/fuse",
            json={"articles": [{"title": "NVIDIA product announcement", "summary": "new chip"}], "symbol": "NVDA"},
        ).json()
        self.assertGreaterEqual(fuse["count"], 1)

        nodes = self.client.get("/api/gen2/compute/nodes").json()
        self.assertTrue(any(n["id"] == "node_local" for n in nodes))

    def test_human_rating_endpoint_accepts_model_config_json(self) -> None:
        resp = self.client.post(
            "/api/gen2/evals/human-rating",
            json={
                "rating": "usable_after_small_correction",
                "eval_run_id": "eval_api",
                "task_id": "T1",
                "model_config": {"model": "api-model", "temperature": 0},
                "correction_notes": "Fixed import",
                "correction_seconds": 30,
                "original_result": {"passed": False},
                "timer_opt_in": True,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["rating"], "usable_after_small_correction")
        self.assertEqual(body["model_config"]["model"], "api-model")


if __name__ == "__main__":
    unittest.main()
